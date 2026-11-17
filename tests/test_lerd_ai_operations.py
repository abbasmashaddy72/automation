"""Lerd and AI operations regression contracts; no host packages, services or model data altered."""

from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "ai"))
import automation
import manager

HOST = {
    "family": "debian",
    "id": "ubuntu",
    "arch": "x86_64",
    "desktop": True,
    "container": False,
    "wsl": False,
    "init": "systemd",
    "user_systemd": True,
}


def args(**values):
    d = dict(
        backend="llamacpp",
        action="status",
        yes=False,
        dry_run=False,
        root=None,
        models=None,
        context=None,
        cpu_threads=None,
        cpu_quota=None,
        port=None,
        model=None,
        host="127.0.0.1",
        download=None,
        start=None,
        api_test=None,
        value=None,
        service_name=None,
        non_interactive=True,
    )
    d.update(values)
    return SimpleNamespace(**d)


class LerdAILerdTests(unittest.TestCase):
    def test_dashboard_lerd_actions_require_confirmation_and_preview_is_read_only(self):
        import setup_dashboard

        for operation in ("install", "repair"):
            payload = {"action": f"lerd-{operation}"}
            self.assertEqual(
                setup_dashboard.preview_arguments(payload, aur_ready=False),
                ["lerd", operation, "--dry-run"],
            )
            with self.assertRaises(ValueError):
                setup_dashboard.preview_arguments(
                    payload, aur_ready=False, execute=True
                )
            self.assertEqual(
                setup_dashboard.preview_arguments(
                    {**payload, "confirmed": True}, aur_ready=False, execute=True
                ),
                ["lerd", operation, "--yes"],
            )

    def test_availability_and_missing_install_preview_do_not_run_the_installer(self):
        with (
            tempfile.TemporaryDirectory() as home,
            patch.object(automation.Path, "home", return_value=Path(home)),
            patch.object(automation.shutil, "which", return_value=None),
            patch.object(automation.os, "geteuid", return_value=1000),
            patch.object(automation.urllib.request, "urlopen") as fetch,
            patch.object(automation, "run") as run,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    automation.lerd_action(args(action="availability"), HOST), 0
                )
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "installed": False,
                    "compatible": True,
                    "blockers": [],
                },
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    automation.lerd_action(args(action="install", dry_run=True), HOST),
                    0,
                )
            fetch.assert_not_called()
            run.assert_not_called()

    def test_doctor_runs_real_lerd_doctor(self):
        with (
            patch.object(
                automation.shutil,
                "which",
                side_effect=lambda n: "/usr/bin/lerd" if n == "lerd" else None,
            ),
            patch.object(automation, "run", return_value=0) as invoke,
            patch.object(automation, "lerd_compat", return_value=[]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(automation.lerd_action(args(action="doctor"), HOST), 0)
            self.assertEqual(invoke.call_args.args[0], ["/usr/bin/lerd", "doctor"])

    def test_maintenance_requires_consent(self):
        with (
            patch.object(automation.shutil, "which", return_value="/usr/bin/lerd"),
            patch.object(automation, "run") as invoke,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.lerd_action(args(action="php:rebuild", value="8.5"), HOST), 4
            )
            invoke.assert_not_called()

    def test_php_version_rejected_before_run(self):
        with (
            patch.object(automation.shutil, "which", return_value="/usr/bin/lerd"),
            patch.object(automation, "run") as invoke,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.lerd_action(
                    args(action="php:rebuild", value=";rm -rf /", yes=True), HOST
                ),
                2,
            )
            invoke.assert_not_called()

    def test_service_status_includes_name(self):
        with (
            patch.object(automation.shutil, "which", return_value="/usr/bin/lerd"),
            patch.object(automation, "run", return_value=0) as invoke,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.lerd_action(
                    args(action="service", value="status", service_name="mysql"), HOST
                ),
                0,
            )
            self.assertEqual(
                invoke.call_args.args[0],
                ["/usr/bin/lerd", "service", "status", "mysql"],
            )

    def test_desktop_update_specific_verified_id(self):
        import lerd_ops

        with (
            patch.object(
                automation.shutil,
                "which",
                side_effect=lambda n: "/usr/bin/flatpak" if n == "flatpak" else None,
            ),
            patch.object(
                lerd_ops, "official_desktop_id", return_value="io.lerd.Desktop"
            ),
            patch.object(lerd_ops, "desktop_installed", return_value=True),
            patch.object(automation, "run", return_value=0) as invoke,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.lerd_action(args(action="desktop-update", yes=True), HOST), 0
            )
            self.assertEqual(
                invoke.call_args.args[0],
                ["flatpak", "update", "--user", "io.lerd.Desktop"],
            )

    def test_flatpak_reference_rejects_malicious_identity(self):
        import lerd_ops

        with self.assertRaises(ValueError):
            lerd_ops.parse_flatpakref(b"[Flatpak Ref]\nName=org.example.App;rm -rf /\n")


class LerdAIAITests(unittest.TestCase):
    def test_local_endpoints_block_public_hosts(self):
        import ai_health

        with self.assertRaises(ValueError):
            ai_health.endpoint("ollama", "0.0.0.0", 11434)
        with self.assertRaises(ValueError):
            ai_health.endpoint("llamacpp", "example.com", 8080)
        self.assertEqual(
            ai_health.endpoint("ollama", "127.0.0.1", 11434),
            "http://127.0.0.1:11434/api/tags",
        )

    def test_api_health_handles_connection_refused(self):
        import ai_health

        with (
            patch.object(
                ai_health.urllib.request, "urlopen", side_effect=OSError("offline")
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(ai_health.check_api("llamacpp", "127.0.0.1", 8094), 3)

    def test_hardware_json_is_read_only(self):
        import ai_health

        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ai_health.print_hardware(as_json=True), 0)
        self.assertIn("cpu_threads", output.getvalue())
        self.assertIn("memory_mib", output.getvalue())


class LerdAIContextTests(unittest.TestCase):
    def test_runtime_context_warns_when_underprovisioned(self):
        import ai_health
        import json
        from unittest.mock import MagicMock

        payload = {"default_generation_settings": {"n_ctx": 4096}}
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response
        with (
            patch.object(ai_health.urllib.request, "build_opener") as build,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            build.return_value.open.return_value = response
            result = ai_health.runtime_context("llamacpp", "127.0.0.1", 8094, 32768)
        self.assertEqual(result, 5)
        self.assertIn("4096", out.getvalue())


class LerdAIInstallationSafetyTests(unittest.TestCase):
    def test_lerd_flatpak_ref_rejects_untrusted_redirect(self):
        import lerd_ops
        from unittest.mock import MagicMock

        response = MagicMock()
        response.url = "https://untrusted.example/lerd.flatpakref"
        response.__enter__.return_value = response
        with patch.object(lerd_ops.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(ValueError):
                lerd_ops.official_desktop_id()

    def test_service_preset_must_be_opted_in(self):
        with (
            patch.object(
                automation.shutil,
                "which",
                side_effect=lambda n: "/usr/bin/lerd" if n == "lerd" else None,
            ),
            patch.object(automation, "run") as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.lerd_action(
                    args(action="service", value="preset", service_name="mariadb"), HOST
                ),
                4,
            )
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
