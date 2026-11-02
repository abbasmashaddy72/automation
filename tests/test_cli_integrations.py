"""Unified entrypoint, native sources and CPU settings; no legacy installers."""
from argparse import Namespace
import contextlib
import http.server
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'lib'),str(BASE/'ai')]
import ai_health
import services


class PropsServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/props':self.send_response(404);self.end_headers();return
        body=b'{"default_generation_settings":{"n_ctx":32768}}'
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass


class UnifiedCLIIntegration(unittest.TestCase):
    def test_all_maintained_shell_scripts_parse(self):
        files=set(BASE.rglob('*.sh'))
        for name in ('setup.sh','scripts/prerequisites.sh','scripts/container_probe.sh'):
            self.assertIn(BASE/name,files)
        for file in files:
            result=subprocess.run(['bash','-n',str(file)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,f'{file}: {result.stderr}')

    def test_removed_installers_have_no_dispatch_path(self):
        self.assertFalse((BASE/'modules/legacy').exists())
        for name in ('setup.sh','lib/automation.py','ai/manager.py'):
            self.assertNotIn('modules/legacy',(BASE/name).read_text())

    def test_unified_check_does_not_configure_services(self):
        with tempfile.TemporaryDirectory() as temp:
            env={**os.environ,'HOME':temp,'XDG_CONFIG_HOME':temp+'/config','XDG_STATE_HOME':temp+'/state'}
            result=subprocess.run(['bash',str(BASE/'setup.sh'),'ai','llamacpp','--check','--dry-run',
                '--non-interactive'],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((Path(temp)/'config').exists());self.assertFalse((Path(temp)/'state').exists())

    def test_bad_cpu_quota_is_rejected_before_prerequisites_or_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            env={**os.environ,'HOME':temp,'XDG_CONFIG_HOME':temp+'/config'}
            result=subprocess.run(['bash',str(BASE/'setup.sh'),'ai','llamacpp','configure','--cpu-quota=0%','--yes'],
                env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('quota',result.stderr);self.assertFalse((Path(temp)/'config').exists())

    def test_real_loopback_context_matches_and_reports_underprovisioning(self):
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),PropsServer)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ai_health.runtime_context('llamacpp','127.0.0.1',server.server_port,32768),0)
            self.assertEqual(ai_health.runtime_context('llamacpp','127.0.0.1',server.server_port,65536),5)

    def test_shelly_pacman_first_aur_fallback(self):
        # The old bootstrap installed an AUR helper implicitly. The unified
        # replacement must report source options without installing one.
        import sys
        from unittest.mock import patch, Mock
        sys.path.insert(0,str(BASE/'lib'))
        import sources
        info={'family':'arch','id':'arch','arch':'x86_64'}
        with patch.object(sources.shutil,'which',return_value=None),patch.object(sources.subprocess,'run') as run:
            self.assertEqual(sources.search_exact('shelly',info),[])
            run.assert_not_called()
        candidates=sources.search_exact('shelly',info,
            which=lambda name:'/usr/bin/paru' if name=='paru' else None,
            runner=lambda cmd:Mock(returncode=0,stdout='Repository : aur\nName : shelly\n'))
        self.assertEqual([x['source'] for x in candidates],['paru'])
        self.assertNotIn('--noconfirm',sources.helper_install_cmd('paru','shelly'))


class OwnedCPUConfiguration(unittest.TestCase):
    def test_reconfigure_retains_context_and_targets_only_owned_units(self):
        for backend in ('llamacpp','vllm'):
            with self.subTest(backend=backend),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);exe=root/backend;exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o700)
                model=root/('model.gguf' if backend=='llamacpp' else 'model')
                if backend=='llamacpp':model.write_bytes(b'GGUFfixture')
                else:model.mkdir();(model/'config.json').write_text('{}')
                args=Namespace(backend=backend,action='configure',executable=str(exe),model=str(model),
                    context=32768,cpu_threads=3,cpu_quota='300%',port=18095,key_file=None,yes=True,dry_run=False)
                with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'config')}),\
                        patch('services.control',side_effect=lambda *argv:1 if argv[0]=='is-active' else 0) as control,\
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(services.configure(args),0)
                    args.context=None;args.cpu_threads=2;args.cpu_quota='200%'
                    self.assertEqual(services.configure(args),0)
                    value=services.read(backend)
                    self.assertEqual((value['context'],value['threads'],value['cpu_quota']),(32768,2,200))
                    config,unit=services.paths(backend)
                    self.assertEqual(unit.read_text().count('CPUQuota='),1)
                    self.assertFalse(any(call.args[0] in ('start','restart') for call in control.call_args_list))
                    self.assertFalse((unit.parent/'llamacpp-local.service').exists())

    def test_foreign_unit_refused_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_CONFIG_HOME':temp}):
            config,unit=services.paths('llamacpp');unit.parent.mkdir(parents=True)
            unit.write_text('[Service]\nExecStart=/unrelated\n');before=unit.read_bytes()
            args=Namespace(backend='llamacpp')
            with self.assertRaises((ValueError,OSError)):services.configure(args)
            self.assertEqual(unit.read_bytes(),before);self.assertFalse(config.exists())
