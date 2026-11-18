"""Safe default configuration creation. Existing values are never rewritten."""

from __future__ import annotations
import os
from pathlib import Path
import stat
import tempfile


def ensure(root, parse, validate):
    root = Path(root)
    defaults = root / "config/defaults.env"
    target = root / ".env"
    for path in (root, defaults, target):
        if path.is_symlink():
            raise ValueError("Symlink configuration paths are forbidden")
    wanted = validate(parse(defaults))
    if target.exists():
        st = target.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise ValueError(
                "Configuration must be a regular file owned by the current user"
            )
    existing = validate(parse(target))
    missing = {k: v for k, v in wanted.items() if k not in existing}
    if not missing and target.exists():
        target.chmod(0o600)
        return target
    original = target.read_bytes() if target.exists() else b""
    data = original + (b"\n" if original and not original.endswith(b"\n") else b"")
    data += b"# Safe defaults added by Automation Toolkit\n"
    data += "".join(f"{k}={v}\n" for k, v in missing.items()).encode()
    fd, stage = tempfile.mkstemp(prefix=".config-", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            if target.is_symlink() or target.read_bytes() != original:
                raise ValueError("Configuration changed during merge; retry")
            os.replace(stage, target)
        else:
            # link is exclusive: a concurrent creator is never overwritten.
            os.link(stage, target)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
    return target


# These fields have consumers in the shared CLI. Secrets and private state paths
# are intentionally outside the editor schema.
EDITABLE = {
    "AUTOMATION_PROJECT_SITES_DIR": "Absolute path for the Project Sites directory. Empty uses ~/Documents/Project-Sites.",
    "AUTOMATION_LERD": "Whether the package planner offers Lerd for development services.",
    "AUTOMATION_PREFER_FLATPAK": "Prefer an exact app ID from an already configured Flatpak source.",
    "AUTOMATION_PREFER_SHELLY": "Use Shelly for native Arch package installations when installed.",
    "AUTOMATION_AUTO_SEARCH": "Look for package name alternatives when no exact match is available.",
    "AUTOMATION_ENABLE_AUR": "Allow exact AUR selections in noninteractive Arch commands.",
}


def prepare(root, changes, parse, validate, *, fields=EDITABLE):
    import filesystem

    target = filesystem.checked(root / ".env")
    if not isinstance(changes, dict) or not changes or set(changes) - set(fields):
        raise ValueError("Choose supported configuration fields")
    old = filesystem.read_regular(target, missing=True, limit=65536)
    current = parse(target)
    if filesystem.read_regular(target, missing=True, limit=65536) != old:
        raise ValueError("Configuration changed during review")
    for key, value in changes.items():
        if value is None:
            continue
        if (
            not isinstance(value, str)
            or len(value) > 4096
            or value != value.strip()
            or value.startswith(('"', "'"))
            or any(ord(c) < 32 for c in value)
            or any(token in value for token in ("${", "$(", "`"))
        ):
            raise ValueError(f"Invalid literal value for {key}")
        if (
            key in EDITABLE
            and key != "AUTOMATION_PROJECT_SITES_DIR"
            and value not in ("true", "false")
            and fields is EDITABLE
        ):
            raise ValueError(f"{key} requires true, false, or null for default")
    import re

    seen = set()
    result = []
    for line in (old or b"").decode().splitlines(keepends=True):
        match = re.match(r"^\s*([A-Z_]+)=", line)
        key = match[1] if match else None
        if key in changes:
            seen.add(key)
            if changes[key] is not None:
                result.append(f"{key}={changes[key]}\n")
        else:
            result.append(line)
    remaining = [
        f"{key}={value}\n"
        for key, value in changes.items()
        if key not in seen and value is not None
    ]
    updated = "".join(result)
    if remaining and updated and not updated.endswith("\n"):
        updated += "\n"
    new = (updated + "".join(remaining)).encode()
    if len(new) > 65536:
        raise ValueError("Updated configuration exceeds 64 KiB")
    defaults = parse(root / "config/defaults.env")
    merged = {**defaults, **current}
    for key, value in changes.items():
        if value is not None:
            merged[key] = value
        elif key in defaults:
            merged[key] = defaults[key]
        else:
            merged.pop(key, None)
    validate(merged)
    preview = {
        key: {
            "before": current.get(key),
            "after": value,
            "effective": os.environ.get(key, merged.get(key, "")),
            "environment_override": key in os.environ,
        }
        for key, value in changes.items()
    }
    return target, old, new, preview


def record(state, target, preview):
    import journal
    import uuid
    import workflows

    backup = journal.state_dir(state) / f"config-{uuid.uuid4().hex}.json"
    workflows.write_json(
        backup,
        {
            "target": str(target),
            "before": {key: value["before"] for key, value in preview.items()},
            "expected": {key: value["after"] for key, value in preview.items()},
        },
        private=True,
    )
    return backup.name


def edit(root, changes, parse, validate, *, apply=False, state="", fields=EDITABLE):
    import filesystem

    target, old, new, preview = prepare(root, changes, parse, validate, fields=fields)
    if apply and (old or b"") != new:
        backup = record(state, target, preview)
        if filesystem.read_regular(target, missing=True, limit=65536) != old:
            raise ValueError("Configuration changed during review")
        filesystem.atomic(target, new)
        preview["backup"] = backup
    return preview
