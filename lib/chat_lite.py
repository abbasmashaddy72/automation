"""Optional local ChatGPT Lite client; never starts the inference engine."""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time


def port_in_use(port):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def node_runtime(root):
    candidates = dict.fromkeys(
        (shutil.which("node"), shutil.which("node", path=os.defpath))
    )
    for node in filter(None, candidates):
        try:
            details = json.loads(
                subprocess.check_output(
                    [node, "-p", "JSON.stringify([process.execPath, process.version])"],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=5,
                ).splitlines()[-1]
            )
            binary, version = details
            runtime = Path(binary)
            major = int(version.removeprefix("v").split(".")[0])
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, IndexError):
            continue
        if (
            major >= 22
            and runtime.is_absolute()
            and runtime.is_file()
            and os.access(runtime, os.X_OK)
        ):
            return str(runtime), version
    return None, None


def node_executable(root):
    runtime, _ = node_runtime(root)
    if not runtime:
        raise ValueError("Could not find a usable Node.js 22+ runtime.")
    return runtime


def server_environment(port):
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
    for key in ("VERCEL", "NODE_OPTIONS"):
        env.pop(key, None)
    env.update(HOSTNAME="127.0.0.1", PORT=str(port), NODE_ENV="production")
    return env


def ready(port):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        client.request("GET", "/chat")
        response = client.getresponse()
        return response.status == 200 and b"ChatGPT Lite" in response.read(128 * 1024)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        client.close()


