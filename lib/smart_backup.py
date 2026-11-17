"""Reviewed personal-directory backups shared by the terminal and dashboard."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


DEFAULT_EXCLUDES = (".git", "node_modules", "vendor", "vendors", "__pycache__")
HOME_FOLDERS = (
    "Desktop",
    "Documents",
    "Downloads",
    "Music",
    "Pictures",
    "Videos",
    "Code",
)
SYSTEM_TREES = ("/dev", "/proc", "/sys", "/run", "/etc", "/boot")


def directory(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError("Enter an existing absolute folder path.")
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Enter an absolute folder path without parent traversal.")
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError(f"Choose a real directory, without symbolic links: {path}")
    if any(
        path.is_relative_to(tree) for tree in SYSTEM_TREES
    ) and not path.is_relative_to("/run/media"):
        raise ValueError(f"System directories are outside the backup workflow: {path}")
    return path


def external_destinations():
    if not shutil.which("lsblk"):
        return []
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--output", "NAME,TYPE,TRAN,RM,HOTPLUG,RO,MOUNTPOINTS"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        devices = json.loads(result.stdout)["blockdevices"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return []
    mounts = mounted_paths()
    devices = [(record, False) for record in devices]
    choices = set()
    while devices:
        record, external_parent = devices.pop()
        external = external_parent or (
            record.get("type") == "disk"
            and (
                record.get("tran") == "usb" or record.get("rm") or record.get("hotplug")
            )
        )
        if record.get("ro"):
            continue
        if external:
            for point in record.get("mountpoints") or ():
                if not point or point in ("/", "[SWAP]"):
                    continue
                try:
                    path = directory(point)
                    if (
                        path in mounts
                        and os.access(path, os.W_OK | os.X_OK)
                        and not os.statvfs(path).f_flag & os.ST_RDONLY
                    ):
                        choices.add(str(path))
                except (OSError, ValueError):
                    continue
        devices.extend((child, external) for child in record.get("children", ()))
    return sorted(choices)


def home_jobs(source):
    paths = []
    for name in (*HOME_FOLDERS, "Documents/Project-Sites"):
        child = source / name
        if child.is_dir() and child.resolve() == child:
            paths.append({"path": name, "mode": "zip" if "/" in name else "copy"})
    return paths


def browse(value=None, *, hidden=False):
    path = directory(value or str(Path.home()))
    folders = []
    with os.scandir(path) as entries:
        for entry in entries:
            if (hidden or not entry.name.startswith(".")) and entry.is_dir(
                follow_symlinks=False
            ):
                folders.append(entry.name)
    folders.sort(key=str.casefold)
    return {
        "path": str(path),
        "parent": str(path.parent),
        "folders": folders[:250],
        "more": len(folders) > 250,
        "home": str(Path.home()),
        "external": external_destinations() if value is None else [],
        "default_excludes": list(DEFAULT_EXCLUDES),
        "home_jobs": home_jobs(path),
    }


def identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def revision(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def mounted_paths():
    paths = set()
    with open(
        "/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape"
    ) as info:
        for line in info:
            fields = line.split()
            if len(fields) >= 5:
                mount = re.sub(
                    r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4]
                )
                paths.add(Path(mount))
    return paths


def scan(root, skip, excludes, hidden, mounts, *, root_file_policy=None):
    """Collect literal relative paths without following directory symlinks."""
    root_info = root.lstat()
    entries = []
    pending = [(Path("."), root_info)]
    skipped = 0
    while pending:
        relative, info = pending.pop()
        if info.st_dev != root_info.st_dev or (
            relative != Path(".") and root / relative in mounts
        ):
            skipped += 1
            continue
        is_dir = stat.S_ISDIR(info.st_mode)
        if not (is_dir or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            skipped += 1
            continue
        entries.append((relative, info))
        if is_dir:
            descriptor = os.open(
                root / relative, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                if revision(os.fstat(descriptor)) != revision(info):
                    raise ValueError(
                        f"A source directory changed during preview: {root / relative}"
                    )
                with os.scandir(descriptor) as listing:
                    for entry in sorted(
                        listing, key=lambda item: item.name, reverse=True
                    ):
                        candidate = relative / entry.name
                        if candidate in skip or (
                            not hidden and entry.name.startswith(".")
                        ):
                            continue
                        child_info = entry.stat(follow_symlinks=False)
                        if relative == Path(".") and root_file_policy is not None:
                            root_file = stat.S_ISREG(
                                child_info.st_mode
                            ) or stat.S_ISLNK(child_info.st_mode)
                            if (root_file_policy and not root_file) or (
                                not root_file_policy
                                and root_file
                                and not entry.name.startswith(".")
                            ):
                                continue
                        if entry.name in excludes and (
                            stat.S_ISDIR(child_info.st_mode)
                            or stat.S_ISLNK(child_info.st_mode)
                        ):
                            continue
                        pending.append((candidate, child_info))
            finally:
                os.close(descriptor)
    return entries, skipped


def prepare(spec):
    if not isinstance(spec, dict) or set(spec) - {
        "source",
        "destination",
        "jobs",
        "root_files",
        "hidden",
        "excludes",
        "verification",
    }:
        raise ValueError("Invalid backup options.")
    source = directory(spec.get("source", str(Path.home())))
    target = directory(spec.get("destination"))
    if source == Path("/") or target == Path("/"):
        raise ValueError(
            "Choose personal folders or a mounted data device instead of /."
        )
    if (
        not os.access(target, os.W_OK | os.X_OK)
        or os.statvfs(target).f_flag & os.ST_RDONLY
    ):
        raise ValueError(f"Destination is not writable: {target}")
    root_files = spec.get("root_files", False)
    if type(root_files) is not bool:
        raise ValueError("Choose whether to copy files directly in the source folder.")
    if root_files and target == source:
        raise ValueError(
            "Choose a destination separate from the source when copying its top-level files."
        )
    hidden = spec.get("hidden", False)
    exclusions = spec.get("excludes", list(DEFAULT_EXCLUDES))
    verify = spec.get("verification", "checksum")
    if type(hidden) is not bool or verify not in ("checksum", "quick"):
        raise ValueError(
            "Choose whether to include hidden entries and a valid verification mode."
        )
    if (
        not isinstance(exclusions, list)
        or len(exclusions) > 100
        or any(
            not isinstance(name, str)
            or not name
            or name in (".", "..")
            or "/" in name
            or any(ord(char) < 32 for char in name)
            for name in exclusions
        )
    ):
        raise ValueError(
            "Exclusions must be individual directory names, such as node_modules."
        )
    selections = spec.get("jobs")
    if not isinstance(selections, list) or len(selections) > 150:
        raise ValueError("Select no more than 150 folders.")
    choices = {}
    for row in selections:
        if not isinstance(row, dict) or set(row) - {"path", "mode", "hidden"}:
            raise ValueError("Invalid folder selection.")
        value, mode = row.get("path"), row.get("mode")
        folder_hidden = row.get("hidden", hidden)
        if type(folder_hidden) is not bool:
            raise ValueError(
                "Choose whether to include hidden entries in each selected folder."
            )
        if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
            raise ValueError("Choose a folder relative to the source.")
        relative = Path(value)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or mode not in ("copy", "zip", "skip")
        ):
            raise ValueError("Choose a source-relative folder and Copy, ZIP, or Skip.")
        if relative in choices:
            raise ValueError(f"Choose one format for each folder: {relative}")
        folder = directory(str(source / relative))
        if mode != "skip" and target.is_relative_to(folder):
            raise ValueError(f"The destination is inside the selected folder: {folder}")
        choices[relative] = (mode, folder_hidden)

    jobs = []
    inventories = []
    mount_identity = identity(target)
    mounts = mounted_paths()
    active = [
        (relative, mode, folder_hidden)
        for relative, (mode, folder_hidden) in choices.items()
        if mode != "skip"
    ]
    if root_files:
        active.insert(0, (None, "copy", False))
    if not active:
        raise ValueError(
            "Select Copy or ZIP for at least one folder, or select top-level files."
        )
    for number, (relative, mode, folder_hidden) in enumerate(active, 1):
        only_files = relative is None
        root = source if only_files else source / relative
        nested = {
            child.relative_to(relative): child_mode
            for child, (child_mode, _) in choices.items()
            if relative is not None
            and child != relative
            and child.is_relative_to(relative)
        }
        root_file_policy = (
            True
            if only_files
            else False
            if root_files and relative == Path(".")
            else None
        )
        entries, skipped = scan(
            root,
            nested,
            set(exclusions),
            folder_hidden,
            mounts,
            root_file_policy=root_file_policy,
        )
        leaf = (
            "top-level-files"
            if only_files
            else re.sub(r"[^a-zA-Z0-9._-]", "_", root.name)[:70]
        )
        output = f"{mode}/{number:03d}-{leaf}" + (".zip" if mode == "zip" else "")
        jobs.append(
            {
                "path": "." if only_files else str(relative),
                "scope": "root-files" if only_files else "folder",
                "mode": mode,
                "hidden": folder_hidden,
                "output": output,
                "entries": len(entries),
                "bytes": sum(
                    info.st_size for _, info in entries if stat.S_ISREG(info.st_mode)
                ),
                "skipped_special_or_other_device": skipped,
                "separate": sorted(
                    str(child)
                    for child, child_mode in nested.items()
                    if child_mode != "skip"
                ),
                "excluded_folders": sorted(
                    str(child)
                    for child, child_mode in nested.items()
                    if child_mode == "skip"
                ),
            }
        )
        inventories.append((root, entries))
    total = sum(job["bytes"] for job in jobs)
    # Cover directory blocks and ZIP headers conservatively, including small-file backups.
    estimate = (
        total + total // 100 + sum(job["entries"] for job in jobs) * 4096 + 1024 * 1024
    )
    free = shutil.disk_usage(target).free
    ready = shutil.which("rsync") is not None or all(
        row["mode"] == "zip" for row in jobs
    )
    review = {
        "source": str(source),
        "destination": str(target),
        "hidden": hidden,
        "excludes": sorted(set(exclusions)),
        "verification": verify,
        "jobs": jobs,
        "estimated_bytes": estimate,
        "free_bytes": free,
        "rsync_ready": ready,
    }
    fingerprint = [
        {key: value for key, value in review.items() if key != "free_bytes"},
        mount_identity,
        [
            [(str(path), revision(info)) for path, info in entries]
            for _, entries in inventories
        ],
    ]
    review["revision"] = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode()
    ).hexdigest()
    return review, inventories, mount_identity


def copy_tree(root, entries, output, verification):
    output.mkdir()
    paths = b"".join(
        os.fsencode(str(path)) + b"\0" for path, _ in entries if path != Path(".")
    )
    command = [
        "rsync",
        "-aHAX",
        "--numeric-ids",
        "--sparse",
        "--dirs",
        "--no-recursive",
        "--no-devices",
        "--no-specials",
        "--from0",
        "--files-from=-",
    ]
    args = ["--", f"{root}/", f"{output}/"]
    if paths:
        subprocess.run(command + args, input=paths, check=True)
    # An explicit "." in a files-from list includes immediate, unselected entries.
    # Transfer only root metadata separately, after the selected children.
    root_metadata = ["rsync", "-dptgoAX", "--numeric-ids", "--exclude=*"]
    subprocess.run(root_metadata + args, check=True)
    verify = ["--dry-run", "--itemize-changes"]
    if verification == "checksum":
        verify.append("--checksum")
    result = subprocess.run(
        command + verify + args, input=paths, capture_output=True, check=True
    )
    root_result = subprocess.run(
        root_metadata + ["--dry-run", "--itemize-changes"] + args,
        capture_output=True,
        check=True,
    )
    copied, _ = scan(output, set(), set(), True, set())
    if (
        result.stdout
        or root_result.stdout
        or {path for path, _ in copied} != {path for path, _ in entries}
    ):
        raise ValueError(f"Copy verification found differences under {root}.")


def zip_tree(root, entries, output, verification):
    digests = {}
    with zipfile.ZipFile(
        output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3
    ) as archive:
        for relative, before in entries:
            path = root / relative
            if revision(path.lstat()) != revision(before):
                raise ValueError(f"A source entry changed during backup: {path}")
            name = root.name if relative == Path(".") else f"{root.name}/{relative}"
            # Backslashes are separators in some ZIP tools.
            if "\\" in name:
                raise ValueError(f"ZIP cannot safely represent this filename: {path}")
            is_dir = stat.S_ISDIR(before.st_mode)
            item = zipfile.ZipInfo(name + ("/" if is_dir else ""))
            date = datetime.fromtimestamp(before.st_mtime)
            date = min(max(date, datetime(1980, 1, 1)), datetime(2107, 12, 31))
            item.date_time = date.timetuple()[:6]
            item.create_system = 3
            item.external_attr = (before.st_mode << 16) | (0x10 if is_dir else 0)
            if is_dir:
                archive.writestr(item, b"")
            elif stat.S_ISLNK(before.st_mode):
                archive.writestr(item, os.fsencode(os.readlink(path)))
            else:
                item.compress_type = zipfile.ZIP_DEFLATED
                item.file_size = before.st_size
                digest = hashlib.sha256() if verification == "checksum" else None
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
                ) as data:
                    if revision(os.fstat(data.fileno())) != revision(before):
                        raise ValueError(f"A source file changed during backup: {path}")
                    with archive.open(item, "w", force_zip64=True) as saved:
                        for chunk in iter(lambda: data.read(1024 * 1024), b""):
                            saved.write(chunk)
                            if digest:
                                digest.update(chunk)
                    if revision(os.fstat(data.fileno())) != revision(before):
                        raise ValueError(f"A source file changed during backup: {path}")
                if digest:
                    digests[name] = digest.digest()
    with zipfile.ZipFile(output) as archive:
        if verification == "quick":
            if archive.testzip() is not None:
                raise ValueError(f"ZIP integrity check failed: {output.name}")
        else:
            for item in archive.infolist():
                digest = hashlib.sha256()
                with archive.open(item) as data:
                    for chunk in iter(lambda: data.read(1024 * 1024), b""):
                        digest.update(chunk)
                if (
                    item.filename in digests
                    and digest.digest() != digests[item.filename]
                ):
                    raise ValueError(f"ZIP checksum doesn't match: {item.filename}")


def execute(plan, inventories, destination_identity):
    target = Path(plan["destination"])
    if not plan["rsync_ready"]:
        raise ValueError(
            "Copy requires rsync. Install it through the toolkit or select ZIP."
        )
    if plan["free_bytes"] < plan["estimated_bytes"]:
        raise ValueError(
            "The destination has less free space than the backup estimate."
        )
    if identity(target) != destination_identity:
        raise ValueError("The destination changed. Review the backup again.")
    staged = Path(tempfile.mkdtemp(prefix=".smart-backup-incomplete-", dir=target))
    try:
        for job, (root, entries) in zip(plan["jobs"], inventories):
            output = staged / job["output"]
            output.parent.mkdir(exist_ok=True)
            label = job_label(job)
            print(
                f"{job['mode'].upper()} {label} ({job['entries']} entries).",
                flush=True,
            )
            writer = copy_tree if job["mode"] == "copy" else zip_tree
            writer(root, entries, output, plan["verification"])
            for path, info in entries:
                if revision((root / path).lstat()) != revision(info):
                    raise ValueError(
                        f"A source entry changed during backup: {root / path}"
                    )
            print(f"Verified {label}.", flush=True)
        if identity(target) != destination_identity:
            raise ValueError("The destination changed during backup.")
        (staged / "manifest.json").write_text(json.dumps(plan, indent=2) + "\n")
        suffix = staged.name.rsplit("-", 1)[-1]
        final = target / f"smart-backup-{datetime.now():%Y%m%d-%H%M%S}-{suffix}"
        staged.rename(final)
    except (Exception, KeyboardInterrupt):
        print(f"Backup incomplete. Partial output may be at {staged}", file=sys.stderr)
        raise
    print(f"Backup complete: {final}", flush=True)
    return final


def job_label(job):
    return "Top-level files" if job["scope"] == "root-files" else job["path"]


def show_plan(plan):
    print(f"Source: {plan['source']}\nDestination: {plan['destination']}")
    for job in plan["jobs"]:
        print(
            f"  {job['mode'].upper():4} {job_label(job)} → {job['output']} ({job['entries']} entries; hidden {'included' if job['hidden'] else 'excluded'})"
        )
        if job["separate"]:
            print("       Separate backups: " + ", ".join(job["separate"]))
        if job["excluded_folders"]:
            print("       Excluded folders: " + ", ".join(job["excluded_folders"]))
    print(
        f"Estimated space: {plan['estimated_bytes']:,} bytes. Available: {plan['free_bytes']:,} bytes."
    )
    print(
        f"Hidden entries: {'include' if plan['hidden'] else 'exclude'}. Verification: {plan['verification']}."
    )
    print("Excluded names: " + (", ".join(plan["excludes"]) or "none"))
    if not plan["rsync_ready"]:
        print("Copy prerequisite missing: rsync.")


def interactive():
    if not sys.stdin.isatty():
        raise ValueError(
            "Open this workflow in a terminal, or use smart-backup plan/run --help."
        )
    defaults = browse()
    source = input(f"Source folder [{defaults['home']}]: ").strip() or defaults["home"]
    candidates = defaults["external"]
    for number, folder in enumerate(candidates, 1):
        print(f"  {number}. {folder}")
    if not candidates:
        print(
            "No mounted writable external drive detected. Enter a destination folder."
        )
    dest = input(
        "Destination number or absolute folder" + (" [1]" if candidates else "") + ": "
    ).strip()
    if not dest and candidates:
        dest = candidates[0]
    elif dest.isascii() and dest.isdecimal() and 0 < int(dest) <= len(candidates):
        dest = candidates[int(dest) - 1]
    folders = browse(source, hidden=True)["folders"]
    for index, folder in enumerate(folders, 1):
        print(f"  {index:3}. {folder!r}")
    use_defaults = (
        input("Start with the standard home backup selection? [Y/n]: ").strip().lower()
        != "n"
    )
    jobs = (
        {job["path"]: job for job in home_jobs(directory(source))}
        if use_defaults
        else {}
    )
    if jobs:
        print(
            "Preselected: "
            + ", ".join(f"{job['mode']} {path}" for path, job in jobs.items())
        )
    root_files = (
        input(
            f"Copy visible files directly in the source folder? {'[Y/n]' if use_defaults else '[y/N]'}: "
        )
        .strip()
        .lower()
    )
    root_files = root_files == "y" or (not root_files and use_defaults)
    for mode in ("copy", "zip", "skip"):
        print(
            f"{mode.upper()}: enter one folder number or relative path at a time. Enter . for the entire source."
        )
        while True:
            value = input(f"{mode.upper()} folder (blank to continue): ").strip()
            if not value:
                break
            if value.isascii() and value.isdecimal() and 0 < int(value) <= len(folders):
                value = folders[int(value) - 1]
            path = str(Path(value))
            jobs[path] = {"path": path, "mode": mode}
    hidden = (
        input("Include hidden entries inside selected folders? [y/N]: ").lower() == "y"
    )
    if (
        jobs
        and input("Override hidden entries for individual folders? [y/N]: ").lower()
        == "y"
    ):
        for job in jobs.values():
            if job["mode"] == "skip":
                continue
            value = (
                input(
                    f"Include hidden entries in {job['path']}? [y/n, blank for default]: "
                )
                .strip()
                .lower()
            )
            if value in ("y", "n"):
                job["hidden"] = value == "y"
            elif value:
                raise ValueError("Choose y, n, or leave blank.")
    excludes = input(
        f"Excluded folder names, comma-separated [{', '.join(DEFAULT_EXCLUDES)}] (type none to clear): "
    ).strip()
    spec = {
        "source": source,
        "destination": dest,
        "jobs": list(jobs.values()),
        "root_files": root_files,
        "hidden": hidden,
        "excludes": []
        if excludes == "none"
        else [name.strip() for name in excludes.split(",")]
        if excludes
        else list(DEFAULT_EXCLUDES),
    }
    plan, inventory, fingerprint = prepare(spec)
    show_plan(plan)
    if input("Create and verify this backup? [y/N]: ").lower() != "y":
        return 130
    execute(plan, inventory, fingerprint)
    return 0


def main(argv):
    parser = argparse.ArgumentParser(
        prog="bash setup.sh smart-backup", description=__doc__
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "interactive", help="Choose folders and formats in the terminal"
    )
    listing = commands.add_parser(
        "browse", help="Read-only folder and mounted-drive discovery"
    )
    listing.add_argument("--path")
    listing.add_argument("--hidden", action="store_true")
    for action in ("plan", "run"):
        command = commands.add_parser(action)
        command.add_argument("--source", default=str(Path.home()))
        command.add_argument("--destination")
        command.add_argument("--copy", action="append", default=[], metavar="FOLDER")
        command.add_argument("--zip", action="append", default=[], metavar="FOLDER")
        command.add_argument(
            "--home-defaults",
            action="store_true",
            help="Select standard home folders, Project-Sites ZIP and visible top-level files",
        )
        command.add_argument(
            "--root-files",
            action="store_true",
            help="Copy visible files and symlinks directly under the source",
        )
        command.add_argument(
            "--skip-folder",
            dest="skip",
            action="append",
            default=[],
            metavar="FOLDER",
            help="Exclude a subtree or remove a preset folder",
        )
        command.add_argument("--include-hidden", action="store_true")
        command.add_argument(
            "--hidden-in", action="append", default=[], metavar="FOLDER"
        )
        command.add_argument(
            "--visible-only-in", action="append", default=[], metavar="FOLDER"
        )
        command.add_argument(
            "--exclude-dir", action="append", default=[], metavar="NAME"
        )
        command.add_argument("--clear-default-exclusions", action="store_true")
        command.add_argument(
            "--verification", choices=("quick", "checksum"), default="checksum"
        )
        command.add_argument("--spec", help=argparse.SUPPRESS)
        command.add_argument("--json", action="store_true")
        command.add_argument("--yes", action="store_true")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--expected-plan", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "interactive"):
            return interactive()
        if args.command == "browse":
            print(json.dumps(browse(args.path, hidden=args.hidden)))
            return 0
        spec = (
            json.loads(args.spec)
            if args.spec is not None
            else {
                "source": args.source,
                "destination": args.destination,
                "hidden": args.include_hidden,
                "root_files": args.root_files or args.home_defaults,
                "excludes": (
                    [] if args.clear_default_exclusions else list(DEFAULT_EXCLUDES)
                )
                + args.exclude_dir,
                "verification": args.verification,
                "jobs": [
                    {"path": path, "mode": mode}
                    for mode in ("copy", "zip", "skip")
                    for path in getattr(args, mode)
                ],
            }
        )
        if args.spec is None:
            if args.home_defaults:
                jobs = {
                    Path(job["path"]): job for job in home_jobs(directory(args.source))
                }
                requested = [Path(job["path"]) for job in spec["jobs"]]
                if len(requested) != len(set(requested)):
                    raise ValueError("Choose one format per folder.")
                jobs.update({Path(job["path"]): job for job in spec["jobs"]})
                spec["jobs"] = list(jobs.values())
            included = {Path(path) for path in args.hidden_in}
            excluded = {Path(path) for path in args.visible_only_in}
            selected = {Path(job["path"]) for job in spec["jobs"]}
            if included & excluded or (included | excluded) - selected:
                raise ValueError("Give one hidden-file override per selected folder.")
            for job in spec["jobs"]:
                path = Path(job["path"])
                if path in included or path in excluded:
                    job["hidden"] = path in included
        plan, inventory, fingerprint = prepare(spec)
        if args.command == "plan" or args.dry_run:
            if args.json:
                print(json.dumps(plan))
            else:
                show_plan(plan)
            return 0
        if not args.yes:
            raise ValueError(
                "Review with smart-backup plan, then authorize with run --yes."
            )
        if args.expected_plan and args.expected_plan != plan["revision"]:
            raise ValueError(
                "The source or destination changed after preview. Review the backup again."
            )
        execute(plan, inventory, fingerprint)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Backup cancelled.", file=sys.stderr)
        return 130
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Smart Backup: {error}", file=sys.stderr)
        return 1
