"""Actual backend sandboxes remain explicitly authorized and isolated."""
from pathlib import Path
import sys
import unittest
import json
import tempfile
import subprocess
import contextlib
import io
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import ai_sandbox

class BackendSandboxAuthorization(unittest.TestCase):
    def test_ollama_requires_both_download_and_execution_consent(self):
        for options in ({},{'yes':True},{'allow_download':True}):
            with patch.object(ai_sandbox,'run') as run:
                with self.assertRaises(ValueError):ai_sandbox.ollama_sandbox(**options)
                run.assert_not_called()
    def test_ollama_missing_runtime_is_a_skip_not_a_pass(self):
        with patch.object(ai_sandbox.shutil,'which',return_value=None):
            report=ai_sandbox.ollama_sandbox(yes=True,allow_download=True)
        self.assertEqual(report,{'status':'skip','reason':'podman_unavailable'})
    def test_gguf_shards_are_not_dispatched_to_other_backend(self):
        with self.assertRaises(SystemExit) as result:
            ai_sandbox.main(['--backend','ollama','--with-gguf-shards','--output','/not-created'])
        self.assertEqual(result.exception.code,2)

    def test_runtime_timeout_is_recorded_without_secret_argv_or_false_teardown(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(ai_sandbox,'ollama_sandbox',side_effect=subprocess.TimeoutExpired('private-command-token',30)),contextlib.redirect_stdout(io.StringIO()):
            result=ai_sandbox.main(['--backend','ollama','--yes','--allow-download','--output',temp])
            path=Path(temp)/'ai-sandbox.json';text=path.read_text();report=json.loads(text)
            self.assertEqual(result,1);self.assertEqual(report['status'],'fail')
            self.assertEqual(report['error_type'],'TimeoutExpired');self.assertFalse(report['teardown_verified'])
            self.assertNotIn('private-command-token',text);self.assertEqual(path.stat().st_mode&0o777,0o600)
