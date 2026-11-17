"""Read-only repository-query cache, never an installed-state cache.

Cache entries are deliberately short-lived and scoped by source, distro,
architecture, query and current metadata stamp. No package-manager mutation
and no insecure reliance on cached installation outcomes.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time

TTL = 600
PERSIST = False  # CLI enables disk writes only for approved mutating workflows.


def directory():
    base = Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    ).expanduser()
    return base / "automation-toolkit" / "repository-metadata"


def _key(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def get(parts, *, ttl=TTL, folder=None):
    folder = Path(folder) if folder is not None else directory()
    path = folder / (_key(parts) + ".json")
    if path.is_symlink():
        return None
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        data = json.loads(path.read_text())
        return data["value"] if data.get("key") == parts else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def put(parts, value, *, folder=None):
    if folder is None and not PERSIST:
        return False
    folder = Path(folder) if folder is not None else directory()
    if folder.is_symlink():
        return False
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        path = folder / (_key(parts) + ".json")
        if path.is_symlink():
            return False
        temp = path.with_suffix(".tmp-" + str(os.getpid()))
        with temp.open("x") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump({"key": parts, "value": value}, f)
        os.replace(temp, path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def clear(*, folder=None):
    folder = Path(folder) if folder is not None else directory()
    if folder.is_symlink() or not folder.is_dir():
        return 0
    count = 0
    for path in folder.glob("*.json"):
        if not path.is_symlink():
            path.unlink()
            count += 1
    return count


def expired():
    """List only expired regular entries produced by this repository cache."""
    import re
    import stat
    import filesystem

    folder = filesystem.checked(directory())
    if not folder.exists():
        return []
    if (
        not folder.is_dir()
        or folder.stat().st_uid != os.getuid()
        or folder.stat().st_mode & 0o077
    ):
        raise ValueError("Repository cache must be private and owned")
    cutoff = time.time() - TTL
    result = []
    for path in folder.iterdir():
        if not re.fullmatch(r"[a-f0-9]{64}\.json", path.name):
            continue
        try:
            st = path.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISREG(st.st_mode)
            and st.st_uid == os.getuid()
            and st.st_nlink == 1
            and st.st_mtime < cutoff
        ):
            # A filename alone is not evidence that this tool created it.
            if st.st_size > 1_000_000 or st.st_mode & 0o077:
                continue
            try:
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
                ) as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_ctime_ns) != (
                        st.st_dev,
                        st.st_ino,
                        st.st_ctime_ns,
                    ):
                        continue
                    record = json.loads(stream.read(1_000_001))
                if (
                    not isinstance(record, dict)
                    or set(record) != {"key", "value"}
                    or _key(record["key"]) != path.stem
                ):
                    continue
            except (OSError, ValueError, RecursionError):
                continue
            result.append((path, st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns))
    return result


def expire(reviewed):
    eligible = set(expired())
    removed = 0
    for item in reviewed:
        if item in eligible:
            try:
                item[0].unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed
