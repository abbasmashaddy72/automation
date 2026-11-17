"""Smoke tests for safe portable AI and optional Lerd Desktop wiring."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))
sys.path.insert(0, str(ROOT / "lib"))
import automation as cli


class PortableTests(unittest.TestCase):
    def args(self, **changes):
        data = {
            "backend": "ollama",
            "action": "install",
            "yes": False,
            "dry_run": True,
            "root": None,
        }
        data.update(changes)
        return SimpleNamespace(**data)

    def test_lerd_desktop_without_flatpak_refuses(self):
        info = {
            "family": "debian",
            "desktop": True,
            "container": False,
            "arch": "x86_64",
            "init": "other",
            "user_systemd": False,
            "wsl": False,
        }
        with (
            patch.object(cli.shutil, "which", return_value=None),
            patch.object(cli, "run") as command,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.lerd_action(self.args(action="desktop-install"), info), 3
                )
            command.assert_not_called()

    def test_lerd_desktop_dry_run_uses_official_ref(self):
        info = {
            "family": "debian",
            "desktop": True,
            "container": False,
            "arch": "x86_64",
            "init": "systemd",
            "user_systemd": True,
            "wsl": False,
        }
        with (
            patch.object(
                cli.shutil,
                "which",
                side_effect=lambda n: "/usr/bin/flatpak" if n == "flatpak" else None,
            ),
            patch.object(cli, "run", return_value=0) as command,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.lerd_action(
                        self.args(action="desktop-install", yes=True), info
                    ),
                    0,
                )
            self.assertIn("https://lerd.sh/lerd.flatpakref", command.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
