"""Production contracts in temporary sites/repos; never provisions the host."""
from argparse import Namespace
import contextlib
import io
import json
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
from laravel_toolkit import common as p
from laravel_toolkit import deploy
from laravel_toolkit import provision


def native_php():
    # Never invoke a host Lerd/container wrapper as a native PHP test runtime.
    for name in ('/usr/bin/php','/usr/bin/php8.3','/usr/bin/php8.5','/usr/bin/php8.1'):
        path=Path(name)
        if path.is_file() and os.access(path,os.X_OK):
            with path.open('rb') as stream:
                if stream.read(4)==b'\x7fELF':return name
    return None

NATIVE_PHP=native_php()


class ProductionInputs(unittest.TestCase):
    def test_domains_repositories_and_sites_reject_shell_and_system_paths(self):
        for value in ('example.com;id','http://example.com','Example.COM','-option','a..test'):
            with self.assertRaises(ValueError):p.domain(value)
        for value in ('https://token:secret@example.com/repo','-flag','file:///tmp/repo','git@example.com:../secret'):
            with self.assertRaises(ValueError):deploy.repository(value)
        for value in ('/etc/site','/usr/site',str(ROOT/'site'),'/tmp/a\ncommand'):
            with self.assertRaises(ValueError):p.site_path(value)

    def test_external_url_checks_and_checksum_before_execution(self):
        for value in ('http://example.com/provision.sh','https://forge.laravel.com/servers/1','https://user:secret@example.com/script','https://example.com/script?token=secret'):
            with self.assertRaises(ValueError):p.https_url(value)
        body=b'#!/bin/bash\nprintf "fixture"\n'
        with patch('laravel_toolkit.common.fetch',return_value=body),patch('laravel_toolkit.common.run',return_value='') as run:
            self.assertEqual(p.verified_script('https://example.com/script',p.digest(body)),body)
            self.assertEqual(run.call_args.args[0],['bash','-n'])
            with self.assertRaises(ValueError):p.verified_script('https://example.com/script','f'*64)

    def test_health_urls_reject_invalid_ports_and_nonliteral_targets(self):
        for url in ('http://localhost/up','http://127.0.0.1:invalid/up','http://127.0.0.1:0/up','http://127.0.0.1:65536/up','http://127.0.0.1/space here','http://user:secret@127.0.0.1/up'):
            with self.assertRaises(ValueError):deploy.validate_health_url(url)
        self.assertEqual(deploy.validate_health_url('http://[::1]:8080/up').port,8080)

    def test_private_destinations_and_redirects_are_rejected(self):
        with patch('laravel_toolkit.common.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('laravel_toolkit.common.http.client.HTTPSConnection') as connection:
            with self.assertRaises(ValueError):p.fetch('https://example.com/script')
            connection.assert_not_called()
        connection=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
        connection.getresponse.return_value.status=302
        with patch('laravel_toolkit.common.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch('laravel_toolkit.common.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(ValueError):p.fetch('https://example.com/script')
            connection.close.assert_called_once()

    def test_platform_and_database_selection_are_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'os-release';path.write_text('ID=debian\nVERSION_ID="13"\n')
            with self.assertRaises(ValueError):provision.ubuntu(path)
            path.write_text('ID=ubuntu\nVERSION_ID="18.04"\n')
            with self.assertRaises(ValueError):provision.ubuntu(path)
            path.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            self.assertEqual(provision.ubuntu(path)['VERSION_ID'],'24.04')
        args=Namespace(database='postgresql',cache='redis',firewall=False,harden_ssh=False,tls_email=None)
        values=provision.packages(args,'8.3')
        self.assertIn('postgresql',values);self.assertNotIn('mariadb-server',values)

    def test_transaction_rollback_and_later_edit_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';state.mkdir(mode=0o700);file=root/'site.conf'
            manager=p.ManagedFiles(state)
            with self.assertRaises(ValueError):manager.apply({file:(b'first',0o644)},lambda:(_ for _ in ()).throw(ValueError('fixture invalid config')))
            self.assertFalse(file.exists())
            manager.apply({file:(b'first',0o644)},lambda:None)
            file.write_bytes(b'owner edit')
            with self.assertRaises(ValueError):manager.apply({file:(b'second',0o644)},lambda:None)
            self.assertEqual(file.read_bytes(),b'owner edit')

    def test_two_bash_entrypoints_help_without_host_mutation(self):
        for name in ('laravel-provision.sh','laravel-deploy.sh'):
            result=subprocess.run(['bash',str(ROOT/name),'--help'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('forge-api-token',result.stdout)


@unittest.skipIf(os.geteuid()==0,'Deployment must run as a non-root user; container integration drops privileges')
class DeploymentContracts(unittest.TestCase):
    def setUp(self):
        dependency_patch=patch("laravel_toolkit.prerequisites.ensure");dependency_patch.start();self.addCleanup(dependency_patch.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.site=self.root/'site';self.repo=self.root/'repo'
        for directory in ('releases','shared/storage/app/public','shared/storage/framework/views','shared/storage/logs'):
            (self.site/directory).mkdir(parents=True,exist_ok=True)
        env=self.site/'shared/.env';env.write_text('APP_ENV=production\nAPP_DEBUG=false\nAPP_KEY=base64:fixture-only\n');env.chmod(0o600)
        self.repo.mkdir();self.native=p.run
        self.native(['git','init','-b','main',str(self.repo)])
        self.native(['git','config','user.name','Fixture'],cwd=self.repo);self.native(['git','config','user.email','fixture@example.invalid'],cwd=self.repo)
        (self.repo/'bootstrap').mkdir();(self.repo/'public').mkdir();(self.repo/'database/migrations').mkdir(parents=True)
        for name,data in {'artisan':'fixture','bootstrap/app.php':'fixture','public/index.php':'fixture','composer.json':'{}','composer.lock':'{}','database/migrations/001.php':'<?php /* reviewed compatible fixture */'}.items():
            (self.repo/name).write_text(data)
        self.commit('first')
        self.fail=None;self.calls=[]
    @unittest.skipUnless(NATIVE_PHP,'Native PHP unavailable; never invoke a host Lerd wrapper')
    def test_configuration_probe_loads_autoloader_and_resolves_kernel(self):
        self.execute()
        argv=next(argv for argv,label in self.calls if label=='Production Laravel configuration')
        fixture=self.root/'php-probe';(fixture/'vendor').mkdir(parents=True);(fixture/'bootstrap').mkdir()
        (fixture/'vendor/autoload.php').write_text('<?php function config($key) { return ["app.env"=>"production","app.debug"=>false,"app.key"=>"fixture"][$key]; }')
        (fixture/'bootstrap/app.php').write_text('<?php return new class { function make($name) { if ($name !== "Illuminate\\\\Contracts\\\\Console\\\\Kernel") { throw new Exception("incorrect kernel"); } return new class { function bootstrap() {} }; } };')
        result=subprocess.run([NATIVE_PHP,*argv[1:]],cwd=fixture,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_compiled_configuration_is_private(self):
        original=self.command
        def command(argv,**kwargs):
            result=original(argv,**kwargs)
            if kwargs.get('label')=='Laravel config:cache':
                directory=Path(kwargs['cwd'])/'bootstrap/cache';directory.mkdir(exist_ok=True)
                (directory/'config.php').write_text('fixture secret')
            return result
        with contextlib.redirect_stdout(io.StringIO()):deploy.deploy(self.args(),command=command,health_check=lambda *a:None)
        self.assertEqual((self.site/'current/bootstrap/cache/config.php').stat().st_mode&0o777,0o600)

    def commit(self,value):
        (self.repo/'version.txt').write_text(value)
        self.native(['git','add','.'],cwd=self.repo);self.native(['git','commit','-qm','fixture '+value],cwd=self.repo)
    def args(self,**changes):
        values=dict(site_root=str(self.site),domain='example.test',repository=str(self.repo),allow_local_repository=True,
            branch='main',retain=2,health_url='http://127.0.0.1:18080/up',fpm_service=None,approve_service_changes=False,
            php_version=None,frontend='auto',queue='none',queue_service=None,rollback=False,recover=False,
            yes=True,check=False,dry_run=False,deploy_user=None,migrations='none',approve_migrations=False,
            backward_compatible=False,migration_manifest=None,build_script=None)
        return Namespace(**{**values,**changes})
    def command(self,argv,**kwargs):
        label=kwargs.get('label');self.calls.append((argv,label))
        if label==self.fail:raise ValueError('fixture failure')
        if argv[0]=='git':return self.native(argv,**kwargs)
        if label=='Laravel command discovery':return json.dumps({'commands':[{'name':name} for name in ('config:cache','route:cache','event:cache','view:cache','migrate')]})
        if label=='Production Composer install':
            (Path(kwargs['cwd'])/'vendor').mkdir();(Path(kwargs['cwd'])/'vendor/autoload.php').write_text('fixture')
        return ''
    def execute(self,**changes):
        with contextlib.redirect_stdout(io.StringIO()):return deploy.deploy(self.args(**changes),command=self.command,health_check=lambda *args:None)

    def test_initial_subsequent_and_explicit_rollback_preserve_shared_data(self):
        self.assertEqual(self.execute(),0);first=deploy.current(self.site)
        upload=self.site/'shared/storage/app/public/photo';upload.write_text('uploaded')
        before=(self.site/'shared/.env').read_bytes()
        self.commit('second');self.assertEqual(self.execute(),0);second=deploy.current(self.site)
        self.assertNotEqual(first,second)
        self.assertTrue((self.site/'current/.env').is_symlink());self.assertEqual(upload.read_text(),'uploaded')
        self.assertEqual(self.execute(rollback=True,repository=None),0);self.assertEqual(deploy.current(self.site),first)
        self.assertEqual((self.site/'shared/.env').read_bytes(),before)

    def test_pre_activation_git_composer_and_configuration_failures_preserve_live_release(self):
        self.execute();original=deploy.current(self.site);self.commit('second')
        for failure in ('Repository authentication','Production Composer install','Production Laravel configuration'):
            self.fail=failure
            with self.assertRaises(ValueError):self.execute()
            self.assertEqual(deploy.current(self.site),original)

    def test_node_build_failure_preserves_live_application(self):
        self.execute();original=deploy.current(self.site)
        (self.repo/'package.json').write_text('{"scripts":{"build":"fixture"}}');(self.repo/'package-lock.json').write_text('{}');self.commit('frontend')
        self.fail='Frontend build'
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(deploy.current(self.site),original)

    def test_failed_health_atomically_restores_previous_symlink(self):
        self.execute();original=deploy.current(self.site);self.commit('second')
        def check(*args):
            if deploy.current(self.site)!=original:raise ValueError('fixture unhealthy candidate')
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
            deploy.deploy(self.args(),command=self.command,health_check=check)
        self.assertEqual(deploy.current(self.site),original);self.assertFalse((self.site/'.automation-deploy.pending.json').exists())

    def test_lock_blocks_concurrent_deploy_before_checkout(self):
        with p.lock(self.site/'.automation-deploy.lock'),self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.calls,[])

    def test_migration_manifest_requires_exact_review_and_failure_preserves_current(self):
        self.execute();original=deploy.current(self.site);self.commit('migration')
        manifest=self.root/'migration.json';manifest.write_text(json.dumps({'schema':1,'backward_compatible':True,'files':{'001.php':p.digest((self.repo/'database/migrations/001.php').read_bytes())}}))
        self.fail='Reviewed isolated migrations'
        with self.assertRaises(ValueError):self.execute(migrations='compatible',approve_migrations=True,backward_compatible=True,migration_manifest=manifest)
        self.assertEqual(deploy.current(self.site),original)
        manifest.write_text('{"schema":1,"backward_compatible":true,"files":{}}');self.fail=None
        with self.assertRaises(ValueError):self.execute(migrations='compatible',approve_migrations=True,backward_compatible=True,migration_manifest=manifest)
        self.assertEqual(deploy.current(self.site),original)

    def test_escaping_links_and_modified_old_releases_are_preserved(self):
        self.execute();first=self.site/'releases'/deploy.current(self.site)
        (first/'owner-note').write_text('keep')
        for version in ('second','third','fourth'):
            self.commit(version);self.execute()
        self.assertEqual((first/'owner-note').read_text(),'keep')
        (self.repo/'public/escape').symlink_to('/etc/passwd');self.commit('escape')
        before=deploy.current(self.site)
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(deploy.current(self.site),before)

    def test_queue_signal_uses_actual_artisan_command_after_activation(self):
        with patch('laravel_toolkit.deploy.p.run',return_value='') as run:
            self.assertEqual(self.execute(queue='queue'),0)
        self.assertTrue(any(call.args[0][:3]==['php','artisan','queue:restart'] for call in run.call_args_list))

    def test_dryrun_does_not_create_lock_or_release(self):
        self.assertEqual(self.execute(dry_run=True),0)
        self.assertFalse((self.site/'.automation-deploy.lock').exists());self.assertEqual(list((self.site/'releases').iterdir()),[])
