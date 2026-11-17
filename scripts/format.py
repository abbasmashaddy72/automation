#!/usr/bin/env python3
"""Check or format supported source files in the toolkit checkout."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRETTIER = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
LANGUAGES = {**dict.fromkeys(PRETTIER, "prettier"), ".py": "ruff", ".sh": "shfmt"}


def checkout_files():
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    )
    return {
        Path(name)
        for name in listed.decode("utf-8", errors="surrogateescape").split("\0")
        if name
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Report files that need formatting (default)",
    )
    mode.add_argument(
        "--write", action="store_true", help="Apply formatting to the selected files"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Repo-relative files or directories (default: entire checkout)",
    )
    args = parser.parse_args()
    if not shutil.which("git"):
        parser.error("Git is required to enumerate source files")
    try:
        files = checkout_files()
    except subprocess.CalledProcessError:
        parser.error("Run this formatter from a Git checkout of the toolkit")
    targets = [Path(path) for path in args.paths]
    for target in targets:
        if target.is_absolute() or ".." in target.parts or not (ROOT / target).exists():
            parser.error(f"Expected an existing checkout-relative path: {target}")
    grouped = {}
    for path in sorted(files):
        if targets and not any(
            path == target or target in path.parents for target in targets
        ):
            continue
        if path.suffix not in LANGUAGES or path.name in {
            "package-lock.json",
            "composer.lock",
        }:
            continue
        if (
            any((ROOT / part).is_symlink() for part in (path, *path.parents))
            or not (ROOT / path).is_file()
        ):
            continue
        grouped.setdefault(LANGUAGES[path.suffix], []).append(str(path))
    if not grouped:
        parser.error("No supported source files matched")

    local_prettier = ROOT / "chatgpt-lite/node_modules/.bin/prettier"
    tools = {name: shutil.which(name) for name in grouped}
    if "prettier" in tools and local_prettier.is_file() and not tools["prettier"]:
        tools["prettier"] = str(local_prettier)
    missing = [name for name, command in tools.items() if not command]
    if missing:
        parser.error(
            "Install the missing formatter tools before continuing: "
            + ", ".join(missing)
        )

    flags = {
        "prettier": ["--write" if args.write else "--check"],
        "ruff": ["format", "--no-cache", *([] if args.write else ["--check"])],
        "shfmt": ["-w" if args.write else "-d", "-i", "4", "-ci", "-sr"],
    }
    failed = False
    for name, paths in grouped.items():
        if name == "prettier":
            app = ROOT / "chatgpt-lite"
            nested = [
                str(Path(path).relative_to("chatgpt-lite"))
                for path in paths
                if Path(path).parts[0] == "chatgpt-lite"
            ]
            paths = [path for path in paths if Path(path).parts[0] != "chatgpt-lite"]
            if nested:
                result = subprocess.run(
                    [tools[name], *flags[name], "--", *nested], cwd=app, check=False
                )
                failed |= result.returncode != 0
            if not paths:
                continue
        result = subprocess.run(
            [tools[name], *flags[name], "--", *paths], cwd=ROOT, check=False
        )
        failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
