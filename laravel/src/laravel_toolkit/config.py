"""One bounded Laravel-specific .env, never sourced or expanded."""
from __future__ import annotations
import os
from pathlib import Path
import re
import tempfile
from . import common

ROOT=Path(__file__).resolve().parents[2]
DEFAULTS=ROOT/'config/defaults.env'


def parse(path):
    path=common.checked(path)
    if not path.exists():return {}
    st=path.stat()
    if not path.is_file() or st.st_nlink!=1 or st.st_size>65536 or st.st_mode&0o022:raise ValueError('Unsafe toolkit configuration file')
    if path.name=='.env' and (st.st_mode&0o077 or (os.geteuid()!=0 and st.st_uid!=os.geteuid())):
        raise ValueError('Laravel .env must be private (0600) and owned by the current user')
    result={}
    for number,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip() or line.lstrip().startswith('#'):continue
        match=re.fullmatch(r'([A-Z_]+)=(.*)',line)
        if not match:raise ValueError('Invalid Laravel configuration syntax at line '+str(number))
        key,value=match.groups()
        if key in result:raise ValueError('Duplicate Laravel configuration field')
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
        if any(token in value for token in ('$','`','\0','\r')):raise ValueError('Executable/interpolated configuration is not supported')
        result[key]=value
    return result


def validate(value,keys):
    if set(value)-set(keys):raise ValueError('Unknown Laravel toolkit configuration field')
    for key,choices in {'LARAVEL_DATABASE':('none','mariadb','postgresql'),'LARAVEL_CACHE':('none','redis','valkey'),
        'LARAVEL_QUEUE':('none','queue','horizon'),'LARAVEL_FRONTEND':('auto','none'),
        'LARAVEL_AUTO_PREREQUISITES':('true','false'),'LARAVEL_SCHEDULER':('true','false')}.items():
        if key in value and value[key] not in choices:raise ValueError('Invalid choice for '+key)
    if 'LARAVEL_RETAIN' in value and (not value['LARAVEL_RETAIN'].isascii() or not value['LARAVEL_RETAIN'].isdigit() or not 2<=int(value['LARAVEL_RETAIN'])<=100):
        raise ValueError('LARAVEL_RETAIN must be 2–100')
    for key in ('LARAVEL_SITE_ROOT',):
        if value.get(key):common.site_path(value[key])
    if value.get('LARAVEL_DOMAIN'):common.domain(value['LARAVEL_DOMAIN'])
    if value.get('LARAVEL_DEPLOY_USER'):common.username(value['LARAVEL_DEPLOY_USER'])
    if value.get('LARAVEL_PHP_VERSION') and not re.fullmatch(r'8\.[0-9]{1,2}',value['LARAVEL_PHP_VERSION']):raise ValueError('Invalid configured PHP version')
    return value


def load():
    defaults=parse(DEFAULTS)
    local=validate(parse(ROOT/'.env'),defaults)
    return validate({**defaults,**local},defaults)


def init(*,yes=False,dry_run=False):
    defaults=parse(DEFAULTS);path=ROOT/'.env';existing=validate(parse(path),defaults)
    missing={key:value for key,value in defaults.items() if key not in existing}
    if dry_run:return {'missing':sorted(missing),'written':False}
    if not yes:raise ValueError('Configuration initialization requires --yes')
    original=path.read_bytes() if path.exists() else None
    if original is not None and not missing:
        if os.geteuid()==0 or path.stat().st_uid==os.geteuid():path.chmod(0o600)
        return {'missing':[],'written':False}
    data=original or b''
    if data and not data.endswith(b'\n'):data+=b'\n'
    data+=b'# Safe missing defaults added by Laravel toolkit\n'
    data+=''.join(key+'='+value+'\n' for key,value in missing.items()).encode()
    fd,stage=tempfile.mkstemp(prefix='.laravel-env-',dir=ROOT)
    try:
        os.fchmod(fd,0o600)
        if original is not None and os.geteuid()==0:os.fchown(fd,path.stat().st_uid,path.stat().st_gid)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        if original is None:
            os.link(stage,path)  # exclusive; never overwrite a concurrent creator
        else:
            if path.is_symlink() or path.read_bytes()!=original:raise ValueError('Configuration changed during initialization')
            os.replace(stage,path)
    finally:
        if os.path.exists(stage):os.unlink(stage)
    return {'missing':sorted(missing),'written':True}


def optional(value):return value if value else None


def relative_file(value):
    if not value:return None
    path=Path(value).expanduser()
    return common.checked(path if path.is_absolute() else ROOT/path)
