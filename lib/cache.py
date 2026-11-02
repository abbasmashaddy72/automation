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

TTL=600
PERSIST = False  # CLI enables disk writes only for approved mutating workflows.

def directory():
    base=Path(os.environ.get('XDG_CACHE_HOME', str(Path.home()/'.cache'))).expanduser()
    return base/'automation-toolkit'/'repository-metadata'


def _key(parts):
    return hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()


def get(parts, *, ttl=TTL, folder=None):
    folder=Path(folder) if folder is not None else directory()
    path=folder/(_key(parts)+'.json')
    if path.is_symlink():return None
    try:
        if time.time()-path.stat().st_mtime>ttl:return None
        data=json.loads(path.read_text())
        return data['value'] if data.get('key')==parts else None
    except (OSError,ValueError,KeyError,TypeError):return None


def put(parts,value,*,folder=None):
    if folder is None and not PERSIST: return False
    folder=Path(folder) if folder is not None else directory()
    if folder.is_symlink():return False
    try:
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(folder,0o700)
        path=folder/(_key(parts)+'.json')
        if path.is_symlink():return False
        temp=path.with_suffix('.tmp-'+str(os.getpid()))
        with temp.open('x') as f:
            os.fchmod(f.fileno(),0o600)
            json.dump({'key':parts,'value':value},f)
        os.replace(temp,path)
        return True
    except (OSError,TypeError,ValueError):return False


def clear(*,folder=None):
    folder=Path(folder) if folder is not None else directory()
    if folder.is_symlink() or not folder.is_dir():return 0
    count=0
    for path in folder.glob('*.json'):
        if not path.is_symlink():
            path.unlink();count+=1
    return count
