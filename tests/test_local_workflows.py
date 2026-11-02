"""Local integration contracts: owned AI units, runtime secrets, menus and retries."""
from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'lib'),str(ROOT/'ai'),str(ROOT/'scripts')]
import automation
import auth
import manager
import models
import services
import developer
import ai_health


class ManagedServices(unittest.TestCase):
    def setUp(self):
        from fixture_services import assume_systemctl
        assume_systemctl(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.root/'config'),'XDG_CACHE_HOME':str(self.root/'cache')});env.start();self.addCleanup(env.stop)
        self.exe=self.root/'llama-server';self.exe.write_text('#!/bin/sh\nexit 0\n');self.exe.chmod(0o700)
        self.model=self.root/'tiny.gguf';self.model.write_bytes(b'GGUFfixture')
        self.args=Namespace(backend='llamacpp',action='configure',executable=str(self.exe),model=str(self.model),port=18094,
            context=128,cpu_threads=2,cpu_quota='200%',key_file=None,dry_run=False,yes=True,enabled='yes')

    def configure(self):
        with patch.object(services,'control',return_value=0),contextlib.redirect_stdout(io.StringIO()):
            return services.main(self.args)

    def test_absent_systemctl_still_refuses_before_writes(self):
        with patch.object(services.shutil,'which',return_value=None),patch.object(services,'control') as control,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(services.main(self.args),3)
        control.assert_not_called();self.assertFalse((self.root/'config').exists())

    def test_configure_private_unit_and_configuration(self):
        self.assertEqual(self.configure(),0)
        config,unit=services.paths('llamacpp')
        self.assertEqual(config.stat().st_mode&0o777,0o600)
        self.assertEqual(unit.stat().st_mode&0o777,0o600)
        self.assertIn('CPUQuota=200%',unit.read_text());self.assertIn('--run',unit.read_text())
        self.assertTrue(services.owned('llamacpp'))

    def test_configuration_failure_restores_previous_files(self):
        self.configure();config,unit=services.paths('llamacpp');old=(config.read_bytes(),unit.read_bytes())
        self.args.context=256
        def control(*args):return 3 if args[0]=='daemon-reload' else 0 if args[0]=='show-environment' else 1
        with patch.object(services,'control',side_effect=control),self.assertRaises(ValueError):services.main(self.args)
        self.assertEqual(old,(config.read_bytes(),unit.read_bytes()))

    def test_missing_model_and_malformed_manifest_fail_before_writes(self):
        self.args.model=None
        with patch.object(services,'control',return_value=0),self.assertRaises(ValueError):services.main(self.args)
        self.assertFalse((self.root/'config').exists())
        value={'schema':1,'backend':'llamacpp','executable':False,'model':None,'port':18094,'context':128,'threads':2,'key_file':None,'cpu_quota':200}
        with self.assertRaises(ValueError):services.validate(value)

    def test_existing_unowned_unit_is_never_changed(self):
        config,unit=services.paths('llamacpp');unit.parent.mkdir(parents=True);unit.write_text('[Service]\nExecStart=/other\n')
        with patch.object(services,'control',return_value=0),self.assertRaises((ValueError,FileNotFoundError)):services.main(self.args)
        self.assertIn('/other',unit.read_text());self.assertFalse(config.exists())

    def test_configure_refusal_and_dry_run_write_nothing(self):
        self.args.yes=False
        with patch.object(services,'control',return_value=0),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(services.main(self.args),4)
            self.args.dry_run=True;self.assertEqual(services.main(self.args),0)
        self.assertFalse((self.root/'config').exists())

    def test_active_service_is_not_reconfigured_implicitly(self):
        self.configure();config,_=services.paths('llamacpp');before=config.read_bytes()
        self.args.context=512
        with patch.object(services,'control',return_value=0),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(services.main(self.args),3)
        self.assertEqual(config.read_bytes(),before)

    def test_owned_lifecycle_and_autostart_only_target_owned_unit(self):
        self.configure()
        def control(*args):return 1 if args[0]=='is-active' else 0
        with patch.object(services,'control',side_effect=control) as call,patch.object(services,'port_available',return_value=True),contextlib.redirect_stdout(io.StringIO()):
            for action in ('stop','autostart'):
                self.args.action=action;self.assertEqual(services.main(self.args),0)
            self.args.action='restart';self.assertEqual(services.main(self.args),3) # not ready/active cannot report success
            self.assertTrue(any(x.args==('restart','automation-ai-llamacpp.service') for x in call.call_args_list))
            self.assertFalse(any('llamacpp-local.service' in str(x) for x in call.call_args_list))

    def test_occupied_port_does_not_start_process(self):
        self.configure();self.args.action='start'
        def control(*args):return 1 if args[0]=='is-active' else 0
        with patch.object(services,'control',side_effect=control) as call,patch.object(services,'port_available',return_value=False),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(services.main(self.args),3)
            self.assertFalse(any(x.args[0]=='start' for x in call.call_args_list))

    def test_revoked_key_allows_stop_but_blocks_restart(self):
        key=self.root/'auth/api-key';auth.save(key,'sk-local-'+'q'*40);self.args.key_file=key
        self.configure();key.unlink()
        with patch.object(services,'control',return_value=0) as control,contextlib.redirect_stdout(io.StringIO()):
            self.args.action='stop';self.assertEqual(services.main(self.args),0)
            self.args.action='restart'
            with self.assertRaises(OSError):services.main(self.args)
            self.assertFalse(any(x.args[0]=='restart' for x in control.call_args_list))

    def test_uninstall_preserves_models_keys_and_configuration(self):
        self.configure();config,unit=services.paths('llamacpp')
        self.model.unlink() # Stop/uninstall must remain usable after a model is removed.
        self.args.action='uninstall'
        with patch.object(services,'control',return_value=0),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(services.main(self.args),0)
        self.assertFalse(unit.exists());self.assertTrue(config.exists());self.assertTrue(self.exe.exists())

    def test_symlink_unit_parent_rejected(self):
        target=self.root/'elsewhere';target.mkdir();folder=self.root/'config/systemd';folder.mkdir(parents=True)
        (folder/'user').symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):services.paths('llamacpp')

    def test_vllm_runtime_uses_private_environment_not_argv(self):
        self.args.backend='vllm';self.args.executable=str(self.root/'vllm')
        exe=Path(self.args.executable)
        exe.write_text('#!/usr/bin/env python3\nimport os,json,sys\nprint(json.dumps({"auth":bool(os.getenv("VLLM_API_KEY")),"argv_contains_key":any("sk-local-" in x for x in sys.argv),"offline":os.getenv("HF_HUB_OFFLINE")}))\n');exe.chmod(0o700)
        model=self.root/'model';model.mkdir();(model/'config.json').write_text('{}');self.args.model=str(model)
        key=self.root/'private/api-key';auth.save(key,'sk-local-'+'x'*40);self.args.key_file=key
        self.assertEqual(self.configure(),0)
        cp=subprocess.run([sys.executable,str(ROOT/'ai/services.py'),'--run','vllm',str(self.root/'config')],capture_output=True,text=True,timeout=10)
        self.assertEqual(cp.returncode,0,cp.stderr)
        result=json.loads(cp.stdout);self.assertTrue(result['auth']);self.assertFalse(result['argv_contains_key']);self.assertEqual(result['offline'],'1')
        self.assertNotIn(auth.read(key),cp.stdout+cp.stderr)

    def test_systemd_argument_escaping(self):
        self.assertEqual(services.quote('/path/with %n $HOME "x"'), '"/path/with %%n $$HOME \\"x\\""')
        with self.assertRaises(ValueError):services.quote('bad\nargument')


