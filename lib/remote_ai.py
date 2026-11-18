"""Allowlisted SSH diagnostics and service actions through the remote toolkit."""

import re
import shlex
import subprocess


def probe(
    host,
    user,
    directory,
    operation="detect",
    data_root=None,
    *,
    port=None,
    context_tokens=None,
    packages=None,
    inspect_backend=None,
):
    if not isinstance(host, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}", host
    ):
        raise ValueError("Enter a hostname or IP address")
    if not isinstance(user, str) or not re.fullmatch(
        r"[a-zA-Z_][a-zA-Z0-9_-]{0,63}", user
    ):
        raise ValueError("Enter an SSH user")
    if not isinstance(directory, str) or not re.fullmatch(
        r"/[a-zA-Z0-9_.+/-]{1,512}", directory
    ):
        raise ValueError("Enter the absolute path to the remote toolkit")
    if data_root and (
        operation not in ("plan", "models")
        or not isinstance(data_root, str)
        or not data_root.startswith("/")
        or len(data_root) > 512
        or any(ord(character) < 32 for character in data_root)
    ):
        raise ValueError("Use an absolute model storage folder on the server")
    if port is not None and (
        operation not in ("verify", "port-check", "runtime-context", "inspect")
        or type(port) is not int
        or not 1 <= port <= 65535
    ):
        raise ValueError("Use a valid loopback port for API diagnostics")
    if operation == "context" and (
        type(context_tokens) is not int or not 256 <= context_tokens <= 131072
    ):
        raise ValueError("Choose a context size from 256 to 131072 tokens")
    if inspect_backend is not None and (
        operation != "inspect"
        or inspect_backend not in ("llamacpp", "ollama", "vllm", "jan")
    ):
        raise ValueError("Choose a supported backend to inspect")
    setup = directory.rstrip("/") + "/setup.sh"
    if operation == "detect":
        commands = [
            ["bash", setup, "--check"],
            ["bash", setup, "ai", "server", "hardware"],
            ["bash", setup, "ai", "server", "engines"],
        ]
    elif operation == "package-status":
        from discovery import validate_term

        if not isinstance(packages, list) or not 1 <= len(packages) <= 150:
            raise ValueError("Select 1–150 packages to inspect on the remote server")
        names = ",".join(dict.fromkeys(validate_term(name) for name in packages))
        commands = [["bash", setup, "packages", "status", "--select", names]]
    elif operation in (
        "key-status",
        "inspect",
        "plan",
        "models",
        "status",
        "verify",
        "port-check",
        "runtime-context",
        "context",
        "test-model",
        "start",
        "stop",
        "restart",
    ):
        commands = [
            [
                "bash",
                setup,
                "ai",
                "server",
                operation,
                *(["--data-root", data_root] if data_root else []),
                *(["--port", str(port)] if port is not None else []),
                *(["--inspect-backend", inspect_backend] if inspect_backend else []),
                *(
                    ["--context-tokens", str(context_tokens), "--dry-run"]
                    if operation == "context"
                    else []
                ),
                *(
                    ["--yes"]
                    if operation in ("start", "stop", "restart", "test-model")
                    else []
                ),
            ]
        ]
    else:
        raise ValueError("Unsupported remote AI operation")
    command = " && ".join(shlex.join(args) for args in commands)
    try:
        result = subprocess.run(
            [
                "ssh",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ForwardAgent=no",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ConnectTimeout=8",
                "-l",
                user,
                "--",
                host,
                command,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=85 if operation == "test-model" else 45,
            check=False,
        )
        output = result.stdout + result.stderr
        if len(output) > 65536:
            return {
                "status": 1,
                "output": "Remote response exceeded the dashboard limit. Run the command in the SSH terminal.",
            }
        if result.returncode and not output.strip():
            output = f"SSH operation {operation} exited with status {result.returncode} and returned no details."
        return {"status": result.returncode, "output": output}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": 1, "output": str(error)}
