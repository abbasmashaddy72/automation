"""Smoke tests for safe portable AI and optional Lerd Desktop wiring."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ai'))
sys.path.insert(0,str(ROOT/'lib'))
import portable
import automation as cli

class PortableTests(unittest.TestCase):
    def args(self,**changes):
        data={'backend':'ollama','action':'install','yes':False,'dry_run':True,'root':None}
        data.update(changes)
        return SimpleNamespace(**data)

    def test_ollama_no_execution_without_yes(self):
        with patch.object(portable,'command') as command:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.install_ollama(self.args()),4)
            command.assert_not_called()

    def test_ollama_dry_run_does_not_fetch_installer(self):
        with patch.object(portable.shutil,'which',return_value=None),\
             patch.object(portable.urllib.request,'urlopen') as net:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.install_ollama(self.args(yes=True)),0)
            net.assert_not_called()

    def test_llamacpp_requires_toolchain(self):
        with patch.object(portable.shutil,'which',return_value=None):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.install_llamacpp(self.args(backend='llamacpp',yes=True)),3)

    def test_llamacpp_dry_run_avoids_repo_changes(self):
        with tempfile.TemporaryDirectory() as td, patch.object(portable,'ROOT',Path(td)):
            with patch.object(portable.shutil,'which',return_value='/usr/bin/tool'),\
                 patch.object(portable.subprocess,'run') as subprocess_run:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(portable.install_llamacpp(self.args(backend='llamacpp',yes=True)),0)
                subprocess_run.assert_not_called()
                self.assertFalse((Path(td)/'llamacpp').exists())

    def test_no_automated_ai_model_deletion(self):
        with patch.object(cli,'platform_info',return_value={'family':'debian','arch':'x86_64'}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(portable.main(self.args(action='uninstall',yes=True)),3)

    def test_lerd_desktop_without_flatpak_refuses(self):
        info={'family':'debian','desktop':True,'container':False,'arch':'x86_64','init':'other','user_systemd':False,'wsl':False}
        with patch.object(cli.shutil,'which',return_value=None),patch.object(cli,'run') as command:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.lerd_action(self.args(action='desktop-install'),info),3)
            command.assert_not_called()

    def test_lerd_desktop_dry_run_uses_official_ref(self):
        info={'family':'debian','desktop':True,'container':False,'arch':'x86_64','init':'systemd','user_systemd':True,'wsl':False}
        with patch.object(cli.shutil,'which',side_effect=lambda n: '/usr/bin/flatpak' if n=='flatpak' else None),\
             patch.object(cli,'run',return_value=0) as command:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.lerd_action(self.args(action='desktop-install',yes=True),info),0)
            self.assertIn('https://lerd.sh/lerd.flatpakref',command.call_args.args[0])

if __name__=='__main__': unittest.main()
