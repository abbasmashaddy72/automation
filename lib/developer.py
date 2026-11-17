"""User-only Git identity and shell integration, with private conflict-safe backups."""

from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
import journal

BEGIN = "# BEGIN AUTOMATION TOOLKIT"
END = "# END AUTOMATION TOOLKIT"
SHELLS = ("bash", "zsh", "fish")
SHELL_HELPERS = Path(__file__).resolve().parent / "shell"
MAX_CONFIG_BYTES = 1048576


def shell_helper(shell):
    return SHELL_HELPERS / ("startup.fish" if shell == "fish" else "startup.sh")


def shell_quote(value, shell):
    return shlex.quote(value.replace("\\", "\\\\") if shell == "fish" else value)


def target(kind):
    home = Path.home()
    paths = {
        "git": home / ".gitconfig",
        "bash": home / ".bashrc",
        "zsh": home / ".zshrc",
        "fish": Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        / "fish/config.fish",
        "ssh": home / ".ssh/automation-toolkit.conf",
        "ssh-agent": Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        / "systemd/user/automation-ssh-agent.service",
    }
    if kind not in paths:
        raise ValueError("Unknown developer configuration kind")
    path = paths[kind]
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink developer configuration paths are forbidden")
    if path.exists() and (
        not path.is_file()
        or path.stat().st_uid != os.getuid()
        or path.stat().st_nlink != 1
        or path.stat().st_size > MAX_CONFIG_BYTES
    ):
        raise ValueError(
            "Developer configuration must be an owned, bounded, regular file"
        )
    return path


def show_shell(shell):
    if shell not in SHELLS:
        raise ValueError("Choose Bash, Fish or Zsh")
    path = target(shell)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        print(json.dumps({"path": str(path), "exists": False, "content": ""}))
        return 0
    with os.fdopen(fd, "rb") as stream:
        identity = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(identity.st_mode)
            or identity.st_uid != os.getuid()
            or identity.st_nlink != 1
            or identity.st_size > MAX_CONFIG_BYTES
        ):
            raise ValueError("Choose an owned, regular shell configuration up to 1 MiB")
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError("Shell configuration exceeded the 1 MiB preview limit")
    print(
        json.dumps({"path": str(path), "exists": True, "content": data.decode("utf-8")})
    )
    return 0


def shell_content(
    original,
    shell,
    banner="none",
    *,
    use_agent=False,
    greeting="keep",
    migrate=False,
    terminal_ai=False,
    project_cleanup_aliases=False,
    commands=None,
):
    if shell not in SHELLS:
        raise ValueError("Choose bash, zsh or fish")
    text = original.decode("utf-8")
    if migrate:
        import shell_migration

        text = shell_migration.migrate(text, shell)
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError("Ambiguous existing managed shell blocks; review manually")
    if banner not in ("none", "fastfetch", "neofetch"):
        raise ValueError("Unknown shell banner")
    if greeting not in ("keep", "off") or greeting == "off" and shell != "fish":
        raise ValueError("Fish greeting control applies only to fish")
    helper = shell_quote(str(shell_helper(shell)), shell)
    options = []
    if banner != "none":
        options.append("--banner " + banner)
    if greeting == "off":
        options.append("--hide-greeting")
    if use_agent:
        options.append("--use-toolkit-agent")
    if project_cleanup_aliases:
        if shell == "bash":
            raise ValueError("Project cleanup aliases are available for Fish and Zsh")
        options.append("--project-cleanup-aliases")
    if commands is not None:
        from terminal_setup import AI_COMMANDS, validate_commands

        if terminal_ai or project_cleanup_aliases:
            raise ValueError(
                "Use either individual shell commands or the legacy group options"
            )
        chosen = validate_commands(commands, shell)
        options.append("--commands " + (",".join(chosen) or "none"))
        terminal_ai = any(name in AI_COMMANDS for name in chosen)
    if terminal_ai:
        setup = str(SHELL_HELPERS.parent.parent / "setup.sh")
        options.append("--terminal-ai " + shell_quote(setup, shell))
    source = " \\\n        ".join([f"    source {helper} {shell}", *options])
    opener = (
        f"if test -r {helper}" if shell == "fish" else f"if [[ -r {helper} ]]; then"
    )
    closer = "end" if shell == "fish" else "fi"
    content = f"{opener}\n{source}\n{closer}\n"
    block = BEGIN + "\n" + content + END
    if BEGIN in text:
        if text.index(END) < text.index(BEGIN):
            raise ValueError("Invalid shell marker order")
        return re.sub(
            re.escape(BEGIN) + r".*?" + re.escape(END),
            lambda _: block,
            text,
            flags=re.S,
        ).encode()
    return (
        text + ("" if not text or text.endswith("\n") else "\n") + block + "\n"
    ).encode()


