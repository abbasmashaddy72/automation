"""Validation regressions: isolated distro probes, local inference, fault injection."""
from __future__ import annotations
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'lib'))
sys.path.insert(0,str(ROOT/'ai'))
import validate
import host_diagnostics
import automation
import providers
import ai_health
import journal


class DistroMatrix(unittest.TestCase):
    CASES=[('arch','arch','pacman'),('cachyos','arch','pacman'),
           ('ubuntu','debian','apt-get'),('debian','debian','apt-get'),
           ('linuxmint','debian','apt-get'),('fedora','fedora','dnf'),
           ('rocky','rhel','dnf'),('almalinux','rhel','dnf'),
           ('opensuse-tumbleweed','opensuse','zypper'),('opensuse-leap','opensuse','zypper'),
           ('alpine','alpine','apk')]

    def test_release_matrix_family_and_manager(self):
        for id_,family,manager in self.CASES:
            with self.subTest(distro=id_):
                self.assertEqual(automation.get_family({'ID':id_}),family)
                info={'id':id_,'family':family,'arch':'x86_64','version':'2026','wsl':False,'immutable':False}
                self.assertEqual(providers.capability(info)['manager'],manager)

    def test_no_host_installs_for_immutable_or_wsl(self):
        for variant in ('immutable','wsl'):
            info=dict(id='fedora',family='fedora',version='42',arch='x86_64',immutable=False,wsl=False)
            info[variant]=True
            self.assertFalse(providers.capability(info)['host_install_allowed'])

    def test_lerd_refused_on_container_alpine_and_inactive_systemd(self):
        base={'id':'ubuntu','family':'debian','arch':'x86_64','init':'systemd',
              'user_systemd':True,'container':False,'wsl':False}
        for modification in ({'container':True},{'family':'alpine'},{'user_systemd':False},
                             {'init':'other'},{'arch':'riscv64'}):
            with self.subTest(modification=modification):
                self.assertTrue(automation.lerd_compat({**base,**modification}))

    def test_unrecognized_distribution_cannot_install(self):
        self.assertFalse(providers.capability({'id':'custom','family':'unknown'})['host_install_allowed'])

    def test_container_probe_scripts_are_posix_safe(self):
        source=(ROOT/'scripts/container_probe.sh').read_text()
        self.assertIn('READ_ONLY=yes',source)
        self.assertNotIn('sudo ',source)
        self.assertNotIn('apk add',source)
        self.assertEqual(subprocess.run(['sh','-n',str(ROOT/'scripts/container_probe.sh')],capture_output=True).returncode,0)


