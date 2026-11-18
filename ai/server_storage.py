"""Plan local model storage and attach only explicitly selected filesystems."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import stat

from hardware_inventory import run

FILESYSTEMS = {"ext4", "xfs", "btrfs"}
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
SYSTEM_UNITS = Path("/etc/systemd/system")
UUID_DEVICES = Path("/dev/disk/by-uuid")


def checked_root(value):
    path = Path(value)
    if (
        not path.is_absolute()
        or not re.fullmatch(r"/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", str(path))
        or ".." in path.parts
        or any(part.is_symlink() for part in (path, *path.parents))
    ):
        raise ValueError(
            "Choose an absolute model directory with no symlinks, spaces or parent traversal"
        )
    blocked = (
        "/boot",
        "/dev",
        "/etc",
        "/proc",
        "/run",
        "/sys",
        "/usr",
        "/var/lib/containers",
    )
    if any(path == Path(item) or Path(item) in path.parents for item in blocked):
        raise ValueError(
            "Choose a model directory outside system configuration and runtime paths"
        )
    return path


def inspect(path):
    root = checked_root(path)
    ancestor = next(part for part in (root, *root.parents) if part.exists())
    if not ancestor.is_dir():
        raise ValueError("A model directory conflicts with an existing file")
    raw = run(
        [
            "findmnt",
            "--json",
            "--target",
            str(ancestor),
            "-o",
            "TARGET,SOURCE,FSTYPE,UUID,OPTIONS",
        ]
    )
    mounts = json.loads(raw or "{}").get("filesystems", [])
    if len(mounts) != 1:
        raise RuntimeError(
            "Cannot identify the model storage filesystem; check findmnt"
        )
    mount = mounts[0]
    if "rw" not in (mount.get("options") or "").split(","):
        raise RuntimeError("Model storage filesystem is not writable")
    free = shutil.disk_usage(ancestor).free
    if free < 3 * 1024**3:
        raise RuntimeError("Model storage needs at least 3 GiB free")
    mountpoint = mount["target"]
    return {
        "ready": root.is_dir(),
        "directory": str(root),
        "mount": mountpoint,
        "filesystem": mount["fstype"],
        "source": mount["source"],
        "uuid": (mount.get("uuid") or "").lower() or None,
        "free_gib": round(free / 1024**3, 2),
    }


def is_mount(path):
    return bool(
        run(["findmnt", "--noheadings", "--mountpoint", str(path), "-o", "TARGET"])
    )


def devices():
    raw = run(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--tree",
            "-o",
            "PATH,TYPE,FSTYPE,UUID,MOUNTPOINTS,RO,RM,SIZE",
        ]
    )
    if not raw:
        raise RuntimeError(
            "Storage discovery requires lsblk with JSON and MOUNTPOINTS support"
        )
    tree = json.loads(raw)["blockdevices"]

    def descendants(node):
        yield node
        for child in node.get("children", []):
            yield from descendants(child)

    rows = []
    seen = {}
    for disk in tree:
        branch = list(descendants(disk))
        used = any(
            any(row.get("mountpoints") or []) or row.get("fstype") == "swap"
            for row in branch
        )
        for row in branch:
            identifier = row.get("uuid") or ""
            if identifier:
                seen.setdefault(identifier.lower(), set()).add(row.get("path"))
            if (
                not used
                and disk.get("type") == "disk"
                and row["type"] in ("disk", "part")
                and row["size"] >= 3 * 1024**3
                and not row.get("children")
                and row.get("ro") is False
                and disk.get("rm") is False
                and disk.get("ro") is False
                and row.get("fstype") in FILESYSTEMS
                and UUID.fullmatch(identifier)
                and re.fullmatch(
                    r"/dev/(?:sd[a-z]+[0-9]*|vd[a-z]+[0-9]*|nvme[0-9]+n[0-9]+(?:p[0-9]+)?|mmcblk[0-9]+(?:p[0-9]+)?)",
                    row.get("path") or "",
                )
            ):
                rows.append(
                    {
                        "uuid": identifier.lower(),
                        "device": row["path"],
                        "filesystem": row["fstype"],
                        "bytes": row["size"],
                    }
                )
    return [row for row in rows if len(seen[row["uuid"]]) == 1]


def selected(identifier):
    if not isinstance(identifier, str) or not UUID.fullmatch(identifier):
        raise ValueError("Choose a filesystem UUID from ai server storage")
    candidates = [row for row in devices() if row["uuid"] == identifier.lower()]
    if len(candidates) != 1:
        raise RuntimeError(
            "Selected UUID is not an unmounted supported filesystem on an unused disk"
        )
    return candidates[0]


def check_mount_path(root):
    for part in (root, *root.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError(
                "Choose a mount point under root-owned, administrator-writable directories such as /srv"
            )


def mount_selected(root, identifier, action, marker):
    root = checked_root(root)
    if not isinstance(identifier, str) or not UUID.fullmatch(identifier):
        raise ValueError("Choose a filesystem UUID from ai server storage")
    uuid = identifier.lower()
    name = run(["systemd-escape", "--path", "--suffix=mount", str(root)])
    if not re.fullmatch(r"[A-Za-z0-9_.\\-]+\.mount", name):
        raise RuntimeError("Cannot determine the systemd mount unit name")
    path = SYSTEM_UNITS / name
    if path.is_symlink():
        raise RuntimeError("Mount unit is a symlink")
    fragment = run(["systemctl", "show", "-p", "FragmentPath", "--value", name])
    if fragment and fragment != str(path):
        raise RuntimeError(
            "A different systemd mount configuration already owns this path"
        )

    def content(filesystem):
        return (
            f"{marker}\n[Mount]\nWhat=/dev/disk/by-uuid/{uuid}\n"
            f"Where={root}\nType={filesystem}\nOptions=rw,nodev,nosuid,noexec\nTimeoutSec=30\n"
        )

    if path.exists():
        if not path.is_file() or path.stat().st_size > 4096:
            raise RuntimeError("Unsafe existing mount unit")
        current = path.read_text()
        if not any(current == content(fs) for fs in FILESYSTEMS):
            raise RuntimeError(
                "Existing mount unit differs from the selected filesystem"
            )
    if is_mount(root):
        mounted = inspect(root)
        if path.is_file() and mounted["mount"] == str(root) and mounted["uuid"] == uuid:
            return mounted
        raise RuntimeError(
            "Mount point already in use. Reuse it with --data-root alone"
        )

    choice = selected(uuid)
    check_mount_path(root)
    device = UUID_DEVICES / uuid
    if device.resolve(strict=True) != Path(choice["device"]).resolve(
        strict=True
    ) or not stat.S_ISBLK(device.stat().st_mode):
        raise RuntimeError("Selected filesystem device changed")
    fstab = action(
        [
            "findmnt",
            "--fstab",
            "--evaluate",
            "--noheadings",
            "--raw",
            "-o",
            "SOURCE,TARGET",
        ],
        capture=True,
        check=False,
    )
    if fstab.returncode not in (0, 1) or fstab.stderr:
        raise RuntimeError("Cannot verify existing fstab assignments")
    for line in fstab.stdout.splitlines():
        source, _, target = line.partition(" ")
        if (
            target.strip() == str(root)
            or source == f"UUID={uuid}"
            or Path(source).resolve() == device.resolve()
        ):
            raise RuntimeError(
                "Selected filesystem or mount point already has an fstab entry"
            )
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise RuntimeError("The mount point must be an empty directory")
    action(["mkdir", "-p", "--", root], root=True)
    check_mount_path(root)
    if any(root.iterdir()) or is_mount(root) or selected(uuid) != choice:
        raise RuntimeError("Storage changed while preparing the mount")
    if not path.exists():
        import tempfile

        with tempfile.TemporaryDirectory() as staging:
            source = Path(staging) / name
            source.write_text(content(choice["filesystem"]))
            pending = path.with_name(".automation-mount-" + source.parent.name)
            action(["install", "-m", "0644", "--", source, pending], root=True)
            try:
                action(["ln", "-T", "--", pending, path], root=True)
            finally:
                action(["rm", "-f", "--", pending], root=True)
    if path.is_symlink() or path.read_text() != content(choice["filesystem"]):
        raise RuntimeError("Mount configuration changed before activation")
    action(["systemctl", "daemon-reload"], root=True)
    action(["systemctl", "start", name], root=True)
    mounted = inspect(root)
    if mounted["mount"] != str(root) or mounted["uuid"] != uuid:
        raise RuntimeError("Mounted filesystem does not match the selected UUID")
    return mounted
