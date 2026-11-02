"""Audit regression cases; all mutations isolated in temporary directories."""
from __future__ import annotations
from argparse import Namespace
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
for folder in ('lib','ai','scripts'): sys.path.insert(0,str(ROOT/folder))
import automation
import auth
import cache
import configuration
import desktop
import manager
import models
import patch_manager
import full_update
import validate


def sha(value): return hashlib.sha256(value).hexdigest()


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); (self.root/'config').mkdir()
        (self.root/'config/defaults.env').write_text('AUTOMATION_LERD=true\nAUTOMATION_PROFILE=minimal\n')

    def ensure(self): return configuration.ensure(self.root,automation.config_file,automation.validate_settings)

    def test_create_private_defaults_and_idempotent_merge(self):
        path=self.ensure(); self.assertEqual(path.stat().st_mode & 0o777,0o600)
        data=path.read_bytes(); self.ensure(); self.assertEqual(data,path.read_bytes())

    def test_existing_configuration_bytes_preserved(self):
        path=self.root/'.env'; path.write_text('# custom\nAUTOMATION_LERD=false')
        self.ensure()
        self.assertTrue(path.read_text().startswith('# custom\nAUTOMATION_LERD=false\n'))
        self.assertEqual(automation.config_file(path)['AUTOMATION_LERD'],'false')
        self.assertEqual(automation.config_file(path)['AUTOMATION_PROFILE'],'minimal')

    def test_invalid_existing_config_unchanged(self):
        path=self.root/'.env'; data='AUTOMATION_LERD=$(touch /tmp/forbidden)\n'; path.write_text(data)
        with self.assertRaises(ValueError): self.ensure()
        self.assertEqual(path.read_text(),data)

    def test_symlink_and_hardlink_config_rejected(self):
        path=self.root/'.env'; outside=self.root/'outside'; outside.write_text('AUTOMATION_LERD=false\n')
        path.symlink_to(outside)
        with self.assertRaises(ValueError): self.ensure()
        path.unlink(); os.link(outside,path)
        with self.assertRaises(ValueError): self.ensure()


