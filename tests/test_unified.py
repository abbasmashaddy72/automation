"""Offline, non-destructive tests for the unified automation toolkit."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

a = module('automation_cli','lib/automation.py')
p = module('patch_manager','scripts/patch_manager.py')

class TestPlatform(unittest.TestCase):
    def test_detect_all_families(self):
        for dist,fam in [('arch','arch'),('manjaro','arch'),('cachyos','arch'),('debian','debian'),
                         ('ubuntu','debian'),('linuxmint','debian'),('pop','debian'),
                         ('fedora','fedora'),('rocky','rhel'),('almalinux','rhel'),
                         ('opensuse-tumbleweed','opensuse'),('opensuse-leap','opensuse'),
                         ('alpine','alpine')]:
            with self.subTest(dist=dist): self.assertEqual(a.get_family({'ID':dist}),fam)
    def test_id_like(self):
        self.assertEqual(a.get_family({'ID':'custom','ID_LIKE':'rhel fedora'}),'rhel')
    def test_unknown(self):
        self.assertEqual(a.get_family({'ID':'other'}),'unknown')
    def test_release_parser_is_not_shell(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'os-release'
            f.write_text('ID="ubuntu"\nID_LIKE=debian\nEVIL=$(touch /tmp/should_not_exist)\n')
            self.assertEqual(a.os_release(f)['ID'],'ubuntu')
    def test_managers(self):
        self.assertEqual(a.MANAGERS['opensuse'],'zypper')
        self.assertEqual(a.MANAGERS['alpine'],'apk')
    def test_no_lerd_on_openrc(self):
        info={'family':'alpine','arch':'x86_64','init':'other','user_systemd':False,'container':False,'wsl':False}
        self.assertTrue(a.lerd_compat(info))
    def test_no_lerd_on_container(self):
        info={'family':'arch','arch':'x86_64','init':'systemd','user_systemd':True,'container':True,'wsl':False}
        self.assertTrue(a.lerd_compat(info))
    def test_version_alias(self):
        self.assertEqual(a.package_native_name('python3','arch'),'python')
        self.assertEqual(a.package_native_name('python3','debian'),'python3')
    def test_aur_only_arch(self):
        with patch.object(a.shutil,'which',return_value='/mock/paru'):
            self.assertIsNone(a.aur_helper({'family':'debian'}))
            self.assertEqual(a.aur_helper({'family':'arch'}),'paru')

class TestConfig(unittest.TestCase):
    def test_config_priority_and_no_code_execution(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'.env'; f.write_text('AUTOMATION_LERD=false\nAUTOMATION_RETRIES=1\n')
            self.assertEqual(a.config_file(f)['AUTOMATION_LERD'],'false')
            f.write_text('AUTOMATION_LERD=$(touch /tmp/bad)\n')
            with self.assertRaises(ValueError): a.config_file(f)
    def test_invalid_key(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'.env'; f.write_text('UNSUPPORTED_CONFIG=foo\n')
            with self.assertRaises(ValueError): a.config_file(f)
    def test_default_preserved(self):
        entries=a.package_catalog({'family':'arch'})
        self.assertGreaterEqual(len(entries),44)
        self.assertIn('shelly',[e['id'] for e in entries])
        self.assertTrue(next(e['default'] for e in entries if e['id']=='lerd'))
    def test_nonarch_shows_unsupported_for_transparent_recommendations(self):
        entries=a.package_catalog({'family':'debian'})
        self.assertIn('shelly',[e['id'] for e in entries])
        self.assertIsNone(a.package_native_name('shelly','debian'))
        self.assertIn('lerd',[e['id'] for e in entries])
    def test_no_install_without_confirmation(self):
        import argparse
        ns=argparse.Namespace(dry_run=False,yes=False,non_interactive=True)
        self.assertFalse(a.approved(ns,'Run?'))
    def test_dry_run_never_invokes(self):
        import argparse
        ns=argparse.Namespace(dry_run=True)
        with patch.object(a.subprocess,'run') as runner:
            self.assertEqual(a.run(['sudo','example'],mutate=True,args=ns),0)
            runner.assert_not_called()
    def test_cli_help(self):
        result=subprocess.run(['bash',str(ROOT/'setup.sh'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('packages',result.stdout)
    def test_ai_help(self):
        result=subprocess.run(['bash',str(ROOT/'setup.sh'),'ai','--help'],capture_output=True,text=True)
        # top-level help is valid too
        self.assertEqual(result.returncode,0,result.stderr)

class TestPatch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'repo'; self.root.mkdir()
        self.backup=Path(self.tmp.name)/'backups'
        self.original=p.ROOT
        p.ROOT=self.root
        self.addCleanup(setattr,p,'ROOT',self.original)
        self.env=patch.dict('os.environ',{'AUTOMATION_PATCH_BACKUP_DIR':str(self.backup)})
        self.env.start(); self.addCleanup(self.env.stop)

    def mkzip(self,ops,payload):
        target=Path(self.tmp.name)/'update.zip'
        with zipfile.ZipFile(target,'w') as z:
            z.writestr('manifest.json',json.dumps({'format':1,'operations':ops}))
            for path,data in payload.items(): z.writestr('payload/'+path,data)
        return target

    def test_reject_traversal(self):
        for name in ('../evil','/tmp/evil','config/../../a','../.env','x\\y','C:/windows'):
            with self.subTest(name=name),self.assertRaises(ValueError): p.valid_name(name)
    def test_protect_env(self):
        for name in ('.env','.env.local','.env.foo','backups/a','logs/a','.git/config'):
            with self.subTest(name=name),self.assertRaises(ValueError): p.valid_name(name)
    def test_reject_symlink_target(self):
        (self.root/'link').symlink_to(self.backup, target_is_directory=True)
        with self.assertRaises(ValueError): p.target_path('link/a')
    def test_bad_payload_hash(self):
        ops=[{'action':'add','path':'new.txt','sha256':'0'*64}]
        with zipfile.ZipFile(self.mkzip(ops,{'new.txt':b'data'})) as z:
            with self.assertRaises(ValueError): p.read_zip(z)
    def test_reject_zip_slip(self):
        zpath=Path(self.tmp.name)/'malicious.zip'
        with zipfile.ZipFile(zpath,'w') as z:
            z.writestr('manifest.json','{"format":1,"operations":[]}')
            z.writestr('../evil','evil')
        with zipfile.ZipFile(zpath) as z:
            with self.assertRaises(ValueError): p.read_zip(z)
    def test_reject_zip_symlink(self):
        zpath=Path(self.tmp.name)/'malicious.zip'
        with zipfile.ZipFile(zpath,'w') as z:
            z.writestr('manifest.json','{"format":1,"operations":[]}')
            entry=zipfile.ZipInfo('payload/sym')
            entry.create_system=3; entry.external_attr=(0o120777<<16)
            z.writestr(entry,'/etc/passwd')
        with zipfile.ZipFile(zpath) as z:
            with self.assertRaises(ValueError): p.read_zip(z)
    def test_conflicts(self):
        (self.root/'x').write_text('original')
        self.assertFalse(p.check([{'action':'modify','path':'x','old_sha256':'0'*64}]))
    def test_apply_and_rollback(self):
        from hashlib import sha256
        (self.root/'old.txt').write_bytes(b'old')
        ops=[{'action':'modify','path':'old.txt','old_sha256':sha256(b'old').hexdigest(),'sha256':sha256(b'new').hexdigest()},
             {'action':'add','path':'fresh.txt','sha256':sha256(b'fresh').hexdigest()}]
        with zipfile.ZipFile(self.mkzip(ops,{'old.txt':b'new','fresh.txt':b'fresh'})) as z:
            self.assertEqual(p.apply(z,p.read_zip(z)),0)
        self.assertEqual((self.root/'old.txt').read_bytes(),b'new')
        self.assertEqual((self.root/'fresh.txt').read_bytes(),b'fresh')
        folder=next(self.backup.iterdir()); p.restore(folder)
        self.assertEqual((self.root/'old.txt').read_bytes(),b'old')
        self.assertFalse((self.root/'fresh.txt').exists())
    def test_delete_rename(self):
        from hashlib import sha256
        (self.root/'old.txt').write_bytes(b'old')
        ops=[{'action':'rename','from':'old.txt','path':'new.txt','old_sha256':sha256(b'old').hexdigest(),'sha256':sha256(b'copy').hexdigest()}]
        with zipfile.ZipFile(self.mkzip(ops,{'new.txt':b'copy'})) as z:
            self.assertEqual(p.apply(z,p.read_zip(z)),0)
        self.assertFalse((self.root/'old.txt').exists());self.assertTrue((self.root/'new.txt').exists())
        p.restore(next(self.backup.iterdir()))
        self.assertTrue((self.root/'old.txt').exists());self.assertFalse((self.root/'new.txt').exists())

if __name__=='__main__': unittest.main()

class TestPlansAndSafety(unittest.TestCase):
    def mkargs(self, **kwargs):
        import argparse
        base={'select':['git,curl'], 'exclude':['curl'], 'interactive':False, 'yes':False,
              'non_interactive':True, 'dry_run':True, 'command':'packages','action':'install'}
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_plan_exclusion_is_not_removal(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        with patch.object(a,'installed',return_value=False),patch.object(a,'available',return_value=True),\
             patch.object(a,'run',return_value=0) as runner,patch.object(a,'approved',return_value=True):
            import contextlib
            with io.StringIO() as out,contextlib.redirect_stdout(out):
                self.assertEqual(a.packages_action(self.mkargs(),info,{}),0)
                self.assertIn('git',out.getvalue())
                self.assertNotIn('curl ',out.getvalue())
            runner.assert_called_once()
            self.assertIn('git',runner.call_args.args[0])
            self.assertNotIn('remove',runner.call_args.args[0])

    def test_unapproved_install_does_not_run(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        with patch.object(a,'installed',return_value=False),patch.object(a,'available',return_value=True),\
             patch.object(a,'run') as runner,patch.object(a,'approved',return_value=False):
            self.assertEqual(a.packages_action(self.mkargs(dry_run=False),info,{}),4)
            runner.assert_not_called()

    def test_unknown_package_rejected(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        self.assertEqual(a.packages_action(self.mkargs(select=['malicious-command;touch']),info,{}),2)

    def test_package_manager_commands_are_argument_arrays(self):
        for fam,tool in [('arch','pacman'),('debian','apt-get'),('fedora','dnf'),
                         ('rhel','dnf'),('opensuse','zypper'),('alpine','apk')]:
            cmd=a.install_cmd('git',{'family':fam})
            self.assertEqual(cmd[1] if cmd[0]=='sudo' else cmd[0],tool)

    def test_default_lerd_not_on_headless(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        with patch.object(a,'installed',return_value=True),patch.object(a,'available',return_value=True):
            import contextlib
            with io.StringIO() as out,contextlib.redirect_stdout(out):
                args=self.mkargs(select=None,exclude=None,action='plan')
                self.assertEqual(a.packages_action(args,info,{}),0)
                self.assertNotIn('lerd ',out.getvalue())

    def test_rollback_refuses_modified_working_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'bk';folder.mkdir()
            root=Path(tmp)/'repo';root.mkdir()
            (root/'target').write_bytes(b'edited')
            (folder/'state.json').write_text(json.dumps({'originals':{'target':p.sha(b'old')},
                'applied':{'target':p.sha(b'applied')}}))
            (folder/'originals').mkdir();(folder/'originals/target').write_bytes(b'old')
            with patch.object(p,'ROOT',root):
                with self.assertRaisesRegex(ValueError,'Rollback conflict'):
                    p.restore(folder,verify_current=True)
                self.assertEqual((root/'target').read_bytes(),b'edited')