class BackgroundServer:
    """A transient user service scoped to this checkout."""

    def __init__(self, root):
        self.root = root.resolve()
        identity = hashlib.sha256(os.fsencode(self.root)).hexdigest()[:24]
        self.unit = f"automation-chat-lite-{identity}.service"
        self.directory = self.root / ".next/standalone"
        self.description = f"Automation Toolkit ChatGPT Lite {identity} port "

    def command(self, program, *args):
        try:
            return subprocess.run(
                [program, "--user", *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(
                f"ChatGPT Lite service command failed: {program}"
            ) from error

    def inspect(self):
        result = self.command(
            "systemctl",
            "show",
            self.unit,
            "--property=LoadState,ActiveState,Transient,Description,WorkingDirectory",
        )
        props = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        if props.get("LoadState") == "not-found":
            return None
        if result.returncode or props.get("LoadState") != "loaded":
            raise ValueError(
                "A working systemd user manager is required for background mode."
            )
        description = props.get("Description", "")
        port = description[len(self.description) :]
        if (
            props.get("Transient") != "yes"
            or props.get("WorkingDirectory") != str(self.directory)
            or not description.startswith(self.description)
            or not port.isascii()
            or not port.isdecimal()
            or len(port) > 5
            or not 1024 <= int(port) <= 65535
            or int(port) == 8080
        ):
            raise ValueError(
                "The background service name is occupied by an unrecognized unit."
            )
        return int(port), props.get("ActiveState")

    def status(self):
        try:
            if not shutil.which("systemd-run"):
                raise ValueError(
                    "systemd-run is unavailable; use dashboard-session preview."
                )
            observed = self.inspect()
        except ValueError as error:
            return {"background_available": False, "background_detail": str(error)}
        if observed is None:
            return {"background_available": True, "background_running": False}
        port, state = observed
        return {
            "background_available": True,
            "background_running": True,
            "background_port": port,
            "background_state": state,
            "background_ready": state == "active" and ready(port),
        }

    def start(self, port):
        if self.inspect() is not None:
            raise ValueError(
                "Stop the existing background service before starting another."
            )
        if not (self.directory / "server.js").is_file():
            raise ValueError("Build ChatGPT Lite first using Node.js 22+.")
        node = node_executable(self.root)
        if port_in_use(port):
            raise ValueError(f"Port {port} is already in use. Choose another port.")
        result = self.command(
            "systemd-run",
            f"--unit={self.unit}",
            "--collect",
            f"--description={self.description}{port}",
            f"--working-directory={self.directory}",
            "--property=Type=exec",
            "--property=UnsetEnvironment=NODE_OPTIONS VERCEL LISTEN_FDS LISTEN_PID",
            "--setenv=HOSTNAME=127.0.0.1",
            f"--setenv=PORT={port}",
            "--setenv=NODE_ENV=production",
            "--setenv=NEXT_TELEMETRY_DISABLED=1",
            "--",
            node,
            "server.js",
        )
        if result.returncode:
            raise ValueError(
                "Could not start ChatGPT Lite in the systemd user manager."
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            observed = self.inspect()
            if observed is None:
                break
            if (
                observed == (port, "active")
                and ready(port)
                and self.inspect() == observed
            ):
                return
            time.sleep(0.15)
        self.stop()
        raise ValueError(
            f"ChatGPT Lite did not become ready. Check journalctl --user -u {self.unit}."
        )

    def stop(self):
        if (
            self.inspect() is not None
            and self.command("systemctl", "stop", self.unit).returncode
        ):
            raise ValueError("Could not stop the ChatGPT Lite background service.")


class PreviewServer:
    """One loopback preview, owned by the dashboard that launched it."""

    def __init__(self, root):
        self.root = root / ".next/standalone"
        self.process = None
        self.port = None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.running():
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        self.port = None

    def start(self, port):
        if self.running():
            if self.port == port:
                return
            raise ValueError("Stop the current preview before changing its port.")
        self.stop()
        if not (self.root / "server.js").is_file():
            raise ValueError("Build ChatGPT Lite first using Node.js 22+.")
        node = node_executable(self.root.parent.parent)
        if port_in_use(port):
            raise ValueError(f"Port {port} is already in use. Choose another port.")
        try:
            with tempfile.TemporaryFile() as log:
                self.process = subprocess.Popen(
                    [node, "server.js"],
                    cwd=self.root,
                    env=server_environment(port),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if not self.running():
                        break
                    if ready(port) and self.running():
                        self.port = port
                        return
                    time.sleep(0.15)
                log.seek(0)
                raise ValueError(
                    "ChatGPT Lite did not become ready. "
                    + log.read(4096).decode(errors="replace")
                )
        finally:
            if self.port is None:
                self.stop()


def status(root, port, action="status"):
    node, version = node_runtime(root)
    return {
        "node": bool(node),
        "node_supported": bool(node),
        "node_version": version,
        "npm": bool(shutil.which("npm")),
        "built": (root / ".next/standalone/server.js").is_file(),
        "port_in_use": port_in_use(port),
        "action": action,
        "url": f"http://127.0.0.1:{port}",
        "build_paths": [str(root / ".next"), str(root / "node_modules")],
        **BackgroundServer(root).status(),
    }


def main(argv, root):
    parser = argparse.ArgumentParser(prog="bash setup.sh chat-lite")
    parser.add_argument(
        "action",
        choices=("status", "build", "serve", "debug", "remove", "start", "stop"),
        nargs="?",
        default="status",
    )
    parser.add_argument("--port", type=int, default=3001)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or args.port == 8080:
        parser.error("Choose a client port from 1024 to 65535 other than 8080")
    url = f"http://127.0.0.1:{args.port}"
    built = (root / ".next/standalone/server.js").is_file()
    if args.action == "status" or args.dry_run:
        print(json.dumps(status(root, args.port, args.action)))
        return 0
    if not args.yes:
        print("Review the action and supply --yes.")
        return 4
    background = BackgroundServer(root)
    if args.action == "start":
        background.start(args.port)
        print("ChatGPT Lite background service ready at", url)
        return 0
    if args.action == "stop":
        background.stop()
        print("ChatGPT Lite background service stopped.")
        return 0
    if args.action in ("build", "remove") and background.status().get(
        "background_running"
    ):
        raise ValueError(
            "Stop the ChatGPT Lite background service before changing build output."
        )
    if args.action == "remove":
        output = root / ".next"
        if output.is_symlink() or (output.exists() and not output.is_dir()):
            raise ValueError("Unexpected ChatGPT Lite build directory")
        if output.exists():
            shutil.rmtree(output)
        print("ChatGPT Lite build output removed.")
        return 0
    node = node_executable(root)
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
    for key in ("VERCEL", "NODE_OPTIONS"):
        env.pop(key, None)
    if args.action == "debug":
        if not (root / "node_modules/next/dist/bin/next").is_file():
            raise ValueError(
                "Install locked dependencies first: bash setup.sh chat-lite build --yes"
            )
        env["AUTOMATION_CHAT_DEBUG"] = "1"
        print("ChatGPT Lite debug:", url, flush=True)
        return subprocess.run(
            [
                node,
                "node_modules/next/dist/bin/next",
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=root,
            env=env,
        ).returncode
    if args.action == "build":
        if not shutil.which("npm"):
            raise ValueError("ChatGPT Lite needs npm to install locked dependencies")
        for command in (
            ["npm", "ci", "--no-audit", "--no-fund"],
            ["npm", "run", "build"],
        ):
            try:
                result = subprocess.run(command, cwd=root, env=env, timeout=900)
            except subprocess.TimeoutExpired as exc:
                raise ValueError(
                    "ChatGPT Lite build timed out; rerun after checking npm/build output"
                ) from exc
            if result.returncode:
                return result.returncode
        output = root / ".next/standalone"
        for source, target in (
            (root / "public", output / "public"),
            (root / ".next/static", output / ".next/static"),
        ):
            shutil.copytree(source, target, dirs_exist_ok=True)
        return 0
    if not built:
        raise ValueError(
            "Build ChatGPT Lite first: bash setup.sh chat-lite build --yes"
        )
    if port_in_use(args.port):
        raise ValueError(f"Port {args.port} is already in use. Choose another port.")
    env = server_environment(args.port)
    print("ChatGPT Lite:", url, flush=True)
    return subprocess.run(
        [node, "server.js"], cwd=root / ".next/standalone", env=env
    ).returncode
