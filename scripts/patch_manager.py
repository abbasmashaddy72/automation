#!/usr/bin/env python3
"""Checksum-validated ZIP patch staging, atomic per-file replace and rollback.

Manifest v1 records operations and original checksums. Archives must contain
manifest.json and payload/<relative-path> entries; no absolute/symlink paths.
The toolkit is not a transactional filesystem; rollback is best-effort after
unrecoverable power loss, but automatic on caught application errors.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {'.env', '.env.local'}
MAX_FILES = 5000
MAX_SIZE = 100 * 1024 * 1024


def valid_name(name):
    if not isinstance(name,str) or not name or len(name)>1024 or '\\' in name or any(ord(c)<32 for c in name) or name.startswith('/'):
        raise ValueError(f'Invalid path: {name!r}')
    p = PurePosixPath(name)
    if str(p) != name or name == '.' or '..' in p.parts or '.' in p.parts or p.is_absolute() or ':' in p.parts[0]:
        raise ValueError(f'Unsafe path: {name!r}')
    if name.split('/')[0] in ('backups', '.git', 'logs', 'reports') or name in PROTECTED or name.startswith('.env.') and name != '.env.example':
        raise ValueError(f'Protected destination: {name!r}')
    return name


def target_path(name):
    valid_name(name)
    target = ROOT / name
    # Reject existing symlink ancestors; never write through attacker links.
    parent = target
    while parent != ROOT:
        if parent.is_symlink(): raise ValueError('Symlink destination is forbidden: ' + name)
        parent = parent.parent
    return target


def sha(data): return hashlib.sha256(data).hexdigest()


def verify_authenticity(z, *, allow_unsigned=True, trust_keys=()):
    """Local updates use SHA-256; optional signatures are verified when present.

    Keys must be provisioned out-of-band, not shipped inside the patch. SHA-256
    payload checks only prove integrity and are NOT a signature.
    """
    signed='signature.ed25519' in z.namelist()
    if not signed:
        if allow_unsigned:
            return 'local-checksums-only'
        raise ValueError('Unsigned patch refused. Supply a trusted signature or explicitly pass --allow-unsigned.')
    if not trust_keys:
        raise ValueError('Signed patch requires a trusted public key (--trust-key PATH).')
    signature=z.read('signature.ed25519')
    if len(signature)!=64: raise ValueError('Invalid Ed25519 signature size')
    data=z.read('manifest.json')
    with tempfile.TemporaryDirectory(prefix='automation-verify-') as tmp:
        msg=Path(tmp)/'manifest'; sig=Path(tmp)/'signature'
        msg.write_bytes(data);sig.write_bytes(signature)
        for key in trust_keys:
            key=Path(key).expanduser()
            if not key.is_file() or key.is_symlink(): continue
            if key.stat().st_size>16384: continue
            try:
                p=subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(key),
                                  '-rawin','-in',str(msg),'-sigfile',str(sig)],
                                 capture_output=True,timeout=10)
            except (OSError,subprocess.TimeoutExpired): continue
            if p.returncode==0:
                print('Verified Ed25519 patch signature with trusted key:',key)
                return 'signed-and-verified'
    raise ValueError('Patch signature verification failed for all trusted public keys')


def read_zip(z):
    members = z.infolist()
    if len(members) > MAX_FILES or sum(i.file_size for i in members) > MAX_SIZE:
        raise ValueError('Archive exceeds safety limits')
    seen = set()
    for item in members:
        name = item.filename.rstrip('/')
        valid_name(name)
        if name in seen: raise ValueError('Duplicate archive member: ' + name)
        seen.add(name)
        if stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('Symlink archive member forbidden: ' + name)
    if z.namelist().count('manifest.json') != 1:
        raise ValueError('Missing or duplicate manifest')
    manifest = json.loads(z.read('manifest.json'))
    if manifest.get('format') != 1 or not isinstance(manifest.get('operations'), list):
        raise ValueError('Invalid manifest format')
    operations = manifest['operations']
    paths = set()
    renamed_sources = set()
    for op in operations:
        if not isinstance(op,dict): raise ValueError('Invalid patch operation')
        path = valid_name(op['path'])
        if path in paths: raise ValueError('Duplicate operation destination')
        paths.add(path)
        if op['action'] not in ('add','modify','delete','rename'):
            raise ValueError('Invalid patch operation')
        if 'mode' in op and (type(op['mode']) is not int or op['mode'] not in (0o644,0o755)):
            raise ValueError('Invalid file mode')
        for key in ('old_sha256', 'sha256'):
            if key in op and op[key] is not None and not __import__('re').fullmatch(r'[a-f0-9]{64}', op[key]):
                raise ValueError('Bad checksum')
        if op['action'] == 'rename':
            old = valid_name(op['from'])
            if old in paths or old in renamed_sources: raise ValueError('Conflicting rename')
            renamed_sources.add(old)
            target_path(old)
        target_path(path)
        if op['action'] != 'add' and not op.get('old_sha256'): raise ValueError('Missing original checksum')
        if op['action'] in ('add', 'modify', 'rename'):
            member = 'payload/' + path
            if member not in seen: raise ValueError('Missing payload: '+path)
            data = z.read(member)
            if sha(data) != op.get('sha256'): raise ValueError('Payload checksum mismatch: '+path)
    if paths & renamed_sources: raise ValueError('Conflicting rename destination')
    if set(x for x in seen if x.startswith('payload/') and not x.endswith('/')) != {
            'payload/' + op['path'] for op in operations if op['action'] in ('add','modify','rename')}:
        raise ValueError('Unexpected payload entries')
    return operations


def check(ops, force=False):
    conflicts = []
    for op in ops:
        dest = target_path(op['path'])
        old = target_path(op['from']) if op['action'] == 'rename' else dest
        is_add = op['action'] == 'add'
        if is_add and dest.exists(): conflicts.append(op['path'] + ': already exists')
        if not is_add and (not old.is_file() or sha(old.read_bytes()) != op.get('old_sha256')):
            conflicts.append(str(old.relative_to(ROOT)) + ': original checksum differs')
        if op['action'] == 'rename' and dest.exists(): conflicts.append(op['path'] + ': target exists')
    if conflicts:
        print('Conflicts:', *conflicts, sep='\n - ', file=sys.stderr)
        if not force: return False
        print('Force mode: overwriting conflicting files after backup; no automatic deletion of local configs.', file=sys.stderr)
    return True


def backup_root():
    d = Path(os.environ.get('AUTOMATION_PATCH_BACKUP_DIR', str(ROOT.parent / '.automation-patch-backups'))).absolute()
    if any(p.is_symlink() for p in (d,*d.parents)): raise ValueError('Symlink backup paths are forbidden')
    d = d.resolve()
    if d == ROOT or ROOT in d.parents:
        raise ValueError('Patch backup directory must be outside repository')
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def restore(folder, *, verify_current=False):
    state = json.loads((folder/'state.json').read_text())
    # Verify every original BEFORE restoring any files.
    for rel, old_sha in state['originals'].items():
        target_path(rel)
        if old_sha is not None:
            src = folder/'originals'/rel
            if any(p.is_symlink() for p in (src,*src.parents)) or not src.is_file() or sha(src.read_bytes()) != old_sha:
                raise ValueError('Corrupt rollback backup')
    if verify_current:
        for rel, expected in state.get('applied', {}).items():
            dest = target_path(rel)
            current = sha(dest.read_bytes()) if dest.is_file() else None
            if current != expected:
                raise ValueError(f'Rollback conflict: {rel} was modified since applying patch')
    for rel, old_sha in reversed(list(state['originals'].items())):
        dest = target_path(rel)
        if old_sha is None:
            if dest.is_file(): dest.unlink()
        else:
            src = folder/'originals'/rel
            if sha(src.read_bytes()) != old_sha: raise ValueError('Corrupt rollback backup')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    print('Restored original files from:', folder)


def apply(z, ops, force=False):
    if not check(ops, force): return 3
    bdir = backup_root()/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    # Fine-grained changes are backed up before the first file changes.
    bdir.mkdir(mode=0o700)
    originals = {}
    affected = set()
    for op in ops:
        affected.add(op['path'])
        if op['action'] == 'rename': affected.add(op['from'])
    for rel in sorted(affected):
        target = target_path(rel)
        original = target.read_bytes() if target.is_file() else None
        originals[rel] = sha(original) if original is not None else None
        if original is not None:
            dest = bdir/'originals'/rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(original)
            dest.chmod(target.stat().st_mode & 0o777)
    expected = dict(originals)
    for op in ops:
        expected[op['path']] = op.get('sha256') if op['action'] != 'delete' else None
        if op['action'] == 'rename': expected[op['from']] = None
    write_state(bdir, {'originals': originals, 'expected':expected})
    try:
        for op in ops:
            dest = target_path(op['path'])
            if op['action'] in ('delete', 'rename'):
                source = target_path(op['from']) if op['action'] == 'rename' else dest
                if source.is_file(): source.unlink()
            if op['action'] in ('add','modify','rename'):
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Same-filesystem temporary staging enables atomic individual replacements.
                fd, stage = tempfile.mkstemp(dir=dest.parent, prefix='.automation-stage-')
                try:
                    with os.fdopen(fd,'wb') as f:
                        f.write(z.read('payload/'+op['path']))
                        f.flush(); os.fsync(f.fileno())
                    mode = (bdir/'originals'/op['path'])
                    os.chmod(stage, op.get('mode', mode.stat().st_mode & 0o777 if mode.exists() else 0o644))
                    os.replace(stage, dest)
                finally:
                    if Path(stage).exists(): Path(stage).unlink()
        # Safely prune only empty directories left behind by moved/deleted files.
        # Never remove nonempty folders, user data, or unrelated directories.
        for op in ops:
            if op['action'] not in ('delete','rename'):continue
            removed=target_path(op['from']) if op['action']=='rename' else target_path(op['path'])
            parent=removed.parent
            while parent!=ROOT and ROOT in parent.parents:
                try:parent.rmdir()
                except OSError:break
                parent=parent.parent
        # Validate new shell/Python source before marking the patch installed.
        import subprocess
        scripts = sorted(ROOT.rglob('*.sh'))
        for script in scripts:
            if '/.git/' in str(script): continue
            result = subprocess.run(['bash','-n',str(script)], capture_output=True)
            if result.returncode: raise ValueError('Bash validation failed: ' + str(script))
        for py in ROOT.rglob('*.py'):
            import ast
            ast.parse(py.read_bytes(), filename=str(py))
    except BaseException:
        restore(bdir)
        raise
    state_path = bdir/'state.json'
    state = json.loads(state_path.read_text())
    state['applied'] = {rel: sha((ROOT/rel).read_bytes()) if (ROOT/rel).is_file() else None for rel in affected}
    write_state(bdir, state)
    (bdir/'applied').write_text('validated\n')
    print('Applied successfully. Backup:', bdir)
    return 0


def write_state(folder, state):
    fd, stage = tempfile.mkstemp(prefix='.state-', dir=folder)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(state,stream,indent=2); stream.flush(); os.fsync(stream.fileno())
        os.replace(stage,folder/'state.json')
        fd = os.open(folder,os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(stage): os.unlink(stage)


def recover(folder):
    state = json.loads((folder/'state.json').read_text())
    if 'expected' not in state: raise ValueError('This backup has no interrupted-update recovery receipt')
    for rel, original in state['originals'].items():
        path = target_path(rel)
        current = sha(path.read_bytes()) if path.is_file() else None
        if current not in (original,state['expected'].get(rel)):
            raise ValueError('Recovery conflict: '+rel+' was edited outside the patch')
    restore(folder)
    (folder/'recovered').write_text('restored\n')
    if (folder/'applied').exists(): (folder/'applied').unlink()
    return 0


def main(argv=None):
    global ROOT
    p = argparse.ArgumentParser(description='Apply checked, backed-up Toolkit ZIP patches')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', metavar='PATCH')
    mode.add_argument('--apply', metavar='PATCH')
    mode.add_argument('--rollback', nargs='?', const='latest', metavar='BACKUP')
    mode.add_argument('--recover', nargs='?', const='latest', metavar='BACKUP', help='restore an interrupted update after verifying its receipt')
    p.add_argument('--force', action='store_true')
    p.add_argument('--root',type=Path,help='existing toolkit directory (for running the new updater against a prior release)')
    p.add_argument('--allow-unsigned', action='store_true',default=True,help='compatibility flag: local checksum updates do not require signing')
    p.add_argument('--trust-key', action='append',default=[],metavar='PUBLIC_PEM',help='Ed25519 public key obtained from a trusted channel')
    args = p.parse_args(argv)
    if args.root:
        root=args.root.expanduser().absolute()
        if root == Path('/') or not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('Select an existing non-symlink toolkit directory')
        ROOT=root.resolve()
    if args.force and not args.apply: p.error('--force requires --apply')
    lock = ROOT.parent/'.automation-patch.lock'
    with (contextlib.nullcontext(None) if args.check else lock.open('a+')) as f:
        if f is not None:
            try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another update process is running')
        if args.rollback or args.recover:
            base = backup_root()
            choice = args.rollback or args.recover
            marker = 'state.json' if args.recover else 'applied'
            options = sorted(x for x in base.iterdir() if not x.is_symlink() and (x/marker).exists() and not (x/'recovered').exists())
            if choice == 'latest' and not options: raise ValueError('No eligible update backup')
            folder = options[-1] if choice == 'latest' else Path(choice).resolve()
            if folder.parent != base or not (folder/marker).exists():
                raise ValueError('Invalid rollback backup')
            if args.recover: return recover(folder)
            restore(folder, verify_current=True); (folder/'applied').unlink()
            return 0
        patch = Path(args.apply or args.check)
        with zipfile.ZipFile(patch) as z:
            ops = read_zip(z)
            verify_authenticity(z,allow_unsigned=args.allow_unsigned,trust_keys=args.trust_key)
            print('Patch operations:', len(ops))
            if args.check: return 0 if check(ops) else 3
            return apply(z, ops, args.force)

if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print('Update failed:', exc, file=sys.stderr); sys.exit(2)
