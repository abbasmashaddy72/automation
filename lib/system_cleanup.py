"""Review system cleanup candidates using distribution-native tooling."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def inspect_command(argv):
    if not shutil.which(argv[0]):
        return None
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (
        result.stdout.strip()
        if result.returncode == 0 or (argv[0] == "pacman" and result.returncode == 1)
        else None
    )


def cache_entries(family, output):
    entries = []
    for line in (output or "").splitlines():
        if family == "arch":
            path = Path(line)
            if not path.is_absolute() or ".pkg.tar." not in path.name:
                continue
            try:
                if path.is_file() and not path.is_symlink():
                    entries.append({"path": str(path), "bytes": path.stat().st_size})
            except OSError:
                continue
        elif family == "debian":
            record = re.fullmatch(r"Del (\S+) (\S+) \[([0-9.]+) (B|kB|MB|GB)\]", line)
            if record:
                name, version, size, unit = record.groups()
                entries.append(
                    {
                        "package": name,
                        "version": version,
                        "bytes": round(
                            float(size) * 1000 ** ("B", "kB", "MB", "GB").index(unit)
                        ),
                    }
                )
    return entries


def main(args, approve, info):
    family = info["family"]
    action = args.action or "plan"
    if action == "updates":
        commands = {
            "arch": ["pacman", "-Qu"],
            "debian": ["apt", "list", "--upgradable"],
            "fedora": ["dnf", "--cacheonly", "repoquery", "--upgrades"],
            "rhel": ["dnf", "--cacheonly", "repoquery", "--upgrades"],
            "opensuse": ["zypper", "--non-interactive", "--no-refresh", "list-updates"],
            "alpine": ["apk", "version", "-l", "<"],
        }
        command = commands.get(family)
        result = inspect_command(command) if command else None
        print(
            result
            or (
                "No updates listed in current metadata."
                if result == ""
                else "Update information unavailable."
            )
        )
        return 0 if result is not None else 3
    cache = {
        "arch": (
            ["paccache", "-d", "-vv", "-k", "3"],
            ["paccache", "-r", "-k", "3"],
        ),
        "debian": (
            ["apt-get", "-s", "autoclean"],
            ["apt-get", "autoclean"],
        ),
    }.get(family)
    if action not in ("plan", "cache") or args.value:
        raise ValueError("system-cleanup plan|cache|updates")
    orphans = {
        "arch": ["pacman", "-Qdtq"],
        "debian": ["apt-get", "-s", "autoremove"],
        "fedora": ["dnf", "--cacheonly", "repoquery", "--unneeded"],
        "rhel": ["dnf", "--cacheonly", "repoquery", "--unneeded"],
    }.get(family)
    candidates = inspect_command(cache[0]) if cache else None
    estimates = cache_entries(family, candidates)
    print(
        json.dumps(
            {
                "distribution": info["id"],
                "cache_preview": candidates,
                "cache_cleanup_supported": bool(estimates)
                and not info.get("immutable")
                and not info.get("wsl"),
                "cache_entries": estimates[:150],
                "cache_total_bytes": sum(item["bytes"] for item in estimates),
                "listed_cache_entries": min(len(estimates), 150),
                "cache_estimate": "Estimated space from native dry-run candidates; the package manager rechecks at execution.",
                "unused_packages_review": inspect_command(orphans) if orphans else None,
                "journal_usage": inspect_command(["journalctl", "--disk-usage"]),
                "temporary_files_and_logs": "Inspection only. Use the distribution retention policy for active logs and temporary files.",
            },
            indent=2,
        )
    )
    if action == "plan" or args.dry_run:
        return 0
    if info.get("immutable") or info.get("wsl") or not cache or candidates is None:
        raise ValueError("Native cache cleanup is unavailable on this system")
    if not estimates:
        return 0
    if not approve(args, "Clean obsolete package-manager archives?"):
        return 4
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    if (
        prefix
        and subprocess.run(
            ["sudo", "-n", "-v"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
    ):
        print("Dashboard authentication: pending", flush=True)
        if subprocess.run(["sudo", "-v"], check=False).returncode:
            print("Dashboard authentication: failed", flush=True)
            return 4
        print("Dashboard authentication: complete", flush=True)
    return subprocess.run([*prefix, *cache[1]], check=False).returncode