class LocalUserFlows(unittest.TestCase):
    def test_text_wizard_can_choose_profile_even_with_configured_defaults(self):
        entries=[{'id':'curl','category':'Essential System Utilities','default':True},
                 {'id':'firefox','category':'Desktop','default':True}]
        settings={'AUTOMATION_PROFILE':'default','AUTOMATION_LERD':'false'}
        with patch('sys.stdin.isatty',return_value=True),patch.object(automation.shutil,'which',return_value=None), \
             patch.object(automation,'installed',return_value=False),patch('builtins.input',side_effect=['3','done']),contextlib.redirect_stdout(io.StringIO()):
            profile,selected=automation.select_interactive(entries,{'family':'debian'},settings,prompt_profile=True)
        self.assertEqual(profile,'minimal');self.assertEqual(selected,['curl'])
        self.assertEqual(settings['AUTOMATION_PROFILE'],'default')

    def test_jan_openai_api_contract_is_loopback_authenticated(self):
        with tempfile.TemporaryDirectory() as td:
            key=Path(td)/'private/api-key';auth.save(key,'sk-local-'+'j'*40);expected=auth.read(key)
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.headers.get('Authorization')!='Bearer '+expected:
                        self.send_response(401);self.end_headers();return
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"tiny-fixture"}]}')
                def do_POST(self):
                    self.rfile.read(int(self.headers.get('Content-Length','0')))
                    if self.headers.get('Authorization')!='Bearer '+expected:
                        self.send_response(401);self.end_headers();return
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"choices":[{"message":{"content":"OK"}}]}')
                def log_message(self,*args):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(ai_health.check_api('jan',port=server.server_port,key_file=key),0)
                    self.assertEqual(ai_health.model_inventory('jan',port=server.server_port,key_file=key),0)
                    self.assertEqual(auth.test_endpoint('jan',key,port=server.server_port),0)
                    self.assertEqual(ai_health.smoke_inference('jan','tiny-fixture',port=server.server_port,key_file=key),0)
                    self.assertEqual(ai_health.check_api('jan',port=server.server_port),3)
            finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_api_menu_cancel_and_confirm_refusal(self):
        args=Namespace(yes=False,dry_run=False)
        with patch('sys.stdin.isatty',return_value=True),patch('builtins.input',return_value=''),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(auth.menu(args),0)
        with patch('sys.stdin.isatty',return_value=True),patch('builtins.input',side_effect=['1','n']),patch.object(auth,'main') as change,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.menu(args),4);change.assert_not_called()

    def test_new_api_keys_cannot_be_written_into_source_tree(self):
        with self.assertRaises(ValueError):auth.save(ROOT/'must-not-create-private-key','sk-local-'+'p'*40)
        self.assertFalse((ROOT/'must-not-create-private-key').exists())

    def test_api_menu_dispatches_existing_actions(self):
        args=Namespace(yes=False,dry_run=False)
        with patch('sys.stdin.isatty',return_value=True),patch('builtins.input',side_effect=['5','yes']),patch.object(auth,'main',return_value=0) as change,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.menu(args),0);self.assertEqual(change.call_args.args[0].action,'key-rotate');self.assertTrue(change.call_args.args[0].yes)

    def test_lock_retry_is_bounded_and_general_errors_are_not_retried(self):
        args=Namespace(dry_run=False)
        with patch.object(automation.subprocess,'run',side_effect=[Mock(returncode=1,stdout='',stderr='Could not get lock /var/lib/dpkg/lock'),Mock(returncode=0,stdout='ok',stderr='')]) as run, \
             patch.object(automation.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.run(['apt-get','install','git'],mutate=True,args=args,retries=2),0);self.assertEqual(run.call_count,2)
        with patch.object(automation.subprocess,'run',return_value=Mock(returncode=1,stdout='',stderr='Package not found')) as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.run(['apt-get','install','git'],mutate=True,args=args,retries=2),1);self.assertEqual(run.call_count,1)

    def test_model_search_is_readonly_validated_and_bounded(self):
        response=Mock(status=200);response.read.return_value=b'[{"id":"publisher/model"},{"id":"bad;value"}]'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch.object(models.urllib.request,'build_opener',return_value=Mock(open=Mock(return_value=response))) as opener:
            result=models.search('tiny model',limit=2);self.assertEqual([x['model'] for x in result],['publisher/model'])
            self.assertIn('ProxyHandler',str(type(opener.call_args.args[0])))
            response.read.assert_called_once_with(262145)
        with self.assertRaises(ValueError):models.search('$(touch /tmp/bad)')

    def test_vllm_running_context_uses_actual_model_card(self):
        response=Mock(status=200);response.read.return_value=b'{"data":[{"id":"fixture","max_model_len":256}]}'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch.object(ai_health.urllib.request,'build_opener',return_value=Mock(open=Mock(return_value=response))),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ai_health.runtime_context('vllm',desired=256),0)
            self.assertEqual(ai_health.runtime_context('vllm',desired=512),5)

    def test_service_preflight_does_not_request_compiler(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'scripts').mkdir();(root/'ai').mkdir()
            (root/'setup.sh').write_bytes((ROOT/'setup.sh').read_bytes())
            (root/'scripts/prerequisites.sh').write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$PREFLIGHT_LOG"\n')
            (root/'ai/manager.py').write_text('pass\n')
            cp=subprocess.run(['bash',str(root/'setup.sh'),'ai','llamacpp','start','--yes'],env={**os.environ,'PREFLIGHT_LOG':str(root/'calls')},capture_output=True,text=True,timeout=10)
            self.assertEqual(cp.returncode,0,cp.stderr);self.assertNotIn('--with-ai-build',(root/'calls').read_text())

    def test_invalid_ai_flags_cannot_trigger_build_prerequisites(self):
        with patch.object(manager.subprocess,'run') as run,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            manager.main(['llamacpp','install','--yes','--unknown-unsafe-option'])
        run.assert_not_called()

    def test_native_query_locale_is_predictable_without_changing_parent_env(self):
        import providers,discovery,sources
        for module,function,args in [(providers,providers._run,(['rpm','-q','git'],)),
            (discovery,discovery._execute,(['apt-cache','search','git'],)),(sources,sources._execute,(['paru','-Si','git'],))]:
            with self.subTest(module=module.__name__),patch.dict(os.environ,{'LC_ALL':'de_DE.UTF-8'}),patch.object(module.shutil,'which',return_value='/tool'),patch.object(module.subprocess,'run',return_value=Mock(returncode=0,stdout='')) as run:
                function(*args);self.assertEqual(run.call_args.kwargs['env']['LC_ALL'],'C');self.assertEqual(os.environ['LC_ALL'],'de_DE.UTF-8')

    def test_immutable_variants_and_suse_atomic_derivatives_are_planning_only(self):
        import providers
        for data in ({'ID':'fedora','VARIANT_ID':'coreos'},{'ID':'aeon','ID_LIKE':'opensuse'},{'ID':'opensuse-kalpa','ID_LIKE':'suse'}):
            info=automation.platform_info(data)
            self.assertTrue(info['immutable']);self.assertFalse(providers.capability(info)['host_install_allowed'])

    def test_bash_bootstrap_refuses_missing_python_installation_under_wsl(self):
        import re
        with tempfile.TemporaryDirectory() as td:
            script=Path(td)/'prerequisites.sh'
            content=(ROOT/'scripts/prerequisites.sh').read_text()
            content=re.sub(r'python_ok\(\) \{.*?\n\}', 'python_ok() {\n    return 1\n}',content,count=1,flags=re.S)
            # Repository tools can create state even with cache-only queries.
            content=re.sub(r'package_available\(\) \{.*?\n\}', 'package_available() {\n    mkdir -p -- "$XDG_STATE_HOME"\n    return 0\n}',content,count=1,flags=re.S)
            # Even a regression in the guard cannot invoke a real installer.
            content=content.replace('"${PRIV[@]}" "${cmd[@]}" "${missing[@]}"', 'printf "forbidden-install\\n" >&2; exit 99')
            script.write_text(content)
            cp=subprocess.run(['bash',str(script),'install','--runtime-only','--without-ui','--yes'],
                env={**os.environ,'WSL_DISTRO_NAME':'fixture-wsl','XDG_STATE_HOME':str(Path(td)/'state')},capture_output=True,text=True,timeout=20)
            self.assertEqual(cp.returncode,3,cp.stdout+cp.stderr)
            self.assertIn('Read-only planning target',cp.stdout)
            self.assertFalse((Path(td)/'state').exists())

    def test_llamacpp_does_not_build_an_unrelated_checkout(self):
        import portable
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'llamacpp/src/.git').mkdir(parents=True)
            args=Namespace(action='repair',yes=True,dry_run=False)
            with patch.object(portable,'ROOT',root),patch.object(portable.shutil,'which',return_value='/tool'),patch.object(portable.subprocess,'run',return_value=Mock(returncode=0,stdout='https://example.test/unrelated.git\n')),patch.object(portable,'command') as build,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.install_llamacpp(args),3);build.assert_not_called()

    def test_cpu_build_is_headless_and_respects_requested_parallelism(self):
        import portable
        with tempfile.TemporaryDirectory() as td,patch.object(portable,'ROOT',Path(td)),patch.object(portable.shutil,'which',return_value='/tool'),patch.object(portable,'command',return_value=0) as build,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.install_llamacpp(Namespace(action='install',yes=True,dry_run=True,cpu_threads=2)),0)
            configured=next(x.args[0] for x in build.call_args_list if x.args[0][0]=='cmake' and '-S' in x.args[0])
            self.assertEqual(configured[configured.index('-G')+1],'Unix Makefiles')
            for flag in ('-DLLAMA_OPENSSL=OFF','-DLLAMA_BUILD_UI=OFF','-DLLAMA_USE_PREBUILT_UI=OFF','-DLLAMA_SUBPROCESS=OFF'):
                self.assertIn(flag,configured)
            compiled=build.call_args_list[-1].args[0]
            self.assertEqual(compiled[-2:],['-j','2']);self.assertIn('llama-server',compiled)

    def test_cpu_build_requires_make_instead_of_failing_mid_configuration(self):
        import portable
        with patch.object(portable.shutil,'which',side_effect=lambda name:None if name=='make' else '/tool'),patch.object(portable,'command') as build,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.install_llamacpp(Namespace(action='install',yes=True,dry_run=False)),3)
            build.assert_not_called()

    def test_container_snapshot_never_mounts_local_credentials_or_model_artifacts(self):
        import container_workflows
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'source';root.mkdir()
            for name in ('.env','.env.production','private.key','private.pem','model.gguf','model.safetensors','old.zip','module.py'):
                (root/name).write_text('fixture')
            outside=Path(td)/'private-data';outside.write_text('fixture-private-data')
            (root/'outside-link').symlink_to(outside)
            observed={}
            def probe(name,**kwargs):
                source=kwargs['source'];observed['files']={p.name for p in source.iterdir()}
                return {'status':'pass'}
            with patch.object(container_workflows,'ROOT',root),patch.object(container_workflows,'probe',side_effect=probe), \
                 patch.object(container_workflows.shutil,'which',return_value='/podman'),patch.object(container_workflows.subprocess,'run',return_value=Mock(returncode=0,stdout='true\n')),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(container_workflows.main(['--allow-install','--containers','debian','--output',str(Path(td)/'output')]),0)
            self.assertEqual(observed['files'],{'module.py'})

    def test_ollama_cli_cannot_inherit_a_remote_host_or_proxy(self):
        import portable
        with patch.dict(os.environ,{'OLLAMA_HOST':'https://remote.example','HTTPS_PROXY':'http://proxy.example'}):
            env=portable.ollama_env('localhost',11435)
            self.assertEqual(env['OLLAMA_HOST'],'127.0.0.1:11435');self.assertNotIn('HTTPS_PROXY',env)
            self.assertEqual(os.environ['OLLAMA_HOST'],'https://remote.example')
            self.assertEqual(portable.ollama_env('::1',11435)['OLLAMA_HOST'],'[::1]:11435')
            with self.assertRaises(ValueError):portable.ollama_env('remote.example',11435)