class ReadOnlyTests(unittest.TestCase):
    def test_shfmt_parser_failure_is_not_hidden_by_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name,code in [('shellcheck',0),('shfmt',1)]:
                path=root/name; path.write_text('#!/bin/sh\nexit '+str(code)+'\n'); path.chmod(0o755)
            result=subprocess.run(['bash',str(ROOT/'scripts/check-scripts.sh'),'--check'],
                env={**os.environ,'PATH':str(root)+':'+os.environ['PATH']},capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,1)
            self.assertIn('shfmt could not parse',result.stderr)
    def test_profile_reads_never_create_state(self):
        import workflows
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'state'
            self.assertEqual(workflows.list_profiles(str(root)),[])
            self.assertFalse(root.exists())
            with self.assertRaises(ValueError): workflows.saved_profile('missing',str(root),automation.validate_settings)
            self.assertFalse(root.exists())

    def test_native_install_revalidates_and_blocks_changed_repository(self):
        info=dict(family='debian',manager='apt-get',desktop=False,id='debian',version='13',wsl=False,container=True,immutable=False,arch='x86_64')
        args=Namespace(select=['git'],exclude=None,interactive=False,command='packages',action='install',dry_run=False,yes=True,non_interactive=True,replace=[],allow_standalone_dev=False)
        with patch.object(automation,'installed',return_value=False),patch.object(automation,'available',return_value=True), \
             patch.object(automation,'native_exact_available',return_value=False),patch.object(automation,'flatpak_available',return_value=False), \
             patch.object(automation,'run') as run,contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(automation.packages_action(args,info,{}),5)
            run.assert_not_called()

    def test_query_commands_disable_metadata_refresh(self):
        import providers,discovery
        for family in ('fedora','rhel'):
            self.assertIn('--cacheonly',providers.exact_query(family,'git'))
            self.assertIn('--cacheonly',discovery.search_command(family,'git'))
        self.assertIn('--no-refresh',providers.exact_query('opensuse','git'))
        self.assertIn('--no-refresh',discovery.search_command('opensuse','git'))

    def test_tumbleweed_python_is_explicit_release_mapping(self):
        import providers
        self.assertEqual(providers.candidates('python3',{'family':'opensuse','id':'opensuse-tumbleweed'})[0],'python313')
        self.assertEqual(providers.candidates('python3',{'family':'opensuse','id':'opensuse-leap','version':'15.6'})[0],'python3')

    def test_installed_rpm_curl_minimal_is_preserved_by_observed_ownership(self):
        with patch.object(automation.shutil,'which',return_value='/usr/bin/curl'),patch.object(automation,'_query',return_value=Mock(returncode=0,stdout='curl-minimal\n')) as query:
            self.assertTrue(automation.installed('curl','rhel'))
            self.assertIn('--whatprovides',query.call_args.args[0])
        with patch.object(automation.shutil,'which',return_value='/usr/bin/curl'),patch.object(automation,'_query',side_effect=[Mock(returncode=0,stdout='unrelated\n'),Mock(returncode=1,stdout='')]):
            self.assertFalse(automation.installed('curl','rhel'))

    def test_existing_explicit_replacement_is_not_reinstalled(self):
        info=dict(family='fedora',manager='dnf',desktop=False,id='fedora',version='42',wsl=False,container=True,immutable=False,arch='x86_64')
        args=Namespace(select=['wget'],exclude=None,interactive=False,command='packages',action='install',dry_run=False,yes=True,non_interactive=True,replace=['wget=wget2-wget'],allow_standalone_dev=False)
        with patch.object(automation,'installed',side_effect=lambda name,family:name=='wget2-wget'),patch.object(automation,'native_exact_available',return_value=True), \
             patch.object(automation,'flatpak_available',return_value=False),patch.object(automation,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.packages_action(args,info,{}),0)
            run.assert_not_called()

    def test_duplicate_and_unbalanced_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config'
            for data in ('AUTOMATION_LERD=true\nAUTOMATION_LERD=false\n','AUTOMATION_LERD="true\n'):
                path.write_text(data)
                with self.assertRaises(ValueError): automation.config_file(path)

    def test_dryrun_exports_do_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'new'
            for args in (['profiles','export',str(target)],['dashboard','export',str(target)],['config','init']):
                with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()), patch.object(automation.configuration,'ensure') as create:
                    self.assertEqual(automation.main([*args,'--yes','--dry-run']),0)
                    create.assert_not_called(); self.assertFalse(target.exists())

    def test_check_overrides_mutating_subcommand_and_cache_refresh(self):
        info={'family':'debian','arch':'x86_64','init':'other','user_systemd':False,'container':True,'wsl':False}
        with patch.object(automation,'platform_info',return_value=info), patch.object(automation,'conflicts',return_value={}), \
             patch.object(automation.cache,'clear') as clear, patch.object(automation,'lerd_action') as action, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.main(['lerd','install','--yes','--check','--refresh-cache']),0)
            clear.assert_not_called(); action.assert_not_called()

    def test_model_smoke_dryrun_sends_no_request(self):
        with patch('ai_health.smoke_inference') as inference,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manager.main(['llamacpp','smoke','--model','tiny','--dry-run']),0)
            inference.assert_not_called()

    def test_multiple_ai_action_flags_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            manager.main(['llamacpp','--check','--repair','--yes'])

    def test_repository_cache_not_persisted_by_readonly_queries(self):
        with patch.object(cache,'directory') as directory:
            self.assertFalse(cache.put(['query'],True))
            directory.assert_not_called()

    def test_setup_readonly_preflight_never_installs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'scripts').mkdir(); (root/'lib').mkdir()
            (root/'setup.sh').write_bytes((ROOT/'setup.sh').read_bytes())
            (root/'scripts/prerequisites.sh').write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$PREFLIGHT_LOG"\n')
            (root/'lib/automation.py').write_text('pass\n')
            env={**os.environ,'PREFLIGHT_LOG':str(root/'calls')}
            for flags in (['--check'],['--help'],['--dry-run']):
                cp=subprocess.run(['bash',str(root/'setup.sh'),'--auto-prereqs','--install',*flags],env=env,capture_output=True,timeout=10)
                self.assertEqual(cp.returncode,0,cp.stderr)
            self.assertEqual((root/'calls').read_text().splitlines(),['check','check','check'])

    def test_direct_install_preflights_without_auto_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'scripts').mkdir(); (root/'lib').mkdir()
            (root/'setup.sh').write_bytes((ROOT/'setup.sh').read_bytes())
            (root/'scripts/prerequisites.sh').write_text('#!/bin/bash\nprintf "%s\\n" "$1" > "$PREFLIGHT_LOG"\n')
            (root/'lib/automation.py').write_text('pass\n')
            cp=subprocess.run(['bash',str(root/'setup.sh'),'packages','install','--yes'],env={**os.environ,'PREFLIGHT_LOG':str(root/'calls')},capture_output=True,timeout=10)
            self.assertEqual(cp.returncode,0,cp.stderr)
            self.assertEqual((root/'calls').read_text(),'install\n')

    def test_mutating_entrypoint_creates_private_lock_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            env={**os.environ,'XDG_STATE_HOME':str(root/'state'),'AUTOMATION_STATE_DIR':str(root/'state/automation-toolkit')}
            cp=subprocess.run([sys.executable,str(ROOT/'lib/automation.py'),'packages','install','--select','git','--exclude','git','--yes','--no-lerd','--no-auto-search'],
                              env=env,capture_output=True,text=True,timeout=30)
            # Empty selection exercises locking without any possible installation.
            self.assertEqual(cp.returncode,0,cp.stderr)
            folder=root/'state/automation-toolkit'
            self.assertEqual(folder.stat().st_mode&0o777,0o700)
            self.assertEqual((folder/'setup.lock').stat().st_mode&0o777,0o600)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.path=self.root/'private/key'
        self.key='sk-local-'+'a'*48

    def test_private_key_roundtrip_and_preservation(self):
        self.assertTrue(auth.save(self.path,self.key))
        self.assertEqual(auth.read(self.path),self.key)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777,0o700)
        self.assertFalse(auth.save(self.path,'b'*48)); self.assertEqual(auth.read(self.path),self.key)
        auth.save(self.path,'c'*48,replace=True); self.assertEqual(auth.read(self.path),'c'*48)

    def test_public_keys_and_symlink_parents_refused(self):
        auth.save(self.path,self.key); self.path.chmod(0o644)
        with self.assertRaises(ValueError): auth.read(self.path)
        (self.root/'link').symlink_to(self.path.parent,target_is_directory=True)
        with self.assertRaises(ValueError): auth.save(self.root/'link/other',self.key)

    def test_copy_passes_key_through_stdin_only(self):
        with patch.dict(os.environ,{'WAYLAND_DISPLAY':'test'}), patch.object(auth.shutil,'which',return_value='/bin/wl-copy'), \
             patch.object(auth.subprocess,'run',return_value=Mock(returncode=0)) as command,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(auth.copy_key(self.key),0)
            self.assertEqual(command.call_args.kwargs['input'],self.key)
            self.assertNotIn(self.key,str(command.call_args.args)); self.assertNotIn(self.key,output.getvalue())

    def test_key_dryrun_does_not_create_files(self):
        args=Namespace(backend='llamacpp',action='key-generate',key_file=self.path,dry_run=True,yes=True)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(auth.main(args),0)
        self.assertFalse(self.path.exists())

    def test_key_lifecycle_redaction_consent_and_revoke(self):
        args=Namespace(backend='llamacpp',action='key-generate',key_file=self.path,dry_run=False,yes=False)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(auth.main(args),4); self.assertFalse(self.path.exists())
            args.yes=True; self.assertEqual(auth.main(args),0); first=auth.read(self.path)
            self.assertEqual(auth.main(args),0); self.assertEqual(first,auth.read(self.path))
            args.action='key-status'; self.assertEqual(auth.main(args),0)
            args.action='key-rotate'; self.assertEqual(auth.main(args),0); second=auth.read(self.path)
            self.assertNotEqual(first,second)
            args.action='key-revoke'; self.assertEqual(auth.main(args),0); self.assertFalse(self.path.exists())
        self.assertNotIn(first,output.getvalue()); self.assertNotIn(second,output.getvalue())
        self.assertIn('Running endpoints retain loaded keys',output.getvalue())

    def test_authentication_requests_validate_valid_invalid_and_absent(self):
        auth.save(self.path,self.key); expected=self.key
        class Handler(BaseHTTPRequestHandler):
            enforced=True
            def do_GET(self):
                if self.enforced and self.headers.get('Authorization') != 'Bearer '+expected:
                    self.send_response(401); self.end_headers(); return
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"data":[]}')
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.test_endpoint('llamacpp',self.path,port=server.server_port),0)
            Handler.enforced=False
            self.assertEqual(auth.test_endpoint('llamacpp',self.path,port=server.server_port),5)

    def test_auth_rejects_remote_and_invalid_ports(self):
        auth.save(self.path,self.key)
        for kwargs in ({'host':'example.com'},{'port':-1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError): auth.test_endpoint('llamacpp',self.path,**kwargs)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'models'; self.data=b'GGUFtiny-fixture'
        self.url='https://example.com/tiny.gguf'

    def download(self,**kwargs):
        options={'yes':True}; options.update(kwargs)
        return models.download(self.root,'tiny.gguf',self.url,sha(self.data),len(self.data),**options)

    def opener(self,payload=None):
        response=Mock(); response.status=200
        stream=io.BytesIO(self.data if payload is None else payload)
        response.read=stream.read; response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
        return Mock(open=Mock(return_value=response))

    def test_download_verify_cache_reuse_and_scoped_remove(self):
        with patch.object(models.urllib.request,'build_opener',return_value=self.opener()) as opener, \
             patch.object(models.ai_health,'hardware',return_value={'available_memory_mib':1024}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.download(),0); self.assertEqual(self.download(),0)
            self.assertEqual(opener.call_count,1)
            other=self.root/'other.gguf'; other.write_bytes(b'user-data')
            self.assertEqual(models.remove(self.root,'tiny.gguf',dry_run=True),0)
            self.assertEqual(models.remove(self.root,'tiny.gguf',yes=False),4)
            self.assertEqual(models.remove(self.root,'tiny.gguf',yes=True),0)
            self.assertEqual(other.read_bytes(),b'user-data')

    def test_corrupted_or_oversized_download_not_activated(self):
        for payload in (b'bad',self.data+b'extra',b'GGUFwrong-data!!'):
            with self.subTest(payload=payload),patch.object(models.urllib.request,'build_opener',return_value=self.opener(payload)), \
                 patch.object(models.ai_health,'hardware',return_value={'memory_mib':1024}),self.assertRaises(ValueError): self.download()
            self.assertFalse((self.root/'tiny.gguf').exists())
            if self.root.exists(): self.assertFalse(list(self.root.glob('.download-*')))

    def test_resources_and_mutated_models_are_protected(self):
        with patch.object(models.ai_health,'hardware',return_value={'available_memory_mib':1}),self.assertRaises(ValueError): self.download()
        self.root.mkdir(exist_ok=True); (self.root/'tiny.gguf').write_bytes(self.data)
        with self.assertRaises(ValueError): models.remove(self.root,'tiny.gguf',yes=True)
        self.assertTrue((self.root/'tiny.gguf').exists())

    def test_model_paths_and_urls_reject_unsafe_inputs(self):
        with self.assertRaises(ValueError): models.checked_root('/tmp/..')
        for name in ('../x.gguf','a/b.gguf','x;echo.gguf'):
            with self.subTest(name=name),self.assertRaises(ValueError): models.filename(name)
        for url in ('http://example.com/x','https://user:pass@example.com/x','file:///tmp/x'):
            with self.subTest(url=url),self.assertRaises(ValueError): models.https_url(url)

    def test_insufficient_disk_and_network_failure_leave_no_model(self):
        with patch.object(models.shutil,'disk_usage',return_value=Mock(free=0)),self.assertRaises(ValueError): self.download()
        with patch.object(models.ai_health,'hardware',return_value={'available_memory_mib':1024}), \
             patch.object(models.urllib.request,'build_opener',return_value=Mock(open=Mock(side_effect=OSError('offline')))),self.assertRaises(OSError): self.download()
        self.assertFalse((self.root/'tiny.gguf').exists())
        self.assertFalse(list(self.root.glob('.download-*')))

    def test_model_dryrun_creates_no_directory(self):
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(self.download(dry_run=True),0)
        self.assertFalse(self.root.exists())


class DesktopTests(unittest.TestCase):
    def test_session_detection_and_headless_gate(self):
        for value,wanted in [('KDE','kde'),('ubuntu:GNOME','gnome'),('XFCE','xfce'),('X-Cinnamon','cinnamon'),('MATE','mate')]:
            with self.subTest(value=value),patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':value},clear=True):
                self.assertEqual(desktop.detect()['desktop'],wanted)
                self.assertIsNone(desktop.detect()['favorites_adapter'])

    def test_kde_updates_actual_task_manager_only(self):
        text='[Containments][1][Applets][2]\nplugin=other\n[Containments][1][Applets][2][Configuration][General]\nlaunchers=preserve\n[Containments][1][Applets][3]\nplugin=org.kde.plasma.icontasks\n[Containments][1][Applets][3][Configuration][General]\nlaunchers=old\n'
        new=desktop.kde_update(text,['firefox.desktop'])
        self.assertIn('launchers=preserve\n',new)
        self.assertIn('launchers=old,applications:firefox.desktop\n',new)
        self.assertEqual(desktop.kde_update(new,['firefox.desktop']),new)

    def test_ambiguous_kde_panels_refused(self):
        text='[a]\nplugin=org.kde.plasma.icontasks\n[b]\nplugin=org.kde.plasma.taskmanager\n'
        with self.assertRaises(ValueError): desktop.kde_update(text,['firefox.desktop'])

    def test_gnome_backup_apply_restore_and_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            values={'current':['old.desktop']}
            def write(adapter,value): values['current']=value
            args=Namespace(action='apply',value=None,select=['firefox.desktop'],dry_run=False,yes=True)
            with patch.object(desktop,'detect',return_value={'favorites_adapter':'gnome'}),patch.object(desktop.shutil,'which',return_value='gsettings'), \
                 patch.object(desktop,'applications',return_value=['firefox.desktop']),patch.object(desktop,'snapshot',side_effect=lambda _:values['current']), \
                 patch.object(desktop,'write',side_effect=write),patch.object(desktop,'backup_root',return_value=Path(td)),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(desktop.main(args,lambda *_:True),0)
                backup=next(Path(td).glob('*.json')); self.assertEqual(backup.stat().st_mode&0o777,0o600)
                args.action='restore'; args.value=backup.name
                values['current']=['user-change.desktop']
                with self.assertRaises(ValueError): desktop.main(args,lambda *_:True)
                values['current']=['old.desktop','firefox.desktop']
                self.assertEqual(desktop.main(args,lambda *_:True),0)
                self.assertEqual(values['current'],['old.desktop'])


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.root=self.base/'repo'; self.root.mkdir()
        patched=patch.object(patch_manager,'ROOT',self.root); patched.start(); self.addCleanup(patched.stop)
        env=patch.dict(os.environ,{'AUTOMATION_PATCH_BACKUP_DIR':str(self.base/'backups')}); env.start(); self.addCleanup(env.stop)

    def archive(self,ops,payload):
        path=self.base/'patch.zip'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('manifest.json',json.dumps({'format':1,'operations':ops}))
            for name,data in payload.items(): archive.writestr('payload/'+name,data)
        return path

    def test_reject_noncanonical_archive_paths(self):
        for value in ('a//b','a/./b','a/','./a','.','a\nb'):
            with self.subTest(value=value),self.assertRaises(ValueError): patch_manager.valid_name(value)

    def test_local_check_unsigned_has_no_lock_or_backup_mutation(self):
        path=self.archive([{'action':'add','path':'a','sha256':sha(b'a')}],{'a':b'a'})
        before=set(self.base.iterdir())
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(patch_manager.main(['--check',str(path)]),0)
        self.assertEqual(set(self.base.iterdir()),before)

    def test_new_executable_mode_and_rollback(self):
        path=self.archive([{'action':'add','path':'run.sh','sha256':sha(b'#!/bin/sh\n'),'mode':0o755}],{'run.sh':b'#!/bin/sh\n'})
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(patch_manager.main(['--apply',str(path)]),0)
        self.assertEqual((self.root/'run.sh').stat().st_mode&0o777,0o755)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(patch_manager.main(['--rollback']),0)
        self.assertFalse((self.root/'run.sh').exists())

    def test_interrupted_receipt_recovery_and_user_edit_conflict(self):
        (self.root/'a').write_bytes(b'new')
        folder=self.base/'backups/interrupted'; (folder/'originals').mkdir(parents=True)
        (folder/'originals/a').write_bytes(b'old')
        patch_manager.write_state(folder,{'originals':{'a':sha(b'old')},'expected':{'a':sha(b'new')}})
        (self.root/'a').write_bytes(b'user-edit')
        with self.assertRaises(ValueError): patch_manager.recover(folder)
        self.assertEqual((self.root/'a').read_bytes(),b'user-edit')
        (self.root/'a').write_bytes(b'new')
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(patch_manager.main(['--recover',str(folder)]),0)
        self.assertEqual((self.root/'a').read_bytes(),b'old')

    def test_failed_syntax_restores_original_files(self):
        (self.root/'a.py').write_bytes(b'original=1\n')
        bad=b'def broken(\n'
        path=self.archive([{'action':'modify','path':'a.py','old_sha256':sha(b'original=1\n'),'sha256':sha(bad)}],{'a.py':bad})
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SyntaxError): patch_manager.main(['--apply',str(path)])
        self.assertEqual((self.root/'a.py').read_bytes(),b'original=1\n')

    def test_full_update_and_rollback_without_signing(self):
        (self.root/'a').write_bytes(b'old'); (self.root/'.env').write_text('private-user-config')
        path=self.base/'full.zip'
        manifest={'format':2,'files':[{'path':'a','sha256':sha(b'new'),'old_sha256':sha(b'old'),'mode':0o644}], 'deletions':[]}
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest)); archive.writestr('a',b'new')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(full_update.main(['--check',str(path),'--root',str(self.root)]),0)
            self.assertEqual(full_update.main(['--apply',str(path),'--root',str(self.root)]),0)
            self.assertEqual(full_update.main(['--apply',str(path),'--root',str(self.root)]),0)
            self.assertEqual(patch_manager.main(['--rollback']),0)
        self.assertEqual((self.root/'a').read_bytes(),b'old')
        self.assertEqual((self.root/'.env').read_text(),'private-user-config')

    def test_validation_normalizes_outside_relative_path(self):
        with patch.object(validate,'ROOT',self.root):
            self.assertEqual(validate.output_path(str(self.root/'../report')),self.base/'report')

    def test_full_update_bad_checksum_and_traversal_rejected(self):
        for name in ('a','../outside'):
            path=self.base/'bad-full.zip'
            manifest={'format':2,'files':[{'path':name,'sha256':'0'*64,'mode':0o644}], 'deletions':[]}
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('manifest.json',json.dumps(manifest)); archive.writestr(name,b'data')
            with self.subTest(name=name),self.assertRaises(ValueError): full_update.main(['--apply',str(path),'--root',str(self.root)])
            self.assertFalse((self.root/'a').exists()); self.assertFalse((self.base/'outside').exists())


if __name__=='__main__': unittest.main()
