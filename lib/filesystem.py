"""Generic local path and data-file helpers, independent of server provisioning."""
import json
import os
from pathlib import Path
import tempfile


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON field')
        result[key]=value
    return result


def checked(path):
    path=Path(path).expanduser().absolute()
    if any(part.is_symlink() for part in (path,*path.parents)):raise ValueError('Symlink paths are not permitted')
    return path.resolve()


def atomic(path,data,mode=0o600):
    path=checked(path);fd,temporary=tempfile.mkstemp(prefix='.automation-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
