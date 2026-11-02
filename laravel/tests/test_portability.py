"""Independent folder configuration, isolation and prerequisite safety."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from laravel_toolkit import config,provision,deploy,prerequisites,templates
from argparse import Namespace

class PortableFolder(unittest.TestCase):
    def test_copy_runs_outside_parent_and_ignores_parent_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp);folder=parent/'portable';shutil.copytree(ROOT,folder,ignore=shutil.ignore_patterns('.env','__pycache__'))
            (parent/'.env').write_text('THIS IS NOT VALID CONFIGURATION\n')
            env={**os.environ,'PYTHONPATH':str(parent)}
            for name in ('provision','deploy'):
                result=subprocess.run(['bash',str(folder/('laravel-'+name+'.sh')),'--help'],cwd='/',env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((folder/'.env').exists())
            for flags in (['--init-config','--check'],['--init-config','--dry-run']):
                result=subprocess.run(['bash',str(folder/'laravel-provision.sh'),*flags],cwd='/',capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr);self.assertFalse((folder/'.env').exists())
            result=subprocess.run(['bash',str(folder/'laravel-provision.sh'),'--init-config','--yes'],cwd='/',capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((folder/'.env').stat().st_mode&0o777,0o600)

    def test_private_config_merge_preserves_original_bytes_and_rejects_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);defaults=root/'defaults.env';defaults.write_text('LARAVEL_DOMAIN=\nLARAVEL_RETAIN=5\n')
            local=root/'.env';original=b'# preserved\nLARAVEL_DOMAIN=example.test\n';local.write_bytes(original);local.chmod(0o600)
            with patch.object(config,'ROOT',root),patch.object(config,'DEFAULTS',defaults):
                self.assertTrue(config.init(yes=True)['written']);self.assertTrue(local.read_bytes().startswith(original))
                self.assertEqual(config.load()['LARAVEL_DOMAIN'],'example.test')
                self.assertFalse(config.init(yes=True)['written'])
                local.write_text('LARAVEL_DOMAIN=$(id)\n')
                with self.assertRaises(ValueError):config.load()
                local.write_bytes(original);local.chmod(0o644)
                with self.assertRaises(ValueError):config.load()

    def test_cli_overrides_own_config_and_resolves_files_from_folder(self):
        defaults=config.load();defaults.update(LARAVEL_DOMAIN='configured.test',LARAVEL_PHP_REPOSITORY='config/repository.json')
        with patch.object(config,'load',return_value=defaults),patch.object(provision,'provision',return_value=0) as call:
            provision.main(['--domain=explicit.test','--dry-run'])
            args=call.call_args.args[0]
            self.assertEqual(args.domain,'explicit.test');self.assertEqual(args.php_repository,ROOT/'config/repository.json')

    def test_prerequisites_require_approval_and_never_install_during_checks(self):
        args=Namespace(php_version='8.3',frontend='none',check=True,dry_run=False,yes=True,auto_prerequisites=True)
        with patch.object(prerequisites.shutil,'which',return_value=None),patch.object(prerequisites.common,'run') as run:
            with self.assertRaises(ValueError):prerequisites.ensure(args)
            run.assert_not_called()
            args.check=False;args.yes=False
            with self.assertRaises(ValueError):prerequisites.ensure(args)
            run.assert_not_called()

    def test_templates_are_bundled_and_resolved(self):
        args=Namespace(domain='example.test',deploy_user='deploy',queue='queue',scheduler=True)
        files,prefix=provision.templates(args,'8.3',Path('/srv/example.test'))
        self.assertGreaterEqual(len(files),7)
        for data,mode in files.values():self.assertNotIn(b'@@',data)
        with self.assertRaises(ValueError):templates.render('../outside.conf.tpl',{})

    def test_no_parent_python_imports_or_sourced_environment(self):
        for path in (ROOT/'src').rglob('*.py'):
            text=path.read_text()
            self.assertNotIn('from validate import',text)
            self.assertNotIn('from container_workflows import',text)
        for path in (ROOT/'lib').glob('*.sh'):
            self.assertNotIn('source "$BASE',path.read_text())

if __name__=='__main__':unittest.main()

class ConfigurationRecovery(unittest.TestCase):
    def test_power_loss_receipt_restores_owned_config_and_preserves_later_edits(self):
        from laravel_toolkit import common
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';state.mkdir(mode=0o700);target=root/'site.conf'
            manager=common.ManagedFiles(state);manager.apply({target:(b'original',0o644)},lambda:None)
            backup=state/('backup-'+'a'*32+'.json')
            common.save(backup,{str(target):{'before':__import__('base64').b64encode(b'original').decode(),'mode':0o644}})
            common.save(manager.pending,{'schema':1,'backup':backup.name,'after':{str(target):common.digest(b'candidate')}})
            target.write_bytes(b'candidate');manager.recover()
            self.assertEqual(target.read_bytes(),b'original');self.assertFalse(manager.pending.exists())
            common.save(manager.pending,{'schema':1,'backup':backup.name,'after':{str(target):common.digest(b'candidate')}})
            target.write_bytes(b'owner edit')
            with self.assertRaises(ValueError):manager.recover()
            self.assertEqual(target.read_bytes(),b'owner edit');self.assertTrue(manager.pending.exists())

    def test_tls_template_keeps_existing_https_without_duplicate_listeners(self):
        args=Namespace(domain='example.test',deploy_user='deploy',queue='none',scheduler=False)
        files,prefix=provision.templates(args,'8.3',Path('/srv/example.test'))
        data=files[Path('/etc/nginx/conf.d')/(prefix+'.conf')][0]
        secure=provision.tls_configuration(data,'example.test',Path('/srv/example.test'))
        self.assertEqual(secure.count(b'listen 80;'),1);self.assertEqual(secure.count(b'listen 443 ssl;'),1)
        self.assertIn(b'TLSv1.2 TLSv1.3',secure)

class OperationPrerequisites(unittest.TestCase):
    def test_rollback_never_installs_git_composer_or_node(self):
        args=Namespace(rollback=True,recover=False,queue='none',fpm_service=None,queue_service=None,php_version='8.3',frontend='auto',check=False,dry_run=False,yes=True)
        with patch.object(prerequisites.shutil,'which',return_value=None),patch.object(prerequisites.common,'run') as run:
            prerequisites.ensure(args);run.assert_not_called()
