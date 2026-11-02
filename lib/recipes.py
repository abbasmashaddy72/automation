"""Lerd PHP guidance and optional reviewed USB exports; no host activation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


def udev(vendor, product):
    if any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{4}', value)
           for value in (vendor, product)):
        raise ValueError('Provide exact four-digit USB vendor and product IDs; no wildcards')
    return {'70-automation-usb.rules': (
        '# Reviewed USB access for an active local systemd/logind session\n'
        f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vendor.lower()}", '
        f'ATTR{{idProduct}}=="{product.lower()}", MODE="0660", TAG+="uaccess"\n')}


def destination(path):
    path = Path(path).expanduser().absolute()
    if path.exists() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Export requires a new non-symlink directory')
    if not path.parent.is_dir() or path.parent.stat().st_uid != os.getuid():
        raise ValueError('Export parent must be an existing user-owned directory')
    path = path.resolve()
    for blocked in ('/etc', '/usr', '/var', '/boot', '/proc', '/sys', '/dev', '/bin', '/sbin'):
        if path == Path(blocked) or Path(blocked) in path.parents:
            raise ValueError('Export into a user review directory, not a system configuration directory')
    return path


def export(files, output, *, yes=False, dry_run=False):
    path = destination(output)
    manifest = {'schema': 1, 'files': {name: hashlib.sha256(text.encode()).hexdigest()
                                     for name, text in files.items()},
                'activation': 'manual review, backup, target-specific syntax validation; no service restart'}
    if dry_run:
        return manifest
    if not yes:
        raise ValueError('Export requires --yes after reviewing the configuration plan')
    path.mkdir(mode=0o700)
    # Exclusive creation: an interrupted export remains available for inspection.
    # Never remove a directory that another process may have subsequently edited.
    for name, text in {**files, 'manifest.json': json.dumps(manifest, indent=2)+'\n'}.items():
        fd = os.open(path/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Lerd PHP guidance and exact USB review exports; never activate host settings')
    parser.add_argument('kind', choices=['php', 'udev'])
    parser.add_argument('--vendor')
    parser.add_argument('--product')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--standalone', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args(argv)
    if args.kind == 'php':
        print(json.dumps({'provider':'lerd','commands':['bash setup.sh lerd php:list','lerd php:ini','lerd php:ini shared'],
            'note':'Use the public Lerd CLI. Editing with php:ini can restart affected FPM containers; review upstream behavior first. No files or services were changed.'},indent=2))
        if args.standalone or args.output:
            print('Standalone PHP export is retired; development runtimes and settings belong to Lerd.')
            return 3
        return 0
    if args.standalone: parser.error('--standalone is retired')
    files = udev(args.vendor,args.product)
    print(json.dumps({'configuration': files, 'host_changes': False}, indent=2))
    if args.output and not args.check:
        print(json.dumps(export(files, args.output, yes=args.yes, dry_run=args.dry_run), indent=2))
    return 0
