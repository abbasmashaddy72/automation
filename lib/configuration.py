"""Safe default configuration creation. Existing values are never rewritten."""
from __future__ import annotations
import os
from pathlib import Path
import stat
import tempfile


def ensure(root, parse, validate):
    root = Path(root)
    defaults = root / 'config/defaults.env'
    target = root / '.env'
    for path in (root, defaults, target):
        if path.is_symlink():
            raise ValueError('Symlink configuration paths are forbidden')
    wanted = validate(parse(defaults))
    if target.exists():
        st = target.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise ValueError('Configuration must be a regular file owned by the current user')
    existing = validate(parse(target))
    missing = {k: v for k, v in wanted.items() if k not in existing}
    if not missing and target.exists():
        target.chmod(0o600)
        return target
    original = target.read_bytes() if target.exists() else b''
    data = original + (b'\n' if original and not original.endswith(b'\n') else b'')
    data += b'# Safe defaults added by Automation Toolkit\n'
    data += ''.join(f'{k}={v}\n' for k, v in missing.items()).encode()
    fd, stage = tempfile.mkstemp(prefix='.config-', dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            if target.is_symlink() or target.read_bytes() != original:
                raise ValueError('Configuration changed during merge; retry')
            os.replace(stage, target)
        else:
            # link is exclusive: a concurrent creator is never overwritten.
            os.link(stage, target)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
    return target