class ValidatorSafety(unittest.TestCase):
    def test_default_scope_is_offline_not_host(self):
        with tempfile.TemporaryDirectory() as td, patch.object(validate,'container_checks') as containers, \
             patch.object(validate,'offline_checks',return_value={'fake':{'status':'pass'}}), \
             patch.object(host_diagnostics,'host_report') as host, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main(['--output',td]),0)
            containers.assert_not_called();host.assert_not_called()
            self.assertEqual(json.loads((Path(td)/'validation.json').read_text())['mode'],'offline')

    def test_skips_if_no_container_engine(self):
        with patch.object(validate,'engine_name',return_value=None):
            report=validate.container_checks(containers=['ubuntu','alpine'])
        self.assertEqual({v['status'] for v in report.values()},{'skip'})

    def test_sandboxed_container_invocation_without_pull(self):
        commands=[]
        def execute(cmd,**kwargs):
            commands.append(cmd)
            return {'status':'pass','exit_code':0,'details':'FAMILY=debian\nMANAGER_PRESENT=yes'}
        with patch.object(validate,'engine_name',return_value='podman'), patch.object(validate,'exec_check',side_effect=execute):
            report=validate.container_checks(containers=['ubuntu'],allow_pull=False)
        self.assertEqual(report['ubuntu']['status'],'pass')
        self.assertEqual(len(commands),2)
        self.assertIn('--network=none',commands[1])
        self.assertIn('--read-only',commands[1])
        self.assertIn('--cap-drop=ALL',commands[1])
        self.assertIn('--user=65534:65534',commands[1])
        self.assertIn('--pull=never',commands[1])
        self.assertFalse(any(c[1]=='pull' for c in commands))

    def test_does_not_pull_without_explicit_approval(self):
        with patch.object(validate,'engine_name',return_value='podman'), \
             patch.object(validate,'exec_check',return_value={'status':'fail','details':'not present'}) as runner:
            result=validate.container_checks(containers=['alpine'],allow_pull=False)
        self.assertEqual(result['alpine']['status'],'skip')
        self.assertEqual(runner.call_count,1)

    def test_invalid_or_duplicate_image_selection_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):validate.main(['--containers','ubuntu,ubuntu'])
            with self.assertRaises(SystemExit):validate.main(['--containers','../../evil'])

    def test_skip_is_not_pass_in_strict_gate(self):
        with tempfile.TemporaryDirectory() as td,patch.object(validate,'engine_name',return_value=None), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main(['--mode','containers','--containers','alpine',
                                           '--require-containers','--output',td]),1)

    def test_report_output_cannot_be_inside_source_or_symlink(self):
        with self.assertRaises(ValueError):validate.output_path(str(ROOT/'reports/ph4'))
        with tempfile.TemporaryDirectory() as td:
            symlink=Path(td)/'redirect';symlink.symlink_to(ROOT,target_is_directory=True)
            with self.assertRaises(ValueError):validate.output_path(str(symlink/'report'))

    def test_report_files_are_private(self):
        with tempfile.TemporaryDirectory() as td:
            validate.save_report(td,{'timestamp':'2026-10-31T00:00:00+00:00','offline':{'x':{'status':'pass'}}})
            for name in ('validation.json','validation.md'):
                self.assertEqual((Path(td)/name).stat().st_mode & 0o777,0o600)

    def test_strict_shell_tools_missing_is_failure(self):
        with patch.object(validate.shutil,'which',return_value=None), \
             patch.object(validate,'exec_check',return_value={'status':'pass','details':''}):
            result=validate.offline_checks(strict_tools=True)
        self.assertEqual(result['shellcheck']['status'],'fail')
        self.assertEqual(result['shfmt']['status'],'fail')

    def test_host_check_is_opt_in(self):
        with patch.object(host_diagnostics.automation,'platform_info',return_value={'id':'debian','family':'debian'}), \
             patch.object(host_diagnostics.shutil,'which',return_value=None):
            result=host_diagnostics.host_report()
        self.assertEqual(result['checks']['lerd_doctor']['status'],'skip')
        self.assertNotIn('ai_inference',result['checks'])

    def test_podman_non_rootless_is_failure(self):
        with patch.object(host_diagnostics.subprocess,'run',return_value=Mock(returncode=0,stdout='false\n',stderr='')):
            self.assertEqual(host_diagnostics.probe(['podman','info','--format','{{.Host.Security.Rootless}}'])['status'],'fail')

    def test_no_inference_without_opt_in(self):
        with patch.object(host_diagnostics.automation,'platform_info',return_value={'id':'debian'}), \
             patch.object(host_diagnostics.shutil,'which',return_value=None), \
             patch.object(ai_health,'smoke_inference') as inference:
            check=host_diagnostics.host_report(inference_backend='ollama',inference_model='qwen:3b')
        inference.assert_not_called()
        self.assertEqual(check['checks']['ai_inference']['status'],'skip')


