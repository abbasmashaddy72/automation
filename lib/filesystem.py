"""Generic local path and data-file helpers, independent of server provisioning."""

import os
from pathlib import Path
import stat
import tempfile


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def checked(path):
    path = Path(path).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Symlink paths are not permitted")
    return path.resolve()


def read_regular(path, *, limit, missing=False, private=False, owned=True):
    path = checked(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if missing:
            return None
        raise
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(st.st_mode)
            or (owned and st.st_uid != os.getuid())
            or st.st_nlink != 1
            or st.st_size > limit
            or (private and st.st_mode & 0o077)
        ):
            raise ValueError("Expected a bounded, owned regular file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Input exceeds size limit")
        return data


def atomic(path, data, mode=0o600):
    path = checked(path)
    fd, temporary = tempfile.mkstemp(prefix=".automation-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
