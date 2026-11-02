"""Minimal non-destructive installation journal; a receipt, not OS rollback.

No credentials, environment values, installer command lines, or model paths are
recorded. Resume means rerunning an installation; native package checks remain
idempotent and existing package-manager transactions are not reversed.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import time
import uuid


def state_dir(configured='', *, create=True):
    target = Path(configured).expanduser() if configured else Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state'))) / 'automation-toolkit'
    if not target.is_absolute() or target.is_symlink():
        raise ValueError('State directory must be an absolute, non-symlink path')
    # Reject world-writable ancestor files/paths except for sticky /tmp or
    # /var/tmp; a private child dir protects actual journal contents.
    for parent in (target,*target.parents):
        if parent.is_symlink(): raise ValueError('Symlink ancestor in state directory')
    if not create and not target.exists(): return target
    if create: target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.stat().st_uid != os.geteuid() or (target.stat().st_mode & 0o077):
        raise ValueError('State directory must be owned by the current user and private (0700)')
    return target


def write(event, *, directory='', session=None, packages=(), source='', result=None):
    if event not in ('started','action','finished','failed','partial'):
        raise ValueError('Invalid journal event')
    root=state_dir(directory)
    path=root/'install-journal.jsonl'
    if path.is_symlink(): raise ValueError('Journal cannot be a symlink')
    item={'timestamp':int(time.time()),'session':session or '', 'event':event,
          'packages':list(packages), 'source':source}
    if result is not None: item['exit_code']=int(result)
    flags=os.O_WRONLY|os.O_APPEND|os.O_CREAT | getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_uid!=os.geteuid() or os.fstat(fd).st_mode & 0o077:
            raise ValueError('Journal must be a private regular file')
        with os.fdopen(fd,'a') as f:
            fd=-1
            f.write(json.dumps(item,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
    finally:
        if fd >= 0: os.close(fd)
    return item


def status(*, directory=''):
    path=state_dir(directory,create=False)/'install-journal.jsonl'
    if not path.exists(): return {'status':'none','message':'No installation journal found'}
    if path.is_symlink() or path.stat().st_size>10_000_000: raise ValueError('Unsafe journal')
    latest={}
    for line in path.read_text().splitlines():
        row=json.loads(line)
        if row.get('session'): latest[row['session']]=row
    if not latest: return {'status':'none'}
    last=list(latest.values())[-1]
    return {'status':'recorded','latest':last,'pending':pending(directory=directory,session=last['session']),
            'note':'Rerun the same install command to recheck packages; this journal does NOT undo system changes.'}


def _read_records(directory=''):
    path=state_dir(directory,create=False)/'install-journal.jsonl'
    if not path.exists():return []
    if path.is_symlink() or path.stat().st_size>10_000_000:raise ValueError('Unsafe journal')
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def pending(*,directory='',session=None):
    """Read-only incomplete logical selections; never automatically resume actions."""
    records=_read_records(directory)
    if not records:return []
    if session is None:
        sessions=[r['session'] for r in records if r.get('event')=='started' and r.get('session')]
        if not sessions:return []
        session=sessions[-1]
    rows=[r for r in records if r.get('session')==session]
    started=next((r for r in rows if r.get('event')=='started'),None)
    if not started:return []
    done={name for r in rows if r.get('event')=='action' and r.get('exit_code')==0
          for name in r.get('packages',[])}
    return [name for name in started.get('packages',[]) if name not in done]


def _owned_path(directory=''):
    return state_dir(directory)/'owned.json'


def owned(*,directory=''):
    path=state_dir(directory,create=False)/'owned.json'
    if not path.exists():return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000:
        raise ValueError('Unsafe ownership registry')
    if path.stat().st_uid!=os.geteuid() or path.stat().st_mode & 0o077:
        raise ValueError('Ownership registry must be private')
    raw=json.loads(path.read_text())
    if not isinstance(raw,dict):raise ValueError('Invalid ownership registry')
    return raw


def record_ownership(requested,package,source,*,directory='',verified=False):
    """Record ONLY installs confirmed post-action; no uninstall rights implied."""
    import re
    if not verified:raise ValueError('Cannot claim unverified installation')
    for x in (requested,package,source):
        if not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+._-]{0,95}',x):
            raise ValueError('Invalid ownership record')
    root=state_dir(directory)
    path=root/'owned.json'
    current=owned(directory=directory)
    if requested in current:return current[requested]
    item={'package':package,'source':source,'verified_at':int(time.time()),
          'removable':False,'note':'Observed newly installed; never auto-uninstall'}
    current[requested]=item
    import tempfile
    fd,temp=tempfile.mkstemp(prefix='.owned-',dir=root)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:
            fd=-1
            json.dump(current,f,sort_keys=True,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if fd>=0:os.close(fd)
        if os.path.exists(temp):os.unlink(temp)
    return item


def new_session():
    return uuid.uuid4().hex