class LocalAPIHandler(BaseHTTPRequestHandler):
    calls=[]
    mode='success'
    def log_message(self,*args):pass
    def do_POST(self):
        length=int(self.headers.get('Content-Length','0'))
        body=json.loads(self.rfile.read(length))
        self.__class__.calls.append((self.path,body))
        if self.__class__.mode=='redirect':
            self.send_response(302);self.send_header('Location','https://example.org/prompt');self.end_headers();return
        if self.__class__.mode=='bad_json':payload=b'not-json'
        elif self.__class__.mode=='empty':payload=b'{}'
        elif self.path=='/api/generate':payload=b'{"response":"OK","done":true}'
        elif self.path=='/completion':payload=b'{"content":"OK"}'
        elif self.path=='/v1/chat/completions':payload=b'{"choices":[{"message":{"content":"OK"}}]}'
        else:payload=b'{"error":"wrong route"}'
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)


class LocalAIInference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),LocalAPIHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=5)
    def setUp(self):LocalAPIHandler.calls=[];LocalAPIHandler.mode='success'

    def test_all_backends_real_local_generation_response(self):
        for backend,route in [('ollama','/api/generate'),('llamacpp','/completion'),('vllm','/v1/chat/completions')]:
            with self.subTest(backend=backend),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ai_health.smoke_inference(backend,'qwen2.5:3b',port=self.server.server_port),0)
                self.assertEqual(LocalAPIHandler.calls[-1][0],route)
                self.assertFalse(LocalAPIHandler.calls[-1][1].get('stream',True))

    def test_localhost_name_resolves_to_explicit_loopback_address(self):
        self.assertEqual(ai_health.endpoint('ollama','localhost',11434),
                         'http://127.0.0.1:11434/api/tags')

    def test_untrusted_redirect_is_not_followed(self):
        LocalAPIHandler.mode='redirect'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(ai_health.smoke_inference('ollama','small',port=self.server.server_port),0)

    def test_empty_and_invalid_generation_fail(self):
        for mode in ('empty','bad_json'):
            LocalAPIHandler.mode=mode
            with self.subTest(mode=mode),contextlib.redirect_stdout(io.StringIO()):
                self.assertNotEqual(ai_health.smoke_inference('ollama','small',port=self.server.server_port),0)

    def test_public_host_and_invalid_model_blocked(self):
        with self.assertRaises(ValueError):ai_health.smoke_inference('ollama','good','0.0.0.0',11434)
        with self.assertRaises(ValueError):ai_health.smoke_inference('ollama','some;evil','127.0.0.1',11434)
        with self.assertRaises(ValueError):ai_health.smoke_inference('ollama','good',timeout=999)

    def test_response_does_not_leak_prompt_or_generated_text_to_log(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ai_health.smoke_inference('llamacpp','test',port=self.server.server_port),0)
        self.assertNotIn('Reply with',out.getvalue())


class FaultInjection(unittest.TestCase):
    def test_failed_package_manager_never_adds_ownership(self):
        with tempfile.TemporaryDirectory() as td:
            info={'id':'debian','family':'debian','manager':'apt-get','version':'13','arch':'x86_64',
                  'desktop':False,'wsl':False,'container':False,'immutable':False}
            import argparse
            args=argparse.Namespace(select=['git'],exclude=None,interactive=False,
                 command='packages',action='install',dry_run=False,yes=True,non_interactive=True,
                 replace=[],allow_standalone_dev=False)
            with patch.object(automation,'installed',return_value=False), \
                 patch.object(automation,'available',return_value=True), \
                 patch.object(automation,'flatpak_available',return_value=False), \
                 patch.object(automation,'run',return_value=100),contextlib.redirect_stdout(io.StringIO()):
                result=automation.packages_action(args,info,{'AUTOMATION_STATE_DIR':str(Path(td)/'state')})
            self.assertNotEqual(result,0)
            self.assertFalse(journal.owned(directory=str(Path(td)/'state')))

    def test_api_unreachable_does_not_change_configuration(self):
        with patch.object(ai_health.urllib.request,'build_opener') as opener,contextlib.redirect_stdout(io.StringIO()):
            opener.return_value.open.side_effect=OSError('network error')
            self.assertNotEqual(ai_health.smoke_inference('llamacpp','foo',port=8094),0)

if __name__=='__main__':unittest.main()
