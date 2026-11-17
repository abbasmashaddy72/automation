"""Debian Popularity Contest controls for the documented local configuration."""

from pathlib import Path
import json
import os
import re
import subprocess
import tempfile


def main(args, approve, info):
    operation = args.action or "status"
    if operation not in ("status", "disable", "restore") or args.value:
        raise ValueError("system-telemetry status|disable|restore")
    active = Path("/etc/cron.daily/popularity-contest")
    folder = Path("/etc/popularity-contest.d")
    target = folder / "zz-automation-toolkit.conf"
    content = b'# Managed by Automation Toolkit\nPARTICIPATE="no"\n'
    if info["id"] not in ("debian", "ubuntu") or not active.is_file():
        print(
            json.dumps(
                {
                    "status": "unsupported or absent",
                    "adapter": "Debian Popularity Contest",
                }
            )
        )
        return 0 if operation == "status" or args.dry_run else 3
    if folder.is_symlink() or target.is_symlink():
        raise ValueError("Unexpected telemetry configuration symlink")
    configured = "no"
    managed = False
    paths = [
        Path("/usr/share/popularity-contest/default.conf"),
        Path("/etc/popularity-contest.conf"),
        *sorted(folder.glob("*.conf")),
    ]
    for path in paths:
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Unsupported telemetry configuration file")
        data = path.read_bytes()
        if path == target:
            managed = data == content
            if not managed:
                raise ValueError(
                    "Existing telemetry override is owned outside the toolkit"
                )
        for line in data.decode().splitlines():
            if re.match(r"^\s*PARTICIPATE\s*=", line):
                match = re.fullmatch(
                    r"""\s*PARTICIPATE=(?:"(yes|no)"|'(yes|no)'|(yes|no))\s*(?:#.*)?""",
                    line,
                )
                configured = (
                    next((v for v in match.groups() if v), "unknown")
                    if match
                    else "unknown"
                )
    print(
        json.dumps(
            {
                "adapter": "Debian Popularity Contest",
                "participate": configured,
                "managed_override": managed,
                "path": str(target),
                "change": "Add an opt-out drop-in or remove the exact toolkit-owned drop-in",
            }
        )
    )
    if operation == "status" or args.dry_run:
        return 0
    if operation == "disable" and (configured == "no" or managed):
        return 0 if configured == "no" else 3
    if operation == "restore" and not managed:
        return 0
    if operation == "disable" and (
        configured == "unknown" or any(path.name > target.name for path in paths[2:])
    ):
        raise ValueError(
            "Review existing telemetry overrides before applying the toolkit opt-out"
        )
    if not approve(
        args, f"{operation.capitalize()} the listed Popularity Contest override?"
    ):
        return 4
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    if operation == "restore":
        if (
            not target.is_file()
            or target.is_symlink()
            or target.read_bytes() != content
        ):
            raise ValueError("Telemetry override changed during review")
        return subprocess.run([*prefix, "unlink", str(target)], check=False).returncode
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / target.name
        source.write_bytes(content)
        stage = folder / (".automation-" + Path(temporary).name)
        for command in (
            ["install", "-d", "-m", "0755", str(folder)],
            ["install", "-m", "0644", str(source), str(stage)],
        ):
            status = subprocess.run([*prefix, *command], check=False).returncode
            if status:
                return status
        try:
            return subprocess.run(
                [*prefix, "ln", "-T", str(stage), str(target)], check=False
            ).returncode
        finally:
            subprocess.run([*prefix, "unlink", str(stage)], check=False)
