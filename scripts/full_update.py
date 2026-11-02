#!/usr/bin/env python3
"""Validate full release ZIPs and apply through the shared backed-up patch engine."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import io
import json
from pathlib import Path
import stat
import sys
import zipfile
import patch_manager as patch


def operations(archive):
    items=archive.infolist()
    if len(items)>patch.MAX_FILES or sum(x.file_size for x in items)>patch.MAX_SIZE: raise ValueError('Archive exceeds safety limits')
    seen=set()
    for item in items:
        name=patch.valid_name(item.filename)
        if name in seen or stat.S_ISLNK(item.external_attr>>16): raise ValueError('Duplicate/symlink archive member')
        seen.add(name)
    manifest=json.loads(archive.read('manifest.json'))
    if manifest.get('format') != 2 or not isinstance(manifest.get('files'),list) or not isinstance(manifest.get('deletions'),list): raise ValueError('Invalid full ZIP manifest')
    result=[]; expected={'manifest.json'}
    if 'signature.ed25519' in seen: expected.add('signature.ed25519')
    paths=set()
    for record in manifest['files']:
        name=patch.valid_name(record['path'])
        if name in paths: raise ValueError('Duplicate release path')
        paths.add(name); expected.add(name)
        payload=archive.read(name)
        if record['sha256'] != patch.sha(payload): raise ValueError('Full ZIP checksum mismatch: '+name)
        if type(record.get('mode')) is not int or record['mode'] not in (0o644,0o755): raise ValueError('Invalid release mode')
        target=patch.target_path(name)
        if target.is_file() and patch.sha(target.read_bytes()) == record['sha256'] and target.stat().st_mode & 0o777 == record['mode']: continue
        old=record.get('old_sha256')
        if target.exists() and (not target.is_file() or old is None): raise ValueError('Existing full-update destination conflict: '+name)
        op={'path':name,'action':'modify' if target.exists() else 'add','sha256':record['sha256'],'mode':record['mode']}
        if target.exists(): op['old_sha256']=old
        result.append(op)
    for op in manifest['deletions']:
        name=patch.valid_name(op['path'])
        if name in paths or op.get('action') != 'delete': raise ValueError('Invalid release deletion')
        paths.add(name)
        if patch.target_path(name).exists(): result.append(op)
    if seen != expected: raise ValueError('Unexpected files in full release')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check'); group.add_argument('--apply')
    parser.add_argument('--root',type=Path,default=patch.ROOT,help='existing toolkit directory')
    parser.add_argument('--allow-unsigned',action='store_true',default=True,help='compatibility flag; local updates use checksums')
    parser.add_argument('--trust-key',action='append',default=[])
    args=parser.parse_args(argv)
    root=args.root.expanduser().absolute()
    if any(p.is_symlink() for p in (root,*root.parents)) or not root.is_dir() or root == Path('/'):
        raise ValueError('Select an existing non-symlink toolkit directory')
    patch.ROOT=root.resolve()
    lock=patch.ROOT.parent/'.automation-patch.lock'
    with (contextlib.nullcontext(None) if args.check else lock.open('a+')) as handle:
        if handle is not None: fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
        with zipfile.ZipFile(args.apply or args.check) as archive:
            ops=operations(archive)
            patch.verify_authenticity(archive,allow_unsigned=args.allow_unsigned,trust_keys=args.trust_key)
            # Convert the verified source to the existing patch contract in memory.
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as converted:
                converted.writestr('manifest.json',json.dumps({'format':1,'operations':ops}))
                for op in ops:
                    if op['action'] != 'delete': converted.writestr('payload/'+op['path'],archive.read(op['path']))
        stream.seek(0)
        with zipfile.ZipFile(stream) as converted:
            ops=patch.read_zip(converted)
            if args.check: return 0 if patch.check(ops) else 3
            if not ops: print('Full release already applied.'); return 0
            return patch.apply(converted,ops)


if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print('Full update failed:',exc,file=sys.stderr); sys.exit(2)