class DeveloperFlows(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'HOME':str(self.root),'XDG_CONFIG_HOME':str(self.root/'.config'),'XDG_STATE_HOME':str(self.root/'state')})
        env.start();self.addCleanup(env.stop)
        self.args=Namespace(action='shell',shell='bash',name='Fixture User',email='fixture@example.test',value=None,dry_run=False,yes=True)

    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()):return developer.main(self.args,lambda *_:True)

    def test_shell_merge_idempotency_and_restore_preserve_original_bytes(self):
        path=self.root/'.bashrc';original=b'# user-owned\nexport EXISTING=value\n';path.write_bytes(original)
        self.assertEqual(self.apply(),0);after=path.read_bytes();self.assertTrue(after.startswith(original))
        self.assertEqual(self.apply(),0);self.assertEqual(path.read_bytes(),after)
        folder=self.root/'state/automation-toolkit/developer';self.assertEqual(len(list(folder.iterdir())),1)
        self.args.action='restore';self.args.value=next(folder.iterdir()).name
        self.assertEqual(self.apply(),0);self.assertEqual(path.read_bytes(),original)

    def test_restore_refuses_later_user_edit(self):
        self.apply();path=self.root/'.bashrc';path.write_text('user later edit')
        self.args.action='restore';self.args.value=next((self.root/'state/automation-toolkit/developer').iterdir()).name
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(path.read_text(),'user later edit')

    def test_git_identity_uses_git_parser_preserves_other_settings(self):
        self.args.action='git'
        path=self.root/'.gitconfig';path.write_text('[core]\n\teditor = vi\n')
        self.assertEqual(self.apply(),0)
        for key,wanted in [('core.editor','vi'),('user.name','Fixture User'),('user.email','fixture@example.test')]:
            cp=subprocess.run(['git','config','--file',str(path),'--get',key],capture_output=True,text=True,timeout=10)
            self.assertEqual(cp.stdout.strip(),wanted)
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_git_invalid_identity_and_shell_blocks_preserve_user_data(self):
        self.args.action='git';self.args.email='bad email'
        path=self.root/'.gitconfig';path.write_text('# original')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(path.read_text(),'# original')
        with self.assertRaises(ValueError):developer.shell_content((developer.BEGIN+'\n').encode(),'bash')

    def test_dryrun_and_refusal_create_no_files(self):
        self.args.dry_run=True;self.assertEqual(self.apply(),0);self.assertEqual(list(self.root.iterdir()),[])
        self.args.dry_run=False
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(developer.main(self.args,lambda *_:False),4)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_shell_templates_parse_and_never_execute_on_read(self):
        for shell in ('bash','zsh','fish'):
            content=developer.shell_content(b'# existing\n',shell)
            self.assertEqual(developer.shell_content(content,shell),content)
            if shell=='bash':
                cp=subprocess.run(['bash','-n'],input=content,capture_output=True,timeout=5)
                self.assertEqual(cp.returncode,0,cp.stderr)

    def test_sourcing_shell_block_twice_preserves_aliases_and_deduplicates_path(self):
        path=self.root/'fixture.sh';path.write_bytes(developer.shell_content(b'', 'bash'))
        script='alias artisan="printf existing"; source "$1"; first="$PATH"; source "$1"; [[ "$PATH" == "$first" ]] || exit 1; [[ "$(alias artisan)" == *existing* ]] || exit 2'
        result=subprocess.run(['bash','--noprofile','--norc','-c',script,'fixture',str(path)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_symlink_targets_are_never_modified(self):
        outside=self.root/'outside';outside.write_text('keep')
        (self.root/'.bashrc').symlink_to(outside)
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(outside.read_text(),'keep')


if __name__=='__main__':unittest.main()
