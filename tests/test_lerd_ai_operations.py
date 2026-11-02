"""Lerd and AI operations regression contracts; no host packages, services or model data altered."""
from __future__ import annotations
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'ai'))
import automation
import portable
import manager

HOST = {'family':'debian','id':'ubuntu','arch':'x86_64','desktop':True,'container':False,'wsl':False,
        'init':'systemd','user_systemd':True}

def args(**values):
    d = dict(backend='llamacpp',action='status',yes=False,dry_run=False,root=None,models=None,
             context=None,cpu_threads=None,cpu_quota=None,port=None,model=None,host='127.0.0.1',
             download=None,start=None,api_test=None,value=None,service_name=None,non_interactive=True)
    d.update(values)
    return SimpleNamespace(**d)

class LerdAILerdTests(unittest.TestCase):
    def test_doctor_runs_real_lerd_doctor(self):
        with patch.object(automation.shutil,'which',side_effect=lambda n: '/usr/bin/lerd' if n=='lerd' else None), \
             patch.object(automation,'run',return_value=0) as invoke, \
             patch.object(automation,'lerd_compat',return_value=[]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='doctor'),HOST),0)
            self.assertEqual(invoke.call_args.args[0],['/usr/bin/lerd','doctor'])

    def test_maintenance_requires_consent(self):
        with patch.object(automation.shutil,'which',return_value='/usr/bin/lerd'), \
             patch.object(automation,'run') as invoke, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='php:rebuild',value='8.5'),HOST),4)
            invoke.assert_not_called()

    def test_php_version_rejected_before_run(self):
        with patch.object(automation.shutil,'which',return_value='/usr/bin/lerd'), \
             patch.object(automation,'run') as invoke, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='php:rebuild',value=';rm -rf /',yes=True),HOST),2)
            invoke.assert_not_called()

    def test_service_status_includes_name(self):
        with patch.object(automation.shutil,'which',return_value='/usr/bin/lerd'), \
             patch.object(automation,'run',return_value=0) as invoke, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='service',value='status',service_name='mysql'),HOST),0)
            self.assertEqual(invoke.call_args.args[0],['/usr/bin/lerd','service','status','mysql'])

    def test_desktop_update_specific_verified_id(self):
        import lerd_ops
        with patch.object(automation.shutil,'which',side_effect=lambda n: '/usr/bin/flatpak' if n=='flatpak' else None), \
             patch.object(lerd_ops,'official_desktop_id',return_value='io.lerd.Desktop'), \
             patch.object(lerd_ops,'desktop_installed',return_value=True), \
             patch.object(automation,'run',return_value=0) as invoke, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='desktop-update',yes=True),HOST),0)
            self.assertEqual(invoke.call_args.args[0],['flatpak','update','--user','io.lerd.Desktop'])

    def test_flatpak_reference_rejects_malicious_identity(self):
        import lerd_ops
        with self.assertRaises(ValueError):
            lerd_ops.parse_flatpakref(b'[Flatpak Ref]\nName=org.example.App;rm -rf /\n')

class LerdAIAITests(unittest.TestCase):
    def test_local_endpoints_block_public_hosts(self):
        import ai_health
        with self.assertRaises(ValueError): ai_health.endpoint('ollama','0.0.0.0',11434)
        with self.assertRaises(ValueError): ai_health.endpoint('llamacpp','example.com',8080)
        self.assertEqual(ai_health.endpoint('ollama','127.0.0.1',11434),'http://127.0.0.1:11434/api/tags')

    def test_api_health_handles_connection_refused(self):
        import ai_health
        with patch.object(ai_health.urllib.request,'urlopen',side_effect=OSError('offline')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ai_health.check_api('llamacpp','127.0.0.1',8094),3)

    def test_llama_server_guard_rejects_missing_model(self):
        import ai_health
        with patch.object(portable,'command') as command, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.serve_llamacpp(args(action='serve',model='/not/a/model.gguf',yes=True)),3)
            command.assert_not_called()

    def test_llama_serve_context_and_threads(self):
        with tempfile.TemporaryDirectory() as td:
            model=Path(td)/'qwen.gguf'; model.write_bytes(b'model')
            with patch.object(portable.shutil,'which',return_value='/usr/bin/llama-server'), \
                 patch.object(portable,'command',return_value=0) as command, contextlib.redirect_stdout(io.StringIO()):
                value=args(action='serve',model=str(model),yes=True,context=32768,cpu_threads=3,port=8094)
                self.assertEqual(portable.serve_llamacpp(value),0)
                command_args=command.call_args.args[0]
                self.assertIn('--ctx-size',command_args)
                self.assertIn('32768',command_args)
                self.assertIn('--threads',command_args)
                self.assertIn('3',command_args)
                self.assertEqual(command_args[command_args.index('--host')+1],'127.0.0.1')

    def test_ollama_pull_requires_approval(self):
        with patch.object(portable,'command') as command, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.pull_ollama(args(backend='ollama',action='pull',model='qwen2.5-coder:3b')),4)
            command.assert_not_called()

    def test_invalid_ollama_model_rejected(self):
        with patch.object(portable,'command') as command, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.pull_ollama(args(backend='ollama',action='pull',model='foo;echo secret',yes=True)),2)
            command.assert_not_called()

    def test_hardware_json_is_read_only(self):
        import ai_health
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ai_health.print_hardware(as_json=True),0)
        self.assertIn('cpu_threads',output.getvalue())
        self.assertIn('memory_mib',output.getvalue())

    def test_arch_llamacpp_unsupported_action_must_not_invoke_legacy_script(self):
        with patch.object(manager,'BACKENDS',dict(manager.BACKENDS)), \
             patch.object(automation,'platform_info',return_value={**HOST,'family':'arch'}), \
             patch.object(manager.subprocess,'run') as invoke, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manager.main(['llamacpp','serve','--model','/tmp/x.gguf','--yes']),3)
            invoke.assert_not_called()


