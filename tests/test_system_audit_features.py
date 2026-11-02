"""Resource planning and desktop adapters without changing a live session."""
from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'lib'),str(ROOT/'ai')]
import resources
import automation
import desktop
import panels


class ResourcePlanning(unittest.TestCase):
    def args(self,**kwargs):return Namespace(**{'backend':'llamacpp','action':'configure','host':'127.0.0.1','cpu_threads':None,'cpu_quota':None,'port':None,'context':None,**kwargs})
    def test_auto_settings_validate_and_are_profile_safe(self):
        value={key:'auto' for key in ('AUTOMATION_AI_THREADS','AUTOMATION_AI_QUOTA','AUTOMATION_AI_PORT')}
        self.assertEqual(automation.validate_settings(value),value)
        with self.assertRaises(ValueError):automation.validate_settings({'AUTOMATION_AI_THREADS':'auto;command'})

    def test_cpu_memory_budget_and_port_are_resolved_without_gpu_claims(self):
        args=self.args()
        with patch('resources.settings',return_value={}),patch('resources.ai_health.hardware',return_value={}),patch('resources.budget',return_value=(8,512)),patch('resources.free_port',return_value=18091):
            result=resources.apply(args)
        self.assertEqual((args.cpu_threads,args.cpu_quota,args.port),(2,'200%',18091))
        self.assertIn('not inferred',result['acceleration'])

    def test_explicit_and_stored_overrides_are_preserved(self):
        args=self.args(cpu_threads=3,cpu_quota='150%',port=19000)
        with patch('resources.settings',return_value={}),patch('resources.ai_health.hardware') as hardware:
            resources.apply(args);hardware.assert_not_called()
        self.assertEqual((args.cpu_threads,args.cpu_quota,args.port),(3,'150%',19000))
        args=self.args()
        with patch('resources.settings',return_value={}),patch('resources.ai_health.hardware') as hardware:
            resources.apply(args,{'threads':2,'cpu_quota':175,'port':19001});hardware.assert_not_called()
        self.assertEqual((args.cpu_threads,args.cpu_quota,args.port),(2,'175%',19001))

    def test_fractional_cgroup_quota_and_zero_memory_are_not_treated_as_unlimited(self):
        args=self.args()
        with patch('resources.settings',return_value={}),patch('resources.ai_health.hardware',return_value={}),patch('resources.budget',return_value=(0.5,0)),patch('resources.free_port',return_value=19001):resources.apply(args)
        self.assertEqual((args.cpu_threads,args.cpu_quota),(1,'50%'))

    def test_occupied_port_is_skipped_without_terminating_its_owner(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));port=occupied.getsockname()[1]
            with patch.dict(resources.ai_health.DEFAULT_PORTS,{'llamacpp':port}):
                selected=resources.free_port('llamacpp')
            self.assertNotEqual(selected,port);self.assertEqual(occupied.getsockname()[1],port)


class CinnamonPanel(unittest.TestCase):
    def test_apply_idempotency_and_restore_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_CONFIG_HOME':temp}),patch('desktop.gsettings',return_value="['panel1:left:0:grouped-window-list@cinnamon.org:2']"):
            file=Path(temp)/'cinnamon/spices/grouped-window-list@cinnamon.org/2.json';file.parent.mkdir(parents=True)
            value={'pinned-apps':{'type':'generic','value':['old.desktop']},'unrelated':{'value':True}}
            file.write_text(json.dumps(value))
            before=panels.snapshot('cinnamon');after=panels.update(before,['firefox.desktop','firefox.desktop'])
            panels.write(after)
            self.assertEqual(json.loads(file.read_text())['pinned-apps']['value'],['old.desktop','firefox.desktop'])
            self.assertEqual(panels.update(panels.snapshot('cinnamon'),['firefox.desktop']),panels.snapshot('cinnamon'))
            panels.write(before);self.assertEqual(json.loads(file.read_text()),value)

    def test_ambiguous_or_uninitialized_applets_are_refused(self):
        with patch('desktop.gsettings',return_value="['panel1:left:0:grouped-window-list@cinnamon.org:2','panel2:left:0:grouped-window-list@cinnamon.org:3']"):
            with self.assertRaises(ValueError):panels.cinnamon_path()


class XFCEPanel(unittest.TestCase):
    def test_launcher_copies_preserve_exec_case_existing_items_and_restore(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_CONFIG_HOME':temp,'XDG_DATA_HOME':temp}):
            file=Path(temp)/'applications/firefox.desktop';file.parent.mkdir();file.write_text('[Desktop Entry]\nType=Application\nName=Fixture\nExec=fixture %U\n')
            folder=Path(temp)/'xfce4/panel/launcher-2';folder.mkdir(parents=True)
            (folder/'old.desktop').write_text('[Desktop Entry]\nType=Application\nName=Old\nExec=old\n')
            state={'items':['old.desktop']}
            def query(*args,**kwargs):
                if args==('--list','--verbose'):return '/plugins/plugin-2 launcher\n/panels/panel-1/plugin-ids 2\n'
                if '/panels/panel-1/plugin-ids' in args:return 'Value is an array with 1 items:\n2'
                if '--set' in args:state['items']=[args[i+1] for i,x in enumerate(args) if x=='--set'];return ''
                if '--reset' in args:state['items']=[];return ''
                return 'Value is an array with '+str(len(state['items']))+' items:\n'+'\n'.join(state['items'])
            with patch('panels.xfconf',side_effect=query):
                before=panels.snapshot('xfce');after=panels.update(before,['firefox.desktop'])
                panels.write(after)
                self.assertIn('Exec = fixture %U', (folder/'automation-firefox.desktop').read_text())
                self.assertEqual(state['items'],['old.desktop','automation-firefox.desktop'])
                self.assertEqual(panels.update(panels.snapshot('xfce'),['firefox.desktop']),panels.snapshot('xfce'))
                panels.write(before)
                self.assertEqual(state['items'],['old.desktop']);self.assertFalse((folder/'automation-firefox.desktop').exists())
                self.assertTrue((folder/'old.desktop').exists())

    def test_multiple_active_launcher_groups_are_not_guessed(self):
        def query(*args,**kwargs):
            return '/plugins/plugin-2 launcher\n/plugins/plugin-3 launcher\n/panels/panel-1/plugin-ids 2 3' if '--list' in args else 'Value is an array:\n2\n3'
        with patch('panels.xfconf',side_effect=query),self.assertRaises(ValueError):panels.xfce_plugin()


class DesktopPreservation(unittest.TestCase):
    def test_gnome_apply_appends_without_duplicates(self):
        state={'current':['old.desktop']}
        with tempfile.TemporaryDirectory() as temp,patch('desktop.detect',return_value={'favorites_adapter':'gnome'}),patch('desktop.shutil.which',return_value='/bin/gsettings'),\
            patch('desktop.applications',return_value=['new.desktop']),patch('desktop.snapshot',side_effect=lambda _:state['current']),\
            patch('desktop.write',side_effect=lambda adapter,value:state.update(current=value)),patch('desktop.backup_root',return_value=Path(temp)),contextlib.redirect_stdout(io.StringIO()):
            args=Namespace(action='apply',value=None,select=['new.desktop'],dry_run=False)
            self.assertEqual(desktop.main(args,lambda *_:True),0)
            self.assertEqual(state['current'],['old.desktop','new.desktop'])
            self.assertEqual(desktop.main(args,lambda *_:True),0)
            self.assertEqual(len(list(Path(temp).glob('*.json'))),1)
