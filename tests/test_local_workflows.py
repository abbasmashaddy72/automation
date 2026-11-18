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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "lib"), str(ROOT / "ai"), str(ROOT / "scripts")]
import automation
import auth
import models
import developer
import ai_health


class LocalUserFlows(unittest.TestCase):
    def test_terminal_dashboard_routes_allow_only_exact_shells_and_approved_changes(
        self,
    ):
        import setup_dashboard

        preview = {"action": "terminal-current", "shell": "fish"}
        self.assertEqual(
            setup_dashboard.preview_arguments(preview, aur_ready=False),
            ["developer", "shell-show", "--shell", "fish"],
        )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {**preview, "confirmed": True}, aur_ready=False, execute=True
            )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {**preview, "shell": "/etc/passwd"}, aur_ready=False
            )

        request = {"action": "terminal-install", "shell": "fish"}
        argv = setup_dashboard.preview_arguments(request, aur_ready=False)
        self.assertIn("fish=fish", argv)
        self.assertIn("--no-auto-search", argv)
        self.assertEqual(argv[-1], "--dry-run")
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(request, aur_ready=False, execute=True)
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {**request, "shell": "fish; id"}, aur_ready=False
            )
        config = {
            "action": "terminal-configure",
            "shell": "zsh",
            "terminal_ai": True,
            "current_sha256": "a" * 64,
        }
        self.assertIn(
            "--terminal-ai", setup_dashboard.preview_arguments(config, aur_ready=False)
        )
        config.pop("terminal_ai")
        individual = setup_dashboard.preview_arguments(
            {**config, "commands": ["ai-ask", "pint"]}, aur_ready=False
        )
        self.assertIn("pint,ai-ask", individual)
        self.assertNotIn("--terminal-ai", individual)
        self.assertIn(
            "none",
            setup_dashboard.preview_arguments(
                {**config, "commands": []}, aur_ready=False
            ),
        )
        for commands in (["pint", "pint"], ["rm -rf"], "pint"):
            with self.assertRaises(ValueError):
                setup_dashboard.preview_arguments(
                    {**config, "commands": commands}, aur_ready=False
                )

    def test_terminal_ai_uses_only_selected_input_and_validates_suggestions(self):
        import terminal_ai

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.received = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                self.server.path = self.path
                self.send_response(200)
                self.end_headers()
                self.wfile.write(self.server.reply)

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            port = str(server.server_port)
            try:
                server.reply = b'data: {"choices":[{"delta":{"content":"Check the port."}}]}\n\ndata: [DONE]\n\n'
                output = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "setup.sh"),
                        "ai",
                        "server",
                        "ask",
                        "--port",
                        port,
                        "--",
                        "Why?",
                        "--help",
                        "--auto-prereqs",
                        "--yes",
                        "configure",
                    ],
                    input="Selected diagnostic",
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(output.returncode, 0, output.stderr)
                self.assertEqual(output.stdout, "Check the port.\n")
                self.assertEqual(server.path, "/v1/chat/completions")
                self.assertEqual(
                    server.received["messages"][1]["content"],
                    "Why? --help --auto-prereqs --yes configure\n\nSelected diagnostic",
                )
                server.reply = json.dumps(
                    {"choices": [{"message": {"content": "ls\necho injected"}}]}
                ).encode()
                with (
                    patch("sys.stdin", io.StringIO("list files")),
                    self.assertRaisesRegex(ValueError, "single plain command"),
                ):
                    terminal_ai.main(["suggest", "--port", port])
            finally:
                server.shutdown()
                worker.join(timeout=5)

    def test_dashboard_webui_install_uses_reviewed_source_and_approval(self):
        import setup_dashboard
        import webui

        request = {"action": "webui-plan", "port": 3100, "allow_pull": True}
        plan = setup_dashboard.preview_arguments(request, aur_ready=False)
        self.assertEqual(
            plan,
            [
                "webui",
                "plan",
                "--image",
                webui.DEFAULT_IMAGE,
                "--port",
                "3100",
                "--allow-pull",
            ],
        )
        install = {**request, "action": "webui-install"}
        for payload in (
            install,
            {**install, "confirmed": True, "image": "latest"},
            {**install, "confirmed": True, "port": True},
        ):
            with self.assertRaises(ValueError):
                setup_dashboard.preview_arguments(
                    payload, aur_ready=False, execute=True
                )
        self.assertEqual(
            setup_dashboard.preview_arguments(
                {**install, "confirmed": True}, aur_ready=False, execute=True
            ),
            ["webui", "install", *plan[2:], "--yes"],
        )

    def test_chat_background_starts_loopback_user_unit_and_refuses_foreign_stop(self):
        import chat_lite

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = chat_lite.BackgroundServer(root)
            service.directory.mkdir(parents=True)
            (service.directory / "server.js").touch()
            command = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
            with (
                patch.object(service, "command", command),
                patch.object(
                    service,
                    "inspect",
                    side_effect=[None, (3101, "active"), (3101, "active")],
                ),
                patch.object(
                    chat_lite, "node_executable", return_value="/usr/bin/node"
                ),
                patch.object(chat_lite, "ready", return_value=True),
                patch.object(chat_lite, "port_in_use", return_value=False),
            ):
                service.start(3101)
            self.assertEqual(command.call_args.args[0], "systemd-run")
            self.assertIn("--setenv=HOSTNAME=127.0.0.1", command.call_args.args)
            self.assertIn("--setenv=PORT=3101", command.call_args.args)
            foreign = subprocess.CompletedProcess(
                [], 0, "LoadState=loaded\nTransient=no\n", ""
            )
            with patch.object(service, "command", return_value=foreign) as call:
                with self.assertRaisesRegex(ValueError, "unrecognized"):
                    service.stop()
                call.assert_called_once()
                self.assertEqual(call.call_args.args[:2], ("systemctl", "show"))

    def test_dashboard_ai_routes_preserve_approval_and_loopback(self):
        import setup_dashboard

        payload = {
            "action": "ai-install",
            "model": "/srv/ai/models/example.gguf",
            "backend": "cpu",
            "install_mode": "reinstall",
            "confirmed": True,
        }
        args = setup_dashboard.preview_arguments(payload, aur_ready=False, execute=True)
        self.assertIn("--rebuild", args)
        self.assertNotIn("--update-source", args)
        self.assertIn("--no-pull", args)
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {**payload, "confirmed": False}, aur_ready=False, execute=True
            )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {"action": "ai-verify", "host": "192.168.0.1"}, aur_ready=False
            )
        self.assertEqual(
            setup_dashboard.preview_arguments(
                {"action": "ai-verify", "host": "::1", "port": 8081}, aur_ready=False
            ),
            ["ai", "server", "verify", "--host", "::1", "--port", "8081"],
        )

    def test_dashboard_eligibility_uses_a_validated_storage_path(self):
        import setup_dashboard

        self.assertEqual(
            setup_dashboard.preview_arguments(
                {"action": "ai-eligibility", "data_root": "/mnt/ai", "backend": "cpu"},
                aur_ready=False,
            ),
            ["ai", "server", "plan", "--data-root", "/mnt/ai"],
        )
        with self.assertRaisesRegex(ValueError, "absolute model directory"):
            setup_dashboard.preview_arguments(
                {"action": "ai-eligibility", "data_root": "invalid"}, aur_ready=False
            )

    def test_chat_preview_refuses_occupied_port_without_starting_node(self):
        import chat_lite

        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            root = Path(directory)
            build = root / ".next/standalone"
            build.mkdir(parents=True)
            (build / "server.js").touch()
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with (
                patch.object(
                    chat_lite, "node_executable", return_value="/usr/bin/node"
                ),
                patch.object(chat_lite.subprocess, "Popen") as launch,
            ):
                with self.assertRaisesRegex(ValueError, "already in use"):
                    chat_lite.PreviewServer(root).start(port)
            launch.assert_not_called()

    def test_dashboard_model_switch_and_test_require_confirmation(self):
        import setup_dashboard

        request = {
            "action": "ai-model-switch",
            "model": "/srv/ai/models/test.gguf",
            "gpu_layers": 25,
        }
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(request, aur_ready=False, execute=True)
        argv = setup_dashboard.preview_arguments(
            {**request, "confirmed": True}, aur_ready=False, execute=True
        )
        self.assertEqual(
            argv,
            [
                "ai",
                "server",
                "switch",
                "--model",
                request["model"],
                "--gpu-layers",
                "25",
                "--yes",
            ],
        )
        self.assertEqual(
            setup_dashboard.preview_arguments(
                {"action": "ai-model-test", "confirmed": True},
                aur_ready=False,
                execute=True,
            ),
            ["ai", "server", "test-model", "--yes"],
        )
        self.assertIn(
            "--update-source",
            setup_dashboard.preview_arguments(
                {"action": "ai-build", "install_mode": "update", "confirmed": True},
                aur_ready=False,
                execute=True,
            ),
        )

    def test_dashboard_model_download_requires_verified_metadata(self):
        import setup_dashboard

        payload = {
            "action": "ai-install",
            "model_url": "https://example.org/model.gguf",
            "sha256": "a" * 64,
            "size_bytes": 5000000,
            "confirmed": True,
        }
        args = setup_dashboard.preview_arguments(payload, aur_ready=False, execute=True)
        self.assertIn("--model-url", args)
        self.assertIn("--size-bytes", args)
        self.assertNotIn("--no-pull", args)
        for changes in ({"size_bytes": None}, {"model": "/srv/ai/models/example.gguf"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                setup_dashboard.preview_arguments(
                    {**payload, **changes}, aur_ready=False, execute=True
                )
        self.assertIn(
            "--php-sample",
            setup_dashboard.preview_arguments(
                {"action": "configuration", "php_sample": True}, aur_ready=False
            ),
        )

    def test_remote_verification_uses_the_targets_loopback(self):
        import remote_ai

        result = subprocess.CompletedProcess([], 0, '{"models":["sample"]}', "")
        with patch.object(remote_ai.subprocess, "run", return_value=result) as run:
            response = remote_ai.probe("ai-host", "operator", "/srv/toolkit", "verify")
        self.assertEqual(response["status"], 0)
        argv = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("ForwardAgent=no", argv)
        self.assertEqual(argv[-1], "bash /srv/toolkit/setup.sh ai server verify")

    def test_remote_model_actions_keep_argv_bounded_and_context_read_only(self):
        import remote_ai
        import setup_dashboard

        result = subprocess.CompletedProcess([], 0, "", "")
        target = ("ai-host", "operator", "/srv/toolkit")
        with patch.object(remote_ai.subprocess, "run", return_value=result) as run:
            remote_ai.probe(*target, "port-check", port=8081)
            self.assertTrue(
                run.call_args.args[0][-1].endswith("port-check --port 8081")
            )
            remote_ai.probe(*target, "context", context_tokens=4096)
            self.assertTrue(
                run.call_args.args[0][-1].endswith(
                    "context --context-tokens 4096 --dry-run"
                )
            )
            remote_ai.probe(*target, "test-model")
            self.assertTrue(run.call_args.args[0][-1].endswith("test-model --yes"))
            remote_ai.probe(*target, "package-status", packages=["git", "curl"])
            self.assertIn(
                "packages status --select git,curl", run.call_args.args[0][-1]
            )
            with self.assertRaises(ValueError):
                remote_ai.probe(*target, "package-status", packages=["curl; cat key"])
            with self.assertRaises(ValueError):
                remote_ai.probe(*target, "key-show")
            with self.assertRaises(ValueError):
                remote_ai.probe(*target, "port-check", port="8080; date")
        payload = {"action": "ai-context", "context_tokens": 4096}
        self.assertEqual(
            setup_dashboard.preview_arguments(payload, aur_ready=False)[-1], "--dry-run"
        )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(payload, aur_ready=False, execute=True)
        self.assertEqual(
            setup_dashboard.preview_arguments(
                {**payload, "confirmed": True}, aur_ready=False, execute=True
            )[-1],
            "--yes",
        )

    def test_system_cache_estimate_contains_only_native_candidates(self):
        import system_cleanup

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            obsolete = path / "example-1-1-x86_64.pkg.tar.zst"
            recent = path / "example-4-1-x86_64.pkg.tar.zst"
            obsolete.write_bytes(b"old")
            recent.write_bytes(b"keep")
            self.assertEqual(
                system_cleanup.cache_entries(
                    "arch", f"Candidate packages:\n{obsolete}"
                ),
                [{"path": str(obsolete), "bytes": 3}],
            )
            self.assertEqual(
                system_cleanup.cache_entries("arch", "no candidate packages"), []
            )
        self.assertEqual(
            system_cleanup.cache_entries("debian", "Del sample 1.0 [2.1 kB]"),
            [{"package": "sample", "version": "1.0", "bytes": 2100}],
        )

    def test_dashboard_reads_authentication_and_failure_events(self):
        import setup_dashboard

        self.assertEqual(
            setup_dashboard.package_event("Dashboard authentication: pending"),
            {"authentication": "pending"},
        )
        self.assertEqual(
            setup_dashboard.package_event(
                'AUR installation failed: {"name":"void-bin","actual":"void-bin","helper":"shelly"}'
            ),
            {
                "aur_failure": {
                    "name": "void-bin",
                    "actual": "void-bin",
                    "helper": "shelly",
                }
            },
        )
        self.assertIsNone(
            setup_dashboard.package_event('AUR installation failed: {"helper":"other"}')
        )

    def test_dashboard_checklist_mark_routes_only_manual_tasks(self):
        import checklist
        import setup_dashboard

        task = next(iter(checklist.IDS))
        request = {
            "action": "checklist-mark",
            "task": task,
            "state": "done",
            "confirmed": True,
        }
        self.assertEqual(
            setup_dashboard.operation_steps(request, aur_ready=False),
            [("checklist-mark", ["checklist", "done", task, "--yes"])],
        )
        for change in (
            {"confirmed": False},
            {"task": "configuration"},
            {"state": "automate"},
        ):
            with self.assertRaises(ValueError):
                setup_dashboard.operation_steps({**request, **change}, aur_ready=False)

    def test_dashboard_keeps_failed_aur_alternatives_explicit(self):
        import setup_dashboard

        payload = {"action": "packages", "packages": ["void-bin"]}
        alternative = setup_dashboard.preview_arguments(
            {**payload, "flatpak": True}, aur_ready=True
        )
        self.assertIn("--prefer-flatpak", alternative)
        self.assertIn("--dry-run", alternative)
        other_helper = setup_dashboard.preview_arguments(
            {**payload, "helper": "paru"}, aur_ready=True
        )
        self.assertEqual(other_helper[-2:], ["--source", "void-bin=paru"])
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                {**payload, "flatpak": True, "helper": "paru"}, aur_ready=True
            )

    def test_reviewed_batch_orders_settings_before_projects_and_packages(self):
        import setup_dashboard

        request = {
            "action": "batch",
            "confirmed": True,
            "steps": [
                {"action": "packages", "packages": ["git"], "fingerprint": "a" * 64},
                {"action": "configuration"},
                {
                    "action": "config-edit",
                    "values": {"AUTOMATION_PROJECT_SITES_DIR": "/home/example/custom"},
                },
            ],
        }
        steps = setup_dashboard.operation_steps(request, aur_ready=False)
        self.assertEqual(
            [name for name, _ in steps], ["config-edit", "configuration", "packages"]
        )
        with self.assertRaises(ValueError):
            setup_dashboard.operation_steps(
                {**request, "steps": [{"action": "cleanup"}]}, aur_ready=False
            )

    def test_saved_native_mapping_is_scoped_to_host(self):
        import package_mappings
        from providers import candidates

        host = {
            "id": "cachyos",
            "family": "arch",
            "arch": "x86_64",
            "manager": "pacman",
        }
        self.assertIn("brave-bin", candidates("brave-browser", host))
        with tempfile.TemporaryDirectory() as directory:
            state = str(Path(directory) / "state")
            package_mappings.save(host, state, "my-browser", "brave-bin")
            self.assertEqual(
                package_mappings.choices(host, state), {"my-browser": "brave-bin"}
            )
            self.assertEqual(
                package_mappings.choices({**host, "id": "arch"}, state), {}
            )

    def test_dashboard_requires_approval_and_reviewed_package_identities(self):
        import setup_dashboard

        payload = {"action": "packages", "packages": ["ripgrep"]}
        self.assertEqual(
            setup_dashboard.preview_arguments(payload, aur_ready=False),
            ["packages", "plan-json", "--dry-run", "--select", "ripgrep"],
        )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(payload, aur_ready=False, execute=True)
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                dict(payload, confirmed=True), aur_ready=False, execute=True
            )
        reviewed = dict(payload, confirmed=True, fingerprint="a" * 64)
        self.assertEqual(
            setup_dashboard.preview_arguments(reviewed, aur_ready=True, execute=True),
            [
                "packages",
                "install",
                "--yes",
                "--expected-plan",
                "a" * 64,
                "--select",
                "ripgrep",
                "--enable-aur",
            ],
        )
        with self.assertRaises(ValueError):
            setup_dashboard.preview_arguments(
                dict(reviewed, packages=["--update"]), aur_ready=True, execute=True
            )

    def test_telemetry_restore_preserves_edits_to_unrelated_settings(self):
        import zed_settings

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            target = Path(directory) / "zed/settings.json"
            target.parent.mkdir()
            state = str(Path(directory) / "state")
            target.write_text('{"theme":"Light","telemetry":{"metrics":true}}')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    zed_settings.telemetry(
                        Namespace(action="disable", value=None, dry_run=False),
                        lambda *_: True,
                        state=state,
                    ),
                    0,
                )
                data = json.loads(target.read_text())
                self.assertEqual(
                    data["telemetry"], {"metrics": False, "diagnostics": False}
                )
                data["theme"] = "Dark"
                target.write_text(json.dumps(data))
                self.assertEqual(
                    zed_settings.telemetry(
                        Namespace(action="restore", value=None, dry_run=False),
                        lambda *_: True,
                        state=state,
                    ),
                    0,
                )
            self.assertEqual(
                json.loads(target.read_text()),
                {"theme": "Dark", "telemetry": {"metrics": True}},
            )

    def test_text_wizard_can_choose_profile_even_with_configured_defaults(self):
        entries = [
            {"id": "curl", "category": "Essential System Utilities", "default": True},
            {"id": "firefox", "category": "Desktop", "default": True},
        ]
        settings = {"AUTOMATION_PROFILE": "default", "AUTOMATION_LERD": "false"}
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch.object(automation.shutil, "which", return_value=None),
            patch.object(automation, "installed", return_value=False),
            patch("builtins.input", side_effect=["3", "all", "done"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            profile, selected = automation.select_interactive(
                entries, {"family": "debian"}, settings, prompt_profile=True
            )
        self.assertEqual(profile, "minimal")
        self.assertEqual(selected, ["curl"])
        self.assertEqual(settings["AUTOMATION_PROFILE"], "default")

    def test_browser_category_checks_only_browser_packages_in_both_wizards(self):
        entries = [
            {"id": "firefox", "category": "Browsers", "default": True},
            {"id": "git", "category": "Development", "default": True},
            {"id": "lerd", "category": "Development", "default": True},
        ]
        settings = {"AUTOMATION_PROFILE": "default"}
        info = {"family": "arch", "desktop": True}
        for gum in (False, True):
            with (
                self.subTest(gum=gum),
                patch("sys.stdin.isatty", return_value=True),
                patch.object(
                    automation.shutil,
                    "which",
                    return_value="/usr/bin/gum" if gum else None,
                ),
                patch.object(automation, "lerd_compat", return_value=[]),
                patch.object(automation, "installed", return_value=False) as installed,
                patch("builtins.input", side_effect=["", "1", "done"]),
                patch.object(
                    automation,
                    "gum_choose",
                    side_effect=[
                        Namespace(returncode=0, stdout="Lerd-managed (recommended)\n"),
                        Namespace(returncode=0, stdout="Browsers\n"),
                        Namespace(
                            returncode=0, stdout="firefox  [check during plan]\n"
                        ),
                    ],
                ) as choose,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    automation.select_interactive(entries, info, settings),
                    ("default", ["firefox"]),
                )
                installed.assert_called_once_with("firefox", "arch")
                if gum:
                    self.assertFalse(
                        any(
                            arg.startswith("--selected")
                            for arg in choose.call_args_list[1].args
                        )
                    )

    def test_jan_openai_api_contract_is_loopback_authenticated(self):
        with tempfile.TemporaryDirectory() as td:
            key = Path(td) / "private/api-key"
            auth.save(key, "sk-local-" + "j" * 40)
            expected = auth.read(key)

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.headers.get("Authorization") != "Bearer " + expected:
                        self.send_response(401)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"data":[{"id":"tiny-fixture"}]}')

                def do_POST(self):
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    if self.headers.get("Authorization") != "Bearer " + expected:
                        self.send_response(401)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"choices":[{"message":{"content":"OK"}}]}')

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        ai_health.check_api(
                            "jan", port=server.server_port, key_file=key
                        ),
                        0,
                    )
                    self.assertEqual(
                        ai_health.model_inventory(
                            "jan", port=server.server_port, key_file=key
                        ),
                        0,
                    )
                    self.assertEqual(
                        auth.test_endpoint("jan", key, port=server.server_port), 0
                    )
                    self.assertEqual(
                        ai_health.smoke_inference(
                            "jan", "tiny-fixture", port=server.server_port, key_file=key
                        ),
                        0,
                    )
                    self.assertEqual(
                        ai_health.check_api("jan", port=server.server_port), 3
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_new_api_keys_cannot_be_written_into_source_tree(self):
        with self.assertRaises(ValueError):
            auth.save(ROOT / "must-not-create-private-key", "sk-local-" + "p" * 40)
        self.assertFalse((ROOT / "must-not-create-private-key").exists())

    def test_lock_retry_is_bounded_and_general_errors_are_not_retried(self):
        args = Namespace(dry_run=False)
        with (
            patch.object(
                automation.subprocess,
                "run",
                side_effect=[
                    Mock(
                        returncode=1,
                        stdout="",
                        stderr="Could not get lock /var/lib/dpkg/lock",
                    ),
                    Mock(returncode=0, stdout="ok", stderr=""),
                ],
            ) as run,
            patch.object(automation.time, "sleep"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.run(
                    ["apt-get", "install", "git"], mutate=True, args=args, retries=2
                ),
                0,
            )
            self.assertEqual(run.call_count, 2)
        with (
            patch.object(
                automation.subprocess,
                "run",
                return_value=Mock(returncode=1, stdout="", stderr="Package not found"),
            ) as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.run(
                    ["apt-get", "install", "git"], mutate=True, args=args, retries=2
                ),
                1,
            )
            self.assertEqual(run.call_count, 1)

    def test_model_search_is_readonly_validated_and_bounded(self):
        response = Mock(status=200)
        response.read.return_value = b'[{"id":"publisher/model"},{"id":"bad;value"}]'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(
            models.urllib.request,
            "build_opener",
            return_value=Mock(open=Mock(return_value=response)),
        ) as opener:
            result = models.search("tiny model", limit=2)
            self.assertEqual([x["model"] for x in result], ["publisher/model"])
            self.assertIn("ProxyHandler", str(type(opener.call_args.args[0])))
            response.read.assert_called_once_with(262145)
        with self.assertRaises(ValueError):
            models.search("$(touch /tmp/bad)")

    def test_service_preflight_does_not_request_compiler(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scripts").mkdir()
            (root / "ai").mkdir()
            (root / "setup.sh").write_bytes((ROOT / "setup.sh").read_bytes())
            (root / "scripts/prerequisites.sh").write_text(
                '#!/bin/bash\nprintf "%s\\n" "$*" > "$PREFLIGHT_LOG"\n'
            )
            (root / "ai/manager.py").write_text("pass\n")
            cp = subprocess.run(
                ["bash", str(root / "setup.sh"), "ai", "llamacpp", "start", "--yes"],
                env={**os.environ, "PREFLIGHT_LOG": str(root / "calls")},
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertNotIn("--with-ai-build", (root / "calls").read_text())

    def test_native_query_locale_is_predictable_without_changing_parent_env(self):
        import providers, discovery, sources

        for module, function, args in [
            (providers, providers._run, (["rpm", "-q", "git"],)),
            (discovery, discovery._execute, (["apt-cache", "search", "git"],)),
            (sources, sources._execute, (["paru", "-Si", "git"],)),
        ]:
            with (
                self.subTest(module=module.__name__),
                patch.dict(os.environ, {"LC_ALL": "de_DE.UTF-8"}),
                patch.object(module.shutil, "which", return_value="/tool"),
                patch.object(
                    module.subprocess, "run", return_value=Mock(returncode=0, stdout="")
                ) as run,
            ):
                function(*args)
                self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")
                self.assertEqual(os.environ["LC_ALL"], "de_DE.UTF-8")

    def test_immutable_variants_and_suse_atomic_derivatives_are_planning_only(self):
        import providers

        for data in (
            {"ID": "fedora", "VARIANT_ID": "coreos"},
            {"ID": "aeon", "ID_LIKE": "opensuse"},
            {"ID": "opensuse-kalpa", "ID_LIKE": "suse"},
        ):
            info = automation.platform_info(data)
            self.assertTrue(info["immutable"])
            self.assertFalse(providers.capability(info)["host_install_allowed"])

    def test_bash_bootstrap_refuses_missing_python_installation_under_wsl(self):
        import re

        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "prerequisites.sh"
            content = (ROOT / "scripts/prerequisites.sh").read_text()
            content = re.sub(
                r"python_ok\(\) \{.*?\n\}",
                "python_ok() {\n    return 1\n}",
                content,
                count=1,
                flags=re.S,
            )
            # Repository tools can create state even with cache-only queries.
            content = re.sub(
                r"package_available\(\) \{.*?\n\}",
                'package_available() {\n    mkdir -p -- "$XDG_STATE_HOME"\n    return 0\n}',
                content,
                count=1,
                flags=re.S,
            )
            # Even a regression in the guard cannot invoke a real installer.
            content = content.replace(
                '"${PRIV[@]}" "${cmd[@]}" "${missing[@]}"',
                'printf "forbidden-install\\n" >&2; exit 99',
            )
            script.write_text(content)
            cp = subprocess.run(
                [
                    "bash",
                    str(script),
                    "install",
                    "--runtime-only",
                    "--without-ui",
                    "--yes",
                ],
                env={
                    **os.environ,
                    "WSL_DISTRO_NAME": "fixture-wsl",
                    "XDG_STATE_HOME": str(Path(td) / "state"),
                },
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(cp.returncode, 3, cp.stdout + cp.stderr)
            self.assertIn("Read-only planning target", cp.stdout)
            self.assertFalse((Path(td) / "state").exists())

    def test_container_snapshot_never_mounts_local_credentials_or_model_artifacts(self):
        import container_workflows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "source"
            root.mkdir()
            for name in (
                ".env",
                ".env.production",
                "private.key",
                "private.pem",
                "model.gguf",
                "model.safetensors",
                "old.zip",
                "module.py",
            ):
                (root / name).write_text("fixture")
            outside = Path(td) / "private-data"
            outside.write_text("fixture-private-data")
            (root / "outside-link").symlink_to(outside)
            observed = {}

            def probe(name, **kwargs):
                source = kwargs["source"]
                observed["files"] = {p.name for p in source.iterdir()}
                return {"status": "pass"}

            with (
                patch.object(container_workflows, "ROOT", root),
                patch.object(container_workflows, "probe", side_effect=probe),
                patch.object(
                    container_workflows.shutil, "which", return_value="/podman"
                ),
                patch.object(
                    container_workflows.subprocess,
                    "run",
                    return_value=Mock(returncode=0, stdout="true\n"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    container_workflows.main(
                        [
                            "--allow-install",
                            "--containers",
                            "debian",
                            "--output",
                            str(Path(td) / "output"),
                        ]
                    ),
                    0,
                )
            self.assertEqual(observed["files"], {"module.py"})


class DeveloperFlows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(
            os.environ,
            {
                "HOME": str(self.root),
                "XDG_CONFIG_HOME": str(self.root / ".config"),
                "XDG_STATE_HOME": str(self.root / "state"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.args = Namespace(
            action="shell",
            shell="bash",
            name="Fixture User",
            email="fixture@example.test",
            value=None,
            dry_run=False,
            yes=True,
        )

    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return developer.main(self.args, lambda *_: True)

    def test_shell_merge_idempotency_and_restore_preserve_original_bytes(self):
        path = self.root / ".bashrc"
        original = b"# user-owned\nexport EXISTING=value\n"
        path.write_bytes(original)
        self.assertEqual(self.apply(), 0)
        after = path.read_bytes()
        self.assertTrue(after.startswith(original))
        self.assertEqual(self.apply(), 0)
        self.assertEqual(path.read_bytes(), after)
        folder = self.root / "state/automation-toolkit/developer"
        self.assertEqual(len(list(folder.iterdir())), 1)
        self.args.action = "restore"
        self.args.value = next(folder.iterdir()).name
        self.assertEqual(self.apply(), 0)
        self.assertEqual(path.read_bytes(), original)

    def test_restore_refuses_later_user_edit(self):
        self.apply()
        path = self.root / ".bashrc"
        path.write_text("user later edit")
        self.args.action = "restore"
        self.args.value = next(
            (self.root / "state/automation-toolkit/developer").iterdir()
        ).name
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(path.read_text(), "user later edit")

    def test_git_identity_uses_git_parser_preserves_other_settings(self):
        self.args.action = "git"
        path = self.root / ".gitconfig"
        path.write_text("[core]\n\teditor = vi\n")
        self.assertEqual(self.apply(), 0)
        for key, wanted in [
            ("core.editor", "vi"),
            ("user.name", "Fixture User"),
            ("user.email", "fixture@example.test"),
        ]:
            cp = subprocess.run(
                ["git", "config", "--file", str(path), "--get", key],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(cp.stdout.strip(), wanted)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_git_invalid_identity_and_shell_blocks_preserve_user_data(self):
        self.args.action = "git"
        self.args.email = "bad email"
        path = self.root / ".gitconfig"
        path.write_text("# original")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(path.read_text(), "# original")
        with self.assertRaises(ValueError):
            developer.shell_content((developer.BEGIN + "\n").encode(), "bash")

    def test_dryrun_and_refusal_create_no_files(self):
        self.args.dry_run = True
        self.assertEqual(self.apply(), 0)
        self.assertEqual(list(self.root.iterdir()), [])
        self.args.dry_run = False
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(developer.main(self.args, lambda *_: False), 4)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_shell_templates_parse_and_never_execute_on_read(self):
        for shell in ("bash", "zsh", "fish"):
            content = developer.shell_content(b"# existing\n", shell)
            self.assertEqual(developer.shell_content(content, shell), content)
            if shell == "bash":
                cp = subprocess.run(
                    ["bash", "-n"], input=content, capture_output=True, timeout=5
                )
                self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_sourcing_shell_block_twice_preserves_aliases_and_deduplicates_path(self):
        path = self.root / "fixture.sh"
        path.write_bytes(developer.shell_content(b"", "bash"))
        script = 'alias artisan="printf existing"; source "$1"; first="$PATH"; source "$1"; [[ "$PATH" == "$first" ]] || exit 1; [[ "$(alias artisan)" == *existing* ]] || exit 2'
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", script, "fixture", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symlink_targets_are_never_modified(self):
        outside = self.root / "outside"
        outside.write_text("keep")
        (self.root / ".bashrc").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(outside.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