class LerdAIContextTests(unittest.TestCase):
    def test_ollama_context_uses_exact_running_models_route(self):
        import ai_health
        from unittest.mock import MagicMock
        response=MagicMock(status=200);response.__enter__.return_value=response
        response.read.return_value=b'{"models":[{"name":"fixture","context_length":128}]}'
        for host,authority in (('127.0.0.1','127.0.0.1'),('::1','[::1]')):
            with patch.object(ai_health.urllib.request,'build_opener') as build,contextlib.redirect_stdout(io.StringIO()):
                build.return_value.open.return_value=response
                self.assertEqual(ai_health.runtime_context('ollama',host,18080,128),0)
                request=build.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url,'http://'+authority+':18080/api/ps')

    def test_runtime_context_warns_when_underprovisioned(self):
        import ai_health
        import json
        from unittest.mock import MagicMock
        payload={'default_generation_settings': {'n_ctx':4096}}
        response=MagicMock()
        response.status=200
        response.read.return_value=json.dumps(payload).encode()
        response.__enter__.return_value=response
        with patch.object(ai_health.urllib.request,'build_opener') as build, contextlib.redirect_stdout(io.StringIO()) as out:
            build.return_value.open.return_value=response
            result=ai_health.runtime_context('llamacpp','127.0.0.1',8094,32768)
        self.assertEqual(result,5)
        self.assertIn('4096',out.getvalue())

    def test_arch_ollama_status_does_not_bootstrap(self):
        with patch.object(manager,'BACKENDS',dict(manager.BACKENDS)), \
             patch('automation.platform_info',return_value={**HOST,'family':'arch'}), \
             patch.object(portable,'main',return_value=0) as safe, \
             patch.object(manager.subprocess,'run') as invoke,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manager.main(['ollama','status']),0)
            safe.assert_called_once()
            invoke.assert_not_called()

class LerdAIOllamaServerTests(unittest.TestCase):
    def test_ollama_server_requires_consent(self):
        with patch.object(portable,'command') as call, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.serve_ollama(args(backend='ollama',action='serve')),4)
            call.assert_not_called()

    def test_ollama_server_is_loopback_only_and_respects_context(self):
        with patch.object(portable.shutil,'which',return_value='/bin/ollama'), \
             patch.object(portable,'command',return_value=0) as call, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.serve_ollama(args(backend='ollama',action='serve',yes=True,context=32768,port=11435)),0)
            self.assertEqual(call.call_args.kwargs['env']['OLLAMA_HOST'],'127.0.0.1:11435')
            self.assertEqual(call.call_args.kwargs['env']['OLLAMA_CONTEXT_LENGTH'],'32768')

    def test_ollama_duplicate_model_skips_pull(self):
        from unittest.mock import MagicMock
        listing=MagicMock(returncode=0,stdout='NAME ID SIZE MODIFIED\nqwen2.5-coder:3b abcd 2GB today\n')
        with patch.object(portable.shutil,'which',return_value='/bin/ollama'), \
             patch.object(portable.subprocess,'run',return_value=listing), \
             patch.object(portable,'command') as command,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.pull_ollama(args(backend='ollama',action='pull',yes=True,model='qwen2.5-coder:3b')),0)
            command.assert_not_called()

    def test_ollama_implicit_latest_tag_reuses_the_existing_model(self):
        from unittest.mock import MagicMock
        listing=MagicMock(returncode=0,stdout='NAME ID SIZE MODIFIED\nfixture:latest abcd 1MB today\nowner/fixture:latest efgh 1MB today\n')
        for model in ('fixture','owner/fixture'):
            with patch.object(portable.shutil,'which',return_value='/bin/ollama'),patch.object(portable.subprocess,'run',return_value=listing),patch.object(portable,'command',return_value=97) as pull,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.pull_ollama(args(backend='ollama',action='pull',yes=True,model=model)),0)
                pull.assert_not_called()

    def test_ollama_explicit_refresh_still_pulls_a_cached_model(self):
        with patch.object(portable.shutil,'which',return_value='/bin/ollama'),patch.object(portable,'command',return_value=0) as pull,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.pull_ollama(args(backend='ollama',action='pull',yes=True,model='fixture',refresh_model=True)),0)
            self.assertEqual(pull.call_args.args[0],['ollama','pull','fixture'])

class LerdAIInstallationSafetyTests(unittest.TestCase):
    def test_lerd_flatpak_ref_rejects_untrusted_redirect(self):
        import lerd_ops
        from unittest.mock import MagicMock
        response=MagicMock()
        response.url='https://untrusted.example/lerd.flatpakref'
        response.__enter__.return_value=response
        with patch.object(lerd_ops.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaises(ValueError):
                lerd_ops.official_desktop_id()

    def test_service_preset_must_be_opted_in(self):
        with patch.object(automation.shutil,'which',side_effect=lambda n: '/usr/bin/lerd' if n=='lerd' else None), \
             patch.object(automation,'run') as command, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(automation.lerd_action(args(action='service',value='preset',service_name='mariadb'),HOST),4)
            command.assert_not_called()

if __name__=='__main__':
    unittest.main()
