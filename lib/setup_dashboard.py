"""Serve the local setup UI and run allowlisted read-only previews."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack
import codecs
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import tempfile
from pathlib import Path
import webbrowser

import discovery
import checklist
import configuration
import sources
import webui
import wizard


ACTIONS = {
    "system": ["--check"],
    "hardware": ["ai", "server", "hardware"],
    "system-details": ["ai", "server", "system-details"],
    "updates": ["system-cleanup", "updates"],
    "system-cleanup": ["system-cleanup", "plan"],
    "checklist": ["checklist", "check"],
    "checklist-tasks": ["checklist", "list"],
    "configuration": [
        "checklist",
        "automate",
        "--select",
        "configuration,projects",
        "--dry-run",
    ],
    "zed": ["zed", "plan"],
    "zed-status": ["zed", "status"],
    "zed-current": ["zed", "show"],
    "desktop": ["desktop", "status"],
    "cleanup": ["cleanup", "plan"],
    "inventory": ["inventory"],
    "recovery": ["recovery", "status"],
    "lerd": ["lerd", "status"],
    "terminal-status": ["developer", "shell-status"],
    "lerd-availability": ["lerd", "availability"],
    "lerd-install": ["lerd", "install", "--dry-run"],
    "lerd-repair": ["lerd", "repair", "--dry-run"],
    "ai-storage": ["ai", "server", "storage"],
    "ai-models": ["ai", "server", "models"],
    "ai-verify": ["ai", "server", "verify"],
    "ai-port-check": ["ai", "server", "port-check"],
    "ai-runtime-context": ["ai", "server", "runtime-context"],
    "ai-status": ["ai", "server", "status"],
    "ai-plan": ["ai", "server", "plan"],
    "ai-eligibility": ["ai", "server", "plan"],
    "chat": ["chat-lite", "status"],
    "webui": ["webui", "status", "--discover"],
    "webui-test": ["webui", "test"],
    "ai-engines": ["ai", "server", "engines"],
    "telemetry": ["telemetry", "status"],
    "system-telemetry": ["system-telemetry", "status"],
    "advanced": ["config", "editor"],
    "zed-backup": ["zed", "backup", "--dry-run"],
    "chat-build": ["chat-lite", "build", "--dry-run"],
    "aur-helpers": ["packages", "search", "yay"],
}

CHANGES = {
    "configuration": ["checklist", "automate", "--select", "configuration,projects"],
    "zed": ["zed", "apply"],
    "cleanup": ["cleanup", "cache"],
    "system-cleanup": ["system-cleanup", "cache"],
    "telemetry-disable": ["telemetry", "disable"],
    "telemetry-restore": ["telemetry", "restore"],
    "system-telemetry-disable": ["system-telemetry", "disable"],
    "system-telemetry-restore": ["system-telemetry", "restore"],
    "zed-backup": ["zed", "backup"],
    "chat-build": ["chat-lite", "build"],
    "chat-remove": ["chat-lite", "remove"],
    "lerd-install": ["lerd", "install"],
    "lerd-repair": ["lerd", "repair"],
    **{f"webui-{action}": ["webui", action] for action in ("start", "stop", "recover")},
    "chat-background-stop": ["chat-lite", "stop"],
    **{
        f"ai-{action}": ["ai", "server", action]
        for action in ("start", "stop", "restart")
    },
}


def preview_arguments(payload, *, aur_ready, execute=False):
    if not isinstance(payload, dict):
        raise ValueError("Expected a preview request")
    action = payload.get("action")
    if not isinstance(action, str):
        raise ValueError("Expected an action")
    if execute and payload.get("confirmed") is not True:
        raise ValueError("Confirm the change first")
    if action == "backup-browse":
        path = payload.get("path")
        if execute or (
            path is not None and (not isinstance(path, str) or len(path) > 4096)
        ):
            raise ValueError("Choose a directory to browse")
        return (
            ["smart-backup", "browse"]
            + ([f"--path={path}"] if path is not None else [])
            + (["--hidden"] if payload.get("hidden") is True else [])
        )
    if action == "backup-run":
        spec = json.dumps(payload.get("spec"))
        if len(spec) > 32768:
            raise ValueError("Backup selection is too large")
        if not execute:
            return ["smart-backup", "plan", "--json", "--spec", spec]
        revision = payload.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise ValueError("Preview the backup before creating it")
        return [
            "smart-backup",
            "run",
            "--spec",
            spec,
            "--expected-plan",
            revision,
            "--yes",
        ]
    if action == "terminal-current":
        shell = payload.get("shell")
        if execute or shell not in ("bash", "fish", "zsh"):
            raise ValueError("Choose Bash, Fish or Zsh for a read-only preview")
        return ["developer", "shell-show", "--shell", shell]
    if action in ("terminal-configure", "terminal-default", "terminal-install"):
        shell = payload.get("shell")
        if shell not in ("bash", "fish", "zsh"):
            raise ValueError("Choose Bash, Fish or Zsh")
        approval = "--yes" if execute else "--dry-run"
        if action == "terminal-install":
            return [
                "packages",
                "install",
                "--select",
                shell,
                "--replace",
                f"{shell}={shell}",
                "--no-auto-search",
                approval,
            ]
        if action == "terminal-default":
            return ["developer", "shell-default", "--shell", shell, approval]
        banner = payload.get("banner", "none")
        greeting = payload.get("fish_greeting", "keep")
        revision = payload.get("current_sha256")
        selections = []
        if "commands" in payload:
            from terminal_setup import validate_commands

            chosen = validate_commands(payload["commands"], shell)
            if (
                payload.get("terminal_ai") is True
                or payload.get("project_cleanup_aliases") is True
            ):
                raise ValueError("Choose individual commands or a legacy group")
            selections = ["--shell-commands", ",".join(chosen) or "none"]
        if (
            banner not in ("none", "fastfetch", "neofetch")
            or greeting not in ("keep", "off")
            or (greeting == "off" and shell != "fish")
            or (shell == "bash" and payload.get("project_cleanup_aliases") is True)
            or not isinstance(revision, str)
            or not re.fullmatch("[a-f0-9]{64}", revision)
        ):
            raise ValueError(
                "Reload the shell state and choose valid configuration options"
            )
        return [
            "developer",
            "shell",
            "--shell",
            shell,
            "--banner",
            banner,
            "--fish-greeting",
            greeting,
            "--current-sha256",
            revision,
            *selections,
            *(["--terminal-ai"] if payload.get("terminal_ai") is True else []),
            *(["--migrate-legacy"] if payload.get("migrate_legacy") is True else []),
            *(
                ["--use-toolkit-agent"]
                if payload.get("use_toolkit_agent") is True
                else []
            ),
            *(
                ["--project-cleanup-aliases"]
                if payload.get("project_cleanup_aliases") is True
                else []
            ),
            approval,
        ]
    if action == "ai-context":
        tokens = payload.get("context_tokens")
        if type(tokens) is not int or not 256 <= tokens <= 131072:
            raise ValueError("Choose a context size from 256 to 131072 tokens")
        return [
            "ai",
            "server",
            "context",
            "--context-tokens",
            str(tokens),
            "--yes" if execute else "--dry-run",
        ]
    if not execute and action in ("ai-port-check", "ai-runtime-context"):
        port = payload.get("port")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("Choose a port between 1 and 65535")
        return [*ACTIONS[action], *(["--port", str(port)] if port is not None else [])]
    if action == ("webui-install" if execute else "webui-plan"):
        image = payload.get("image", webui.DEFAULT_IMAGE)
        port = payload.get("port", 3000)
        if not isinstance(image, str) or not webui.IMAGE.fullmatch(image):
            raise ValueError("Enter a digest-pinned official Open WebUI image")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Choose a port between 1024 and 65535")
        return [
            "webui",
            "install" if execute else "plan",
            "--image",
            image,
            "--port",
            str(port),
            *(["--allow-pull"] if payload.get("allow_pull") is True else []),
            *(["--yes"] if execute else []),
        ]
    if execute and action == "chat-background-start":
        port = payload.get("port", 3001)
        if type(port) is not int or not 1024 <= port <= 65535 or port == 8080:
            raise ValueError("Choose a port between 1024 and 65535 other than 8080")
        return ["chat-lite", "start", "--port", str(port), "--yes"]
    if execute and action == "checklist-mark":
        task = payload.get("task")
        state = payload.get("state")
        if (
            not isinstance(task, str)
            or task not in checklist.IDS
            or state not in ("done", "pending")
        ):
            raise ValueError("Choose a manual checklist task and valid status")
        return ["checklist", state, task, "--yes"]
    if action == "config-edit":
        changes = payload.get("values")
        if (
            not isinstance(changes, dict)
            or set(changes) - configuration.EDITABLE.keys()
        ):
            raise ValueError("Provide configuration values")
        return [
            "config",
            "edit",
            json.dumps(changes),
            "--yes" if execute else "--dry-run",
        ]
    if action == "configuration" and payload.get("php_sample") is True:
        command = CHANGES[action] if execute else ACTIONS[action]
        return [*command, "--php-sample", *(["--yes"] if execute else [])]
    if not execute and action == "project-path":
        target = payload.get("target")
        if target is not None and (
            not isinstance(target, str) or (target and not target.startswith("/"))
        ):
            raise ValueError("Use an absolute project path")
        return [
            "projects",
            "layout",
            *([target] if target else []),
            *(["--php-sample"] if payload.get("php_sample") is True else []),
            "--dry-run",
        ]
    if action in ("config-restore", "zed-restore"):
        prefix = action.split("-")[0]
        backup = payload.get("backup")
        if not isinstance(backup, str) or not re.fullmatch(
            prefix + r"-[a-f0-9]{32}\.json", backup
        ):
            raise ValueError("Choose a valid backup ID")
        return [prefix, "restore", backup, "--yes" if execute else "--dry-run"]
    if action == "mapping":
        name = discovery.validate_term(payload.get("name"))
        actual = discovery.validate_term(payload.get("actual"))
        return [
            "packages",
            "mapping",
            name,
            "--replace",
            f"{name}={actual}",
            "--yes" if execute else "--dry-run",
        ]
    if execute and action in (
        "ai-model-download",
        "ai-model-switch",
        "ai-build",
        "ai-model-test",
    ):
        if action == "ai-model-test":
            return ["ai", "server", "test-model", "--yes"]
        if action == "ai-build":
            mode = payload.get("install_mode", "install")
            if mode not in ("install", "update", "reinstall"):
                raise ValueError("Choose a build action")
            flags = {
                "install": [],
                "update": ["--update-source"],
                "reinstall": ["--rebuild"],
            }
            return [
                "ai",
                "server",
                "build",
                *ai_options({"backend": payload.get("backend")}),
                *flags[mode],
                "--yes",
            ]
        model = ai_model_options(payload)
        if action == "ai-model-download" and model[:1] == ["--model-url"]:
            return [
                "ai",
                "server",
                "model-download",
                *model,
                *ai_options({"data_root": payload.get("data_root")}),
                "--yes",
            ]
        if action == "ai-model-switch" and model[:1] == ["--model"]:
            return [
                "ai",
                "server",
                "switch",
                *model,
                *ai_options({"gpu_layers": payload.get("gpu_layers")}),
                "--yes",
            ]
        raise ValueError(
            "Select the model file or complete the verified download fields first"
        )
    if action == "ai-install" and execute:
        mode = payload.get("install_mode", "install")
        if mode not in ("install", "update", "reinstall"):
            raise ValueError("Choose install, update, or reinstall")
        model_options = ai_model_options(payload)
        if not model_options:
            raise ValueError("Choose an existing GGUF or a verified download")
        return [
            "ai",
            "server",
            "install",
            *model_options,
            *(["--no-pull"] if payload.get("model") else []),
            "--yes",
            *(
                ["--update-source"]
                if mode == "update"
                else ["--rebuild"]
                if mode == "reinstall"
                else []
            ),
            *ai_options(payload),
            *(["--reconfigure"] if payload.get("reconfigure") is True else []),
        ]
    if not execute and action == "ai-verify":
        host = payload.get("host", "127.0.0.1")
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("Model inventory checks require a loopback endpoint")
        port = payload.get("port")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("Choose a port between 1 and 65535")
        return [
            *ACTIONS[action],
            "--host",
            host,
            *(["--port", str(port)] if port is not None else []),
        ]
    if not execute and action == "ai-models":
        return [*ACTIONS[action], *ai_options({"data_root": payload.get("data_root")})]
    if not execute and action == "ai-plan":
        return [*ACTIONS[action], *ai_options(payload), *ai_model_options(payload)]
    if (
        action in ("chat", "chat-build", "chat-remove")
        and payload.get("port") is not None
    ):
        port = payload["port"]
        if type(port) is not int or not 1024 <= port <= 65535 or port == 8080:
            raise ValueError(
                "Choose a ChatGPT Lite port between 1024 and 65535 other than 8080"
            )
        command = CHANGES.get(action) if execute else ACTIONS.get(action)
        if command:
            return [*command, "--port", str(port), *(["--yes"] if execute else [])]
    if execute and action in CHANGES:
        return [*CHANGES[action], "--yes"]
    if not execute and action in ACTIONS:
        return ACTIONS[action]
    names = payload.get("packages")
    if not execute and action == "status":
        if isinstance(names, list) and 0 < len(names) <= 150:
            return [
                "packages",
                "status",
                "--select",
                ",".join(map(discovery.validate_term, names)),
            ]
    if not execute and action == "search":
        return [
            "packages",
            "search",
            discovery.validate_term(payload.get("query")),
            "--dry-run",
        ]
    if (
        action not in ("packages", "repair")
        or not isinstance(names, list)
        or not names
        or len(names) > 150
    ):
        raise ValueError("Select valid packages and sources")
    names = list(dict.fromkeys(map(discovery.validate_term, names)))
    flatpak = payload.get("flatpak", False)
    if type(flatpak) is not bool or (flatpak and action != "packages"):
        raise ValueError("Invalid Flatpak selection")
    helper = payload.get("helper")
    if helper is not None and (
        helper not in sources.HELPERS
        or not aur_ready
        or len(names) != 1
        or flatpak
        or action != "packages"
    ):
        raise ValueError("Choose one supported AUR helper for this package")
    fingerprint = payload.get("fingerprint")
    if execute and (
        not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    ):
        raise ValueError("Preview the package plan first")
    verb = (
        ("repair" if action == "repair" else "install")
        if execute
        else ("repair-plan" if action == "repair" else "plan-json")
    )
    return [
        "packages",
        verb,
        *(["--yes", "--expected-plan", fingerprint] if execute else ["--dry-run"]),
        "--select",
        ",".join(names),
        *(["--enable-aur"] if aur_ready else []),
        *(["--prefer-flatpak"] if flatpak else []),
        *(["--source", f"{names[0]}={helper}"] if helper else []),
    ]


def ai_model_options(payload):
    model = payload.get("model")
    url = payload.get("model_url")
    digest = payload.get("sha256")
    size = payload.get("size_bytes")
    if model:
        if (
            not isinstance(model, str)
            or len(model) > 1024
            or not model.startswith("/")
            or not model.lower().endswith(".gguf")
            or any(ord(c) < 32 for c in model)
            or any((url, digest, size))
        ):
            raise ValueError("Choose one absolute GGUF file or one verified download")
        return ["--model", model]
    if any((url, digest, size)):
        if (
            not isinstance(url, str)
            or len(url) > 2048
            or not url.startswith("https://")
            or "?" in url
            or "#" in url
            or any(c.isspace() for c in url)
            or not isinstance(digest, str)
            or not re.fullmatch("[a-fA-F0-9]{64}", digest)
            or type(size) is not int
            or not 4 <= size <= 100 * 1024**3
        ):
            raise ValueError(
                "Enter an HTTPS GGUF URL, independently verified SHA-256 and exact byte size"
            )
        return ["--model-url", url, "--sha256", digest, "--size-bytes", str(size)]
    return []


def ai_options(payload):
    root = payload.get("data_root")
    port = payload.get("port")
    options = []
    backend = payload.get("backend")
    if backend:
        if backend not in ("auto", "cpu", "cuda", "hip", "vulkan"):
            raise ValueError("Choose a supported inference build")
        options.extend(["--backend", backend])
    if root:
        if not isinstance(root, str) or not re.fullmatch(
            r"/[A-Za-z0-9_.+/-]{1,512}", root
        ):
            raise ValueError("Enter an absolute model directory")
        options.extend(["--data-root", root])
    layers = payload.get("gpu_layers")
    if layers is not None:
        if type(layers) is not int or not 0 <= layers <= 999:
            raise ValueError("Choose a GPU layer count between 0 and 999")
        options.extend(["--gpu-layers", str(layers)])
    if port is not None:
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Choose a port between 1024 and 65535")
        options.extend(["--port", str(port)])
    return options


BATCH_ORDER = (
    "config-edit",
    "configuration",
    "packages",
    "repair",
    "zed",
    "chat-build",
    "ai-install",
)


def operation_steps(payload, *, aur_ready):
    if payload.get("action") != "batch":
        return [
            (
                payload["action"],
                preview_arguments(payload, aur_ready=aur_ready, execute=True),
            )
        ]
    actions = payload.get("steps")
    if (
        payload.get("confirmed") is not True
        or not isinstance(actions, list)
        or not actions
        or len(actions) > len(BATCH_ORDER)
    ):
        raise ValueError("Review and confirm a setup plan")
    steps = {}
    for step in actions:
        if (
            not isinstance(step, dict)
            or step.get("action") not in BATCH_ORDER
            or step["action"] in steps
        ):
            raise ValueError("Unsupported or duplicate setup operation")
        steps[step["action"]] = preview_arguments(
            {**step, "confirmed": True}, aur_ready=aur_ready, execute=True
        )
    return [(name, steps[name]) for name in BATCH_ORDER if name in steps]


def refresh_sudo(stop, command, *, interval=30):
    # Refresh an existing terminal ticket only. The first privileged command
    # owns authentication and displays its normal terminal prompt.
    while not stop.wait(interval):
        try:
            subprocess.run(
                [command, "-n", "-v"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def package_event(line):
    prefix = "Dashboard authentication: "
    if line.startswith(prefix):
        phase = line[len(prefix) :].strip()
        if phase in ("checking", "pending", "complete", "failed", "recipe-review"):
            return {"authentication": phase}
    prefix = "AUR installation failed: "
    if line.startswith(prefix):
        try:
            failure = json.loads(line[len(prefix) :])
            if failure["helper"] in sources.HELPERS:
                return {
                    "aur_failure": {
                        "name": discovery.validate_term(failure["name"]),
                        "actual": discovery.validate_term(failure["actual"]),
                        "helper": failure["helper"],
                    }
                }
        except (ValueError, TypeError, KeyError):
            pass
    prefix = "Dashboard package result: "
    if line.startswith(prefix):
        try:
            result = json.loads(line[len(prefix) :])
            if type(result["failed"]) is bool:
                return {
                    "package_result": {
                        "name": discovery.validate_term(result["name"]),
                        "failed": result["failed"],
                    }
                }
        except (ValueError, TypeError, KeyError):
            pass
    return None


def serve(root, entries, info, settings):
    if os.geteuid() == 0:
        print("Run the setup dashboard as your regular desktop user.")
        return 3

    arch = info["family"] == "arch"
    separate = ("bash", "fish", "zsh", "lerd")
    entries = [row for row in entries if row["id"] not in separate]
    if not arch:
        entries = [row for row in entries if row["id"] not in {"shelly", "base-devel"}]
    helpers = sources.working_helpers(info)
    aur_ready = bool(helpers)
    state = {
        "distro": info["id"],
        "manager": info["manager"],
        "architecture": info.get("arch", "unknown"),
        "separate_packages": separate,
        "arch": arch,
        "packages": [{"id": row["id"], "category": row["category"]} for row in entries],
        "profiles": {
            profile: wizard.profile_defaults(entries, profile, include_lerd=True)
            for profile in ("default", "minimal", "developer")
        },
        "aur_helpers": helpers,
        "terminal": sys.stdin.isatty(),
        "webui_image": webui.DEFAULT_IMAGE,
        "shell": Path(os.environ.get("SHELL", "")).name,
    }
    token = secrets.token_urlsafe(32)
    state["token"] = token
    ui = root / "lib" / "dashboard_ui"
    files = {
        "/": ("index.html", "text/html"),
        "/style.css": ("style.css", "text/css"),
        "/app.js": ("app.js", "text/javascript"),
    }
    from chat_lite import BackgroundServer, PreviewServer, ready as chat_ready
    from chat_lite import status as chat_status

    previews = threading.Lock()
    chat_preview = PreviewServer(root / "chatgpt-lite")
    chat_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def respond(self, status, content, kind="text/plain"):
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'none'",
            )
            try:
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def do_GET(self):
            if self.headers.get("Host") != host:
                return self.respond(403, b"Invalid host")
            if self.path == "/catalog":
                return self.respond(200, json.dumps(state).encode(), "application/json")
            if self.path not in files:
                return self.respond(404, b"Not found")
            name, kind = files[self.path]
            self.respond(200, (ui / name).read_bytes(), kind)

        def do_POST(self):
            with ExitStack() as resources:
                self.handle_operation(resources)

        def handle_operation(self, resources):
            if (
                self.path not in ("/preview", "/execute")
                or self.headers.get("Host") != host
                or self.headers.get("Origin") != url
                or self.headers.get("X-Setup-Token") != token
            ):
                return self.respond(403, b"Invalid request")
            execute = self.path == "/execute"
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1576960:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an operation")
                if size > 16384 and payload.get("action") != "zed-edit":
                    raise ValueError("Invalid request size")
                if payload.get("action") in ("chat-preview-start", "chat-preview-stop"):
                    if not execute or payload.get("confirmed") is not True:
                        raise ValueError(
                            "Confirm starting or stopping the local preview"
                        )
                    port = payload.get("port", 3001)
                    if (
                        type(port) is not int
                        or not 1024 <= port <= 65535
                        or port == 8080
                    ):
                        raise ValueError(
                            "Choose a port between 1024 and 65535 other than 8080"
                        )
                    if not previews.acquire(blocking=False):
                        return self.respond(409, b"An operation is already running")
                    resources.callback(previews.release)
                    with chat_lock:
                        if payload["action"] == "chat-preview-start":
                            if (
                                BackgroundServer(root / "chatgpt-lite")
                                .status()
                                .get("background_running")
                            ):
                                raise ValueError(
                                    "Stop the background service before starting a dashboard preview."
                                )
                            chat_preview.start(port)
                        else:
                            chat_preview.stop()
                    result = {
                        "running": chat_preview.running(),
                        "preview_port": chat_preview.port,
                    }
                    return self.respond(
                        200, json.dumps(result).encode(), "application/json"
                    )
                if payload.get("action") == "remote-ai":
                    from remote_ai import probe

                    operation = payload.get("operation", "detect")
                    allowed = (
                        ("start", "stop", "restart", "test-model")
                        if execute
                        else (
                            "detect",
                            "plan",
                            "models",
                            "status",
                            "verify",
                            "port-check",
                            "runtime-context",
                            "context",
                        )
                    )
                    if operation not in allowed or (
                        execute and payload.get("confirmed") is not True
                    ):
                        raise ValueError("Choose and confirm a supported remote action")
                    if not previews.acquire(blocking=False):
                        return self.respond(409, b"An operation is already running")
                    resources.callback(previews.release)
                    result = probe(
                        payload.get("host"),
                        payload.get("user"),
                        payload.get("directory"),
                        operation,
                        payload.get("data_root")
                        if operation in ("plan", "models")
                        else None,
                        port=payload.get("port"),
                        context_tokens=payload.get("context_tokens"),
                    )
                    if execute:
                        return self.respond(
                            200,
                            json.dumps(result).encode() + b"\n",
                            "application/x-ndjson",
                        )
                    return self.respond(
                        200, json.dumps(result).encode(), "application/json"
                    )
                if payload.get("action") == "zed-edit":
                    mode, profile = payload.get("mode"), payload.get("profile")
                    if mode not in ("apply", "override", "replace") or not isinstance(
                        profile, str
                    ):
                        raise ValueError("Choose a Zed mode and paste a JSONC object")
                    if len(profile.encode("utf-8")) > 256 * 1024:
                        raise ValueError("Zed profile exceeds the 256 KiB limit")
                    if execute and payload.get("confirmed") is not True:
                        raise ValueError("Confirm the reviewed Zed changes")
                    workspace = Path(
                        resources.enter_context(
                            tempfile.TemporaryDirectory(prefix="automation-zed-")
                        )
                    )
                    target = workspace / "settings.json"
                    descriptor = os.open(
                        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        stream.write(profile)
                    args = [
                        "zed",
                        mode,
                        str(target),
                        "--yes" if execute else "--dry-run",
                    ]
                    if execute:
                        version = payload.get("version")
                        if not isinstance(version, str) or not re.fullmatch(
                            r"(?:missing|[a-f0-9]{64})", version
                        ):
                            raise ValueError(
                                "Preview the settings changes before applying"
                            )
                        args.extend(["--current-sha256", version])
                    steps = [("zed-edit", args)] if execute else []
                else:
                    steps = (
                        operation_steps(payload, aur_ready=aur_ready) if execute else []
                    )
                    args = (
                        []
                        if execute
                        else preview_arguments(payload, aur_ready=aur_ready)
                    )
            except (ValueError, UnicodeError, KeyError, TypeError, OSError) as error:
                return self.respond(400, str(error).encode())
            if (
                execute
                and not state["terminal"]
                and payload.get("action") not in ("checklist-mark", "backup-run")
                and not payload["action"].startswith(("webui-", "chat-background-"))
            ):
                return self.respond(
                    409,
                    b"Launch the dashboard from an interactive terminal to apply changes.",
                )
            # System home probes may be in flight when a different tab opens.
            locked = execute or (
                args[:2] != ["packages", "status"]
                and payload["action"]
                not in (
                    "ai-eligibility",
                    "ai-engines",
                    "system-details",
                    "backup-browse",
                )
            )
            if locked and not previews.acquire(blocking=False):
                return self.respond(409, b"An operation is already running")
            try:
                if execute:
                    if chat_preview.running() and any(
                        name in ("chat-build", "chat-remove", "chat-background-start")
                        for name, _ in steps
                    ):
                        return self.respond(
                            409,
                            b"Stop the ChatGPT Lite dashboard preview before starting another server or changing build output.",
                        )
                    if any(
                        args[0]
                        in ("packages", "ai", "system-telemetry", "system-cleanup")
                        and args[1] != "mapping"
                        for _, args in steps
                    ):
                        sudo = shutil.which("sudo")
                        if sudo:
                            stop = threading.Event()
                            keeper = threading.Thread(
                                target=refresh_sudo, args=(stop, sudo), daemon=True
                            )
                            keeper.start()
                            try:
                                return self.execute(steps)
                            finally:
                                stop.set()
                                keeper.join()
                    return self.execute(steps)
                if args[:2] == ["chat-lite", "status"]:
                    port = int(args[-1]) if "--port" in args else 3001
                    details = chat_status(root / "chatgpt-lite", port)
                    details["running"] = chat_preview.running()
                    details["preview_port"] = (
                        chat_preview.port if details["running"] else None
                    )
                    details["preview_ready"] = details["running"] and chat_ready(
                        chat_preview.port
                    )
                    response = {"status": 0, "output": json.dumps(details)}
                    return self.respond(
                        200, json.dumps(response).encode(), "application/json"
                    )
                result = subprocess.run(
                    ["bash", str(root / "setup.sh"), *args],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                    check=False,
                )
                response = {
                    "status": result.returncode,
                    "output": result.stdout.decode("utf-8", errors="replace"),
                }
                if locked:
                    previews.release()
                    locked = False
                self.respond(200, json.dumps(response).encode(), "application/json")
            except subprocess.TimeoutExpired:
                self.respond(
                    504, b"Preview timed out. Try a smaller package selection."
                )
            except OSError:
                self.respond(500, b"Could not run the preview")
            finally:
                if locked:
                    previews.release()

        def execute(self, steps):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            connected = True
            try:
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                connected = False

            def emit(event):
                nonlocal connected
                if connected:
                    try:
                        self.wfile.write(json.dumps(event).encode() + b"\n")
                        self.wfile.flush()
                    except OSError:
                        connected = False

            message = (
                "Dashboard local operation started."
                if all(
                    name == "backup-run"
                    or name.startswith(("webui-", "chat-background-"))
                    for name, _ in steps
                )
                else "Dashboard operation started. Use this terminal for sudo authentication and AUR recipe review."
            )
            print(message, flush=True)
            for name, _ in steps:
                emit({"step": name, "state": "pending"})
            status = 0
            for name, args in steps:
                emit({"step": name, "state": "running"})
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                try:
                    with subprocess.Popen(
                        ["bash", str(root / "setup.sh"), *args],
                        cwd=root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env={
                            **os.environ,
                            "PYTHONUNBUFFERED": "1",
                            "AUTOMATION_DASHBOARD_TTY": "1",
                        },
                    ) as process:
                        pending = ""
                        for chunk in iter(lambda: process.stdout.read1(4096), b""):
                            message = decoder.decode(chunk)
                            print(message, end="", flush=True)
                            emit({"output": message})
                            lines = (pending + message).split("\n")
                            pending = lines.pop()[-4096:]
                            for line in lines:
                                event = package_event(line)
                                if event and (
                                    "authentication" in event
                                    or args[:2]
                                    in (["packages", "install"], ["packages", "repair"])
                                ):
                                    emit(event)
                        emit({"output": decoder.decode(b"", final=True)})
                        status = process.wait()
                except OSError as error:
                    emit({"output": str(error)})
                    status = 127
                emit({"step": name, "state": "failed" if status else "completed"})
                if status:
                    break
            emit({"status": status})

        def log_message(self, *args):
            pass

    # A stable loopback origin keeps this dashboard's local draft across restarts.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 38175), Handler)
    except OSError as error:
        print(f"Cannot open the dashboard on 127.0.0.1:38175: {error}", file=sys.stderr)
        return 3
    with server:
        host = f"127.0.0.1:{server.server_port}"
        url = f"http://{host}"
        print(f"Setup dashboard: {url} (Ctrl+C to close)", flush=True)
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

        def stop_on_signal(_number, _frame):
            raise KeyboardInterrupt

        previous = None
        if threading.current_thread() is threading.main_thread():
            previous = signal.signal(signal.SIGTERM, stop_on_signal)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
            with chat_lock:
                chat_preview.stop()
