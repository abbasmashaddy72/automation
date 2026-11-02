"""Maintained replacements run only in disposable paths or mocked Podman."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
import bootstrap
import recipes
import webui
import automation


class ProjectLayoutTests(unittest.TestCase):
    def test_preserves_existing_projects_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'sites'
            self.assertEqual(len(bootstrap.layout(root, dry_run=True)['missing']), 9)
            self.assertFalse(root.exists())
            bootstrap.layout(root)
            project = root/'Local'/'keep.txt'
            project.write_text('user data')
            self.assertEqual(bootstrap.layout(root)['missing'], [])
            self.assertEqual(project.read_text(), 'user data')
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_conflicts_and_links_are_rejected_before_any_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'sites'; root.mkdir()
            (root/'Testing').write_text('keep')
            with self.assertRaises(ValueError): bootstrap.layout(root)
            self.assertFalse((root/'Local').exists())
            link = Path(temp)/'link'; link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError): bootstrap.layout(link)
        for path in ('/', '/etc/automation-sites', '/var/automation-sites'):
            with self.assertRaises(ValueError): bootstrap.layout(path, dry_run=True)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError): bootstrap.layout(Path(temp)/'..'/'..'/'etc'/'automation-sites',dry_run=True)


class ConfigurationExportTests(unittest.TestCase):
    def test_prefixed_new_command_cannot_fall_through_to_package_installation(self):
        for command in ('configuration','webui'):
            with patch('automation.packages_action') as install,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):automation.main(['--yes',command,'install'])
                install.assert_not_called()

    def test_php_guidance_uses_lerd_and_never_exports_host_configuration(self):
        with patch('recipes.export') as export,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(recipes.main(['php']),0)
            self.assertEqual(recipes.main(['php','--standalone','--output','/unused','--yes']),3)
            export.assert_not_called()
        self.assertIn('lerd php:ini',out.getvalue())
        self.assertNotIn('upload_max_filesize',out.getvalue())

    def test_device_rules_require_exact_ids_and_no_world_write(self):
        text = recipes.udev('05AC','12ab')['70-automation-usb.rules']
        self.assertIn('ATTR{idVendor}=="05ac"', text)
        self.assertIn('ATTR{idProduct}=="12ab"', text)
        self.assertIn('MODE="0660"', text)
        for vendor,product in (('*','1234'),('1234','*'),('x;run','1234'),(None,'1234')):
            with self.assertRaises(ValueError): recipes.udev(vendor,product)

    def test_approved_export_has_checksums_and_private_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'review'
            files = recipes.udev('05ac','12ab')
            recipes.export(files,output,dry_run=True)
            self.assertFalse(output.exists())
            with self.assertRaises(ValueError): recipes.export(files,output)
            manifest = recipes.export(files,output,yes=True)
            self.assertEqual(json.loads((output/'manifest.json').read_text()), manifest)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for name in files:
                self.assertEqual((output/name).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError): recipes.export(files,output,yes=True)

    def test_cli_check_dryrun_and_missing_consent_never_write(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'review'
            for args in (['--check','--yes'], ['--dry-run','--yes'], []):
                result = subprocess.run(['bash',str(ROOT/'setup.sh'),'configuration','udev',
                    '--vendor','05ac','--product','12ab','--output',str(output),*args],
                    capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode, 2 if not args else 0, result.stderr)
                self.assertFalse(output.exists())

    def test_export_refuses_symlink_parent_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); link=root/'link'; link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError): recipes.export(recipes.udev('05ac','12ab'),link/'new',yes=True)
            existing=root/'existing'; existing.write_text('user config')
            with self.assertRaises(ValueError): recipes.export(recipes.udev('05ac','12ab'),existing,yes=True)
            self.assertEqual(existing.read_text(),'user config')

    def test_retired_php_cli_never_creates_export_even_with_yes(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            output=Path(temp)/'php'
            self.assertEqual(recipes.main(['php','--standalone','--output',str(output),'--yes']),3)
            self.assertFalse(output.exists())


class OpenWebUIContracts(unittest.TestCase):
    image = 'ghcr.io/open-webui/open-webui@sha256:'+'a'*64
    identifier = 'b'*64
    token = 'c'*32

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)/'state'
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME':str(self.state)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.value = {'schema':1,'id':self.identifier,'image':self.image,'token':self.token,'port':3000}
        self.row = {'Id':self.identifier,'Config':{'Labels':{webui.LABEL:self.token},'Image':self.image},
                    'Mounts':[{'Destination':'/app/backend/data','Name':webui.VOLUME}], 'State':{'Running':False}}

    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()): return webui.main(list(args))

    def test_plan_requires_pinned_upstream_and_does_not_touch_engine_or_state(self):
        with patch('webui.call') as call:
            self.assertEqual(self.main('plan','--image',self.image),0)
            self.assertEqual(self.main('install','--image',self.image,'--dry-run','--yes'),0)
            call.assert_not_called()
        self.assertFalse(self.state.exists())
        for image in ('ghcr.io/open-webui/open-webui:main','malicious/image@sha256:'+'a'*64):
            with self.assertRaises(ValueError): webui.run_command(image,3000,self.token)
        command = webui.run_command(self.image,3000,self.token)
        self.assertIn('127.0.0.1:3000:8080', command)
        self.assertIn('--pull=never', command)
        self.assertNotIn('--privileged', command)

    def test_changed_identity_label_image_or_mount_refused(self):
        webui.owned(self.row,self.value)
        import copy
        rows = []
        for key, value in (('Id','d'*64), ('Mounts',[])):
            row=copy.deepcopy(self.row); row[key]=value; rows.append(row)
        row=copy.deepcopy(self.row);row['Config']['Labels']={};rows.append(row)
        row=copy.deepcopy(self.row);row['Config']['Image']='foreign';rows.append(row)
        for row in rows:
            with self.assertRaises(ValueError): webui.owned(row,self.value)

    def test_failed_inspection_is_not_treated_as_absence(self):
        with patch('webui.call', return_value=subprocess.CompletedProcess([],125,'','failed')):
            with self.assertRaises(ValueError): webui.inspect('container',webui.NAME)

    def test_lifecycle_requires_approval_and_removal_never_deletes_data(self):
        with patch('webui.os.geteuid',return_value=1000), patch('webui.shutil.which',return_value='/usr/bin/podman'),\
             patch('webui.call',return_value=subprocess.CompletedProcess([],0,'true\n','')) as call,\
             patch('webui.inspect',return_value=self.row),patch('webui.receipt',return_value=self.value):
            self.assertEqual(self.main('stop'),4)
            self.assertEqual(call.call_count,1)
            self.assertEqual(self.main('remove','--yes'),0)
            self.assertEqual(call.call_args.args[0],['rm',self.identifier])
            self.assertNotIn('volume',call.call_args.args[0])
            self.row['State']['Running']=True
            with self.assertRaises(ValueError): self.main('remove','--yes')

    def test_install_without_pull_or_approval_never_creates_resources(self):
        with patch('webui.os.geteuid',return_value=1000),patch('webui.shutil.which',return_value='/usr/bin/podman'),\
             patch('webui.call',return_value=subprocess.CompletedProcess([],0,'true\n','')) as call,\
             patch('webui.inspect',return_value=None):
            self.assertEqual(self.main('install','--image',self.image),4)
            self.assertEqual(self.main('install','--image',self.image,'--yes'),5)
            self.assertEqual(call.call_count,2)
            self.assertFalse(self.state.exists())

    def test_observed_install_writes_private_receipt_and_repeat_is_noop(self):
        resources={}
        def query(kind,name):
            if kind=='image': return {'Id':'d'*64}
            return resources.get(kind)
        def execute(command,**kwargs):
            if command[0]=='info': stdout='true\n'
            elif command[:2]==['volume','create']:
                token=command[command.index('--label')+1].split('=',1)[1]
                resources['volume']={'Labels':{webui.LABEL:token},'CreatedAt':'2026-11-02T12:00:00Z'}; stdout=webui.VOLUME
            elif command[0]=='run':
                token=command[command.index('--label')+1].split('=',1)[1]
                self.row['Config']['Labels'][webui.LABEL]=token
                resources['container']=self.row; stdout=self.identifier
            else: raise AssertionError(command)
            return subprocess.CompletedProcess(command,0,stdout,'')
        with patch('webui.os.geteuid',return_value=os.getuid()),patch('webui.shutil.which',return_value='/usr/bin/podman'),\
             patch('webui.call',side_effect=execute) as call,patch('webui.inspect',side_effect=query):
            # The test environment may itself run as root; override only the guard,
            # keeping real state ownership checks aligned with temporary files.
            with patch('webui.os.geteuid',side_effect=lambda:1000):
                with patch('webui.journal.state_dir',side_effect=lambda create=False: self.private_state(create)):
                    self.assertEqual(self.main('install','--image',self.image,'--yes'),0)
                    receipt=webui.receipt()
                    self.assertEqual(receipt['id'],self.identifier)
                    self.assertEqual(webui.receipt_path().stat().st_mode&0o777,0o600)
                    before=webui.receipt_path().read_bytes()
                    call.reset_mock()
                    self.assertEqual(self.main('install','--image',self.image,'--yes'),0)
                    self.assertEqual(call.call_count,1)
                    self.assertEqual(webui.receipt_path().read_bytes(),before)

    def private_state(self, create):
        if create:self.state.mkdir(mode=0o700,exist_ok=True)
        return self.state

    def test_foreign_volume_refused_before_any_installation(self):
        with patch('webui.os.geteuid',return_value=1000),patch('webui.shutil.which',return_value='/usr/bin/podman'),\
             patch('webui.call',return_value=subprocess.CompletedProcess([],0,'true','')) as call,\
             patch('webui.inspect',side_effect=lambda kind,name:{} if kind=='volume' else None):
            # Empty inspection dictionaries must still count as existing resources.
            with self.assertRaises(ValueError): self.main('install','--image',self.image,'--yes')
            self.assertEqual(call.call_count,1)

    def test_rootful_engine_refused_before_inspection(self):
        with patch('webui.os.geteuid',return_value=1000),patch('webui.shutil.which',return_value='/usr/bin/podman'),\
             patch('webui.call',return_value=subprocess.CompletedProcess([],0,'false','')),patch('webui.inspect') as inspect:
            with self.assertRaises(ValueError):self.main('status')
            inspect.assert_not_called()