def validate_identity(name, email):
    if not name or not 1 <= len(name) <= 120 or any(ord(c) < 32 for c in name):
        raise ValueError("Provide a literal Git display name")
    if not email or len(email) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+", email):
        raise ValueError("Provide a valid Git email address")


def identity(original, name, email):
    validate_identity(name, email)
    if not shutil.which("git"):
        raise ValueError(
            "Git is required; install it with packages install --select git"
        )
    with tempfile.TemporaryDirectory(prefix="automation-git-config-") as td:
        path = Path(td) / "gitconfig"
        path.write_bytes(original)
        path.chmod(0o600)
        for key, value in [("user.name", name), ("user.email", email)]:
            cp = subprocess.run(
                ["git", "config", "--file", str(path), "--replace-all", key, value],
                capture_output=True,
                timeout=10,
            )
            if cp.returncode:
                raise ValueError(
                    "Existing Git configuration is invalid; no file changed"
                )
        return path.read_bytes()


def transport(original, choice):
    if choice not in ("ssh", "https"):
        raise ValueError("Choose --transport ssh or https for the exact GitHub prefix")
    if not shutil.which("git"):
        raise ValueError("Git is required")
    with tempfile.TemporaryDirectory(prefix="automation-git-transport-") as directory:
        path = Path(directory) / "gitconfig"
        path.write_bytes(original)
        path.chmod(0o600)
        command = ["git", "config", "--no-includes", "--file", str(path)]
        query = subprocess.run(
            [
                *command,
                "--get-regexp",
                r"^url\..*\.insteadof$",
                r"^https://github\.com/$",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if query.returncode not in (0, 1):
            raise ValueError("Invalid Git configuration; nothing changed")
        key = "url.git@github.com:.insteadof"
        if choice == "ssh" and any(
            line.split(" ", 1)[0] != key for line in query.stdout.splitlines()
        ):
            raise ValueError(
                "A different GitHub transport rewrite already exists; review it manually before adding another"
            )
        args = (
            ["--replace-all", key, "https://github.com/", r"^https://github\.com/$"]
            if choice == "ssh"
            else ["--unset-all", key, r"^https://github\.com/$"]
        )
        result = subprocess.run([*command, *args], capture_output=True, timeout=10)
        if result.returncode and not (
            choice == "https" and result.returncode in (1, 5)
        ):
            raise ValueError("Git transport configuration failed; nothing changed")
        return path.read_bytes()


def replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, stage = tempfile.mkstemp(prefix=".developer-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_backup(kind, before, after, existed, state=""):
    folder = journal.state_dir(state) / "developer"
    if folder.is_symlink():
        raise ValueError("Symlink developer backup directory")
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
        raise ValueError("Developer backups must be private and owned")
    filename = uuid.uuid4().hex + ".json"
    record = {
        "schema": 1,
        "kind": kind,
        "before": base64.b64encode(before).decode(),
        "before_sha256": sha(before),
        "after_sha256": sha(after),
        "existed": existed,
    }
    replace(folder / filename, (json.dumps(record, indent=2) + "\n").encode())
    return filename


def main(args, approve):
    action = args.action or "status"
    if action == "shell-show":
        return show_shell(args.shell)
    if action in ("shell-status", "shell-default"):
        import terminal_setup
        import sys

        if action == "shell-status":
            return terminal_setup.status(sys.modules[__name__])
        return terminal_setup.set_default(args, approve, SHELLS)
    if action == "ssh-agent":
        import ssh_agent

        return ssh_agent.main(args, approve)
    if action == "import-shell-backup":
        import shell_migration

        return shell_migration.import_backup(args, approve)
    if action in (
        "ssh",
        "ssh-generate",
        "ssh-add",
        "ssh-status",
        "ssh-copy",
        "ssh-test",
        "clone",
        "import-git-backup",
    ):
        import ssh_ops

        return ssh_ops.main(args, approve)
    if action == "status":
        print(
            json.dumps(
                {
                    "git": bool(shutil.which("git")),
                    "shells": {k: bool(shutil.which(k)) for k in SHELLS},
                    "note": "No keys, Git configuration values or shell files were read",
                },
                indent=2,
            )
        )
        return 0
    if action == "restore":
        if not args.value or not re.fullmatch("[a-f0-9]{32}\\.json", args.value):
            raise ValueError("Select an exact developer backup filename")
        folder = (
            journal.state_dir(getattr(args, "developer_state", ""), create=False)
            / "developer"
        )
        backup = folder / args.value
        if (
            any(p.is_symlink() for p in (backup, *backup.parents))
            or not backup.is_file()
            or backup.stat().st_size > 3 * 1048576
            or backup.stat().st_mode & 0o077
            or backup.stat().st_uid != os.getuid()
        ):
            raise ValueError("Unsafe developer backup")
        record = json.loads(backup.read_text())
        if (
            not isinstance(record, dict)
            or record.get("schema") != 1
            or type(record.get("existed")) is not bool
        ):
            raise ValueError("Invalid developer backup schema")
        path = target(record["kind"])
        current = path.read_bytes() if path.exists() else b""
        if sha(current) != record.get("after_sha256"):
            raise ValueError(
                "Developer configuration changed since apply; restore refused"
            )
        before = base64.b64decode(record["before"], validate=True)
        if sha(before) != record.get("before_sha256"):
            raise ValueError("Corrupt developer backup")
        if record["kind"] in SHELLS:
            import shell_migration

            shell_migration.check_syntax(before, record["kind"])
        if args.dry_run:
            print("Dry run: would restore", path.name)
            return 0
        if record["kind"] == "ssh-agent":
            import ssh_agent

            ssh_agent.require_editable()
        if not approve(
            args, "Restore developer configuration from its verified private backup?"
        ):
            return 4
        path = target(record["kind"])
        if sha(path.read_bytes() if path.exists() else b"") != record.get(
            "after_sha256"
        ):
            raise ValueError(
                "Configuration changed during restore review; refusing overwrite"
            )
        if record["kind"] == "ssh-agent":
            ssh_agent.require_editable()
        if record["existed"]:
            replace(path, before)
        else:
            path.unlink()
        print("Restored:", path.name)
        if record["kind"] == "ssh-agent":
            print(
                "Reload the reviewed unit state explicitly with developer ssh-agent reload --yes. No agent was started."
            )
        return 0
    if action not in ("git", "git-transport", "shell"):
        raise ValueError(
            "developer status|git|git-transport|shell|shell-status|shell-show|shell-default|ssh|ssh-agent|ssh-generate|ssh-add|import-git-backup|import-shell-backup|restore BACKUP.json"
        )
    if action == "shell" and args.shell not in SHELLS:
        raise ValueError("developer shell requires --shell bash, zsh or fish")
    kind = "git" if action in ("git", "git-transport") else args.shell
    path = target(kind)
    existed = path.exists()
    before = path.read_bytes() if existed else b""
    if kind == "git":
        if action == "git":
            validate_identity(args.name, args.email)
        elif getattr(args, "transport", None) not in ("ssh", "https"):
            raise ValueError("git-transport requires --transport ssh or https")
        if not shutil.which("git"):
            if args.dry_run:
                print(
                    "Dry run: Git prerequisite would be checked/installed before the reviewed identity change."
                )
                return 0
            if not approve(
                args,
                "Install the missing Git prerequisite from configured native repositories?",
            ):
                return 4
            root = Path(__file__).resolve().parents[1]
            cp = subprocess.run(
                [
                    "bash",
                    str(root / "scripts/prerequisites.sh"),
                    "install",
                    "--runtime-only",
                    "--with-git",
                    "--without-ui",
                    "--yes",
                ],
                timeout=900,
            )
            if cp.returncode:
                return cp.returncode
    if action == "git":
        after = identity(before, args.name, args.email)
    elif action == "git-transport":
        after = transport(before, args.transport)
    else:
        reviewed = getattr(args, "current_sha256", None)
        if not args.dry_run and reviewed and reviewed != sha(before):
            raise ValueError(
                "Shell configuration changed since review; preview it again"
            )
        if getattr(args, "migrate_legacy", False):
            import shell_migration

            migrated = shell_migration.migrate(before.decode("utf-8"), kind).encode()
            if migrated != before and getattr(args, "current_sha256", None) != sha(
                before
            ):
                raise ValueError(
                    "Legacy block migration requires the reviewed current file --current-sha256"
                )
        selected = getattr(args, "shell_commands", None)
        after = shell_content(
            before,
            kind,
            getattr(args, "banner", "none"),
            use_agent=getattr(args, "use_toolkit_agent", False),
            greeting=getattr(args, "fish_greeting", "keep"),
            migrate=getattr(args, "migrate_legacy", False),
            terminal_ai=getattr(args, "terminal_ai", False),
            project_cleanup_aliases=getattr(args, "project_cleanup_aliases", False),
            commands=None
            if selected is None
            else []
            if selected == "none"
            else selected.split(","),
        )
        import shell_migration

        shell_migration.check_syntax(shell_helper(kind).read_bytes(), kind)
        shell_migration.check_syntax(after, kind)
    if before == after:
        print("Developer configuration already matches.")
        return 0
    if args.dry_run:
        print(
            "Dry run: would update",
            path.name,
            "after private backup; no credentials or file contents shown.",
        )
        return 0
    if not approve(args, "Back up and update only " + path.name + "?"):
        return 4
    filename = save_backup(
        kind, before, after, existed, getattr(args, "developer_state", "")
    )
    if path.exists() != existed or path.exists() and path.read_bytes() != before:
        raise ValueError("Configuration changed during review; retry")
    replace(path, after)
    print("Updated:", path.name, "; private backup:", filename)
    print("Existing SSH keys, credentials, login shells and services are unchanged.")
    return 0
