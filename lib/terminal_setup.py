"""Login shell inspection and optional interactive Terminal AI wiring."""

import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess

DEVELOPMENT_COMMANDS = ("artisan", "vbin", "pint", "sail", "fixer", "pest", "phpunit")
CLEANUP_COMMANDS = ("clean-npm", "clean-composer")
AI_COMMANDS = ("ai-ask", "ai-suggest")


def shell_commands(shell):
    return (
        DEVELOPMENT_COMMANDS
        + (CLEANUP_COMMANDS if shell in ("fish", "zsh") else ())
        + AI_COMMANDS
    )


def validate_commands(names, shell):
    allowed = shell_commands(shell)
    if not isinstance(names, (list, tuple)) or any(
        not isinstance(name, str) or name not in allowed for name in names
    ):
        raise ValueError("Choose supported commands for the selected shell")
    if len(names) != len(set(names)):
        raise ValueError("Select each shell command only once")
    return [name for name in allowed if name in names]


def login_shells():
    path = Path("/etc/shells")
    if not path.is_file():
        return []
    paths = (
        Path(line.partition("#")[0].strip()) for line in path.read_text().splitlines()
    )
    return [
        str(shell)
        for shell in paths
        if shell.is_absolute() and shell.is_file() and os.access(shell, os.X_OK)
    ]


def integration_options(block):
    """Read compact settings and preserve support for older inline blocks."""
    source = next(
        (
            line.strip()
            for line in block.replace("\\\n", " ").splitlines()
            if line.strip().startswith("source ")
        ),
        "",
    )
    options = []
    if source:
        words = shlex.split(source)
        if len(words) >= 3 and Path(words[1]).name in ("startup.sh", "startup.fish"):
            options = words[3:]
    banner = next(
        (name for name in ("fastfetch", "neofetch") if f"; {name};" in block), "none"
    )
    if "--banner" in options:
        choice = options[options.index("--banner") + 1 :][:1]
        if choice and choice[0] in ("fastfetch", "neofetch"):
            banner = choice[0]
    selected = (
        options[options.index("--commands") + 1 :][:1]
        if "--commands" in options
        else []
    )
    terminal_ai = (
        "--terminal-ai" in options
        or "automation_ai()" in block
        or "function automation_ai" in block
    )
    cleanup = "--project-cleanup-aliases" in options
    if selected:
        commands = [] if selected[0] == "none" else selected[0].split(",")
    elif block.strip():
        commands = [
            *DEVELOPMENT_COMMANDS,
            *(CLEANUP_COMMANDS if cleanup else ()),
            *(AI_COMMANDS if terminal_ai else ()),
        ]
    else:
        commands = []
    return {
        "banner": banner,
        "terminal_ai": terminal_ai,
        "fish_greeting": "off"
        if "--hide-greeting" in options or 'set -g fish_greeting ""' in block
        else "keep",
        "use_toolkit_agent": "--use-toolkit-agent" in options
        or "automation-ssh-agent/agent.sock" in block,
        "project_cleanup_aliases": cleanup,
        "commands": commands,
    }


def status(developer):
    import shell_migration

    account = pwd.getpwuid(os.getuid())
    allowed = login_shells()
    shells = {}
    for name in developer.SHELLS:
        record = {
            "installed": bool(shutil.which(name)),
            "login_allowed": any(Path(p).name == name for p in allowed),
        }
        try:
            path = developer.target(name)
            data = path.read_bytes() if path.is_file() else b""
            text = data.decode("utf-8")
            block = text.partition(developer.BEGIN)[2].partition(developer.END)[0]
            personal = (
                text.replace(developer.BEGIN + block + developer.END, "")
                if block
                else text
            )
            record.update(
                path=str(path),
                configured=bool(block),
                sha256=developer.sha(data),
                **integration_options(block),
                personal_commands=[
                    command
                    for command in (*DEVELOPMENT_COMMANDS, *CLEANUP_COMMANDS)
                    if re.search(
                        r"^[ \t]*(?:(?:alias|function)[ \t]+"
                        + re.escape(command)
                        + r"(?:[= \t(]|$)|"
                        + re.escape(command)
                        + r"[ \t]*\(\))",
                        personal,
                        re.M,
                    )
                ],
            )
            try:
                record["legacy_blocks"] = shell_migration.migrate(text, name) != text
            except ValueError as error:
                record["legacy_review"] = str(error)
        except (OSError, ValueError) as error:
            record["error"] = str(error)
        shells[name] = record
    print(json.dumps({"default_shell": account.pw_shell, "shells": shells}))
    return 0


def set_default(args, approve, names):
    path = next((p for p in login_shells() if Path(p).name == args.shell), None)
    chsh = shutil.which("chsh", path=os.defpath)
    if args.shell not in names or not path or not chsh or os.getuid() == 0:
        raise ValueError(
            "Choose an installed shell from /etc/shells and run as a regular user with chsh available"
        )
    previous = pwd.getpwuid(os.getuid()).pw_shell
    if Path(previous).name == args.shell:
        print("This shell is already the account default.")
        return 0
    print(f"Account login shell: {previous} → {path}. Applies to new login sessions.")
    if args.dry_run:
        return 0
    if not approve(args, "Change your account's login shell?"):
        return 4
    if os.environ.get("AUTOMATION_DASHBOARD_TTY") == "1":
        print("Dashboard authentication: pending", flush=True)
    with open("/dev/tty", "rb") as terminal:
        result = subprocess.run([chsh, "-s", path], stdin=terminal, timeout=180)
    if result.returncode or pwd.getpwuid(os.getuid()).pw_shell != path:
        print("Dashboard authentication: failed", flush=True)
        raise ValueError("The login shell change could not be verified")
    print("Dashboard authentication: complete", flush=True)
    print("Login shell saved:", path)
    return 0
