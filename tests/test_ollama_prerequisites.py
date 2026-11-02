"""Ollama's official compressed installer needs its own native prerequisites."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ai'))
import manager
import portable

class OllamaPrerequisites(unittest.TestCase):
    def test_missing_installer_runtime_gets_ollama_not_compiler_prerequisites(self):
        with patch.object(manager.shutil,'which',return_value=None),patch.object(manager.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run,patch.object(portable,'main',return_value=0):
            self.assertEqual(manager.main(['ollama','install','--dry-run']),0)
        run.assert_called_once()
        arguments=run.call_args.args[0]
        self.assertIn('--with-ollama',arguments);self.assertNotIn('--with-ai-build',arguments)
        self.assertEqual(arguments[2],'check');self.assertIn('--dry-run',arguments)
    def test_existing_install_does_not_install_unused_tools(self):
        with patch.object(manager.shutil,'which',return_value='/fixture/ollama'),patch.object(manager.subprocess,'run') as run,patch.object(portable,'main',return_value=0):
            self.assertEqual(manager.main(['ollama','install','--dry-run']),0)
        run.assert_not_called()
    def test_status_does_not_bootstrap_installer(self):
        with patch.object(manager.subprocess,'run') as run,patch.object(portable,'main',return_value=0):
            self.assertEqual(manager.main(['ollama','status']),0)
        run.assert_not_called()
    def test_bash_profile_includes_zstd_and_remains_readonly(self):
        result=subprocess.run(['bash',str(ROOT/'scripts/prerequisites.sh'),'check','--runtime-only','--with-ollama','--without-ui','--dry-run'],capture_output=True,text=True,timeout=35)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('zstd',result.stdout)
