"""Shared production validation and transactional files; never loads shell config."""
from __future__ import annotations
import base64
import contextlib
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import tempfile
import urllib.parse
import uuid


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON field')
        result[key]=value
    return result


def read_json(path,limit=1048576):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:raise ValueError('Unsafe or oversized JSON file')
    return json.loads(path.read_text(),object_pairs_hook=unique)


def digest(data):return hashlib.sha256(data).hexdigest()


def file_digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):value.update(chunk)
    return value.hexdigest()


def checked(path):
    path=Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlink path is not allowed here')
    return path.resolve()


def domain(value):
    if (not isinstance(value,str) or len(value)>253 or '.' not in value
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.'))):
        raise ValueError('Provide a lowercase DNS domain without scheme, port or path')
    return value


def username(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}',value) or value=='root':
        raise ValueError('Provide a dedicated non-root deployment user')
    return value


def site_path(value):
    path=checked(value)
    source=Path(__file__).resolve().parents[2]
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(path)) or path==source or source in path.parents:
        raise ValueError('Site paths must be literal paths outside the toolkit source tree')
    blocked=('/etc','/usr','/bin','/sbin','/boot','/dev','/proc','/sys','/root')
    if path in (Path('/'),Path('/var'),Path('/var/www'),Path('/tmp'),Path.home()):raise ValueError('Select a dedicated site directory')
    if any(path==Path(p) or Path(p) in path.parents for p in blocked):raise ValueError('System directories cannot be site roots')
    return path


def private(path, *, directory=False):
    path=checked(path);st=path.stat()
    if (st.st_uid!=os.geteuid() or st.st_mode&0o077 or (not directory and (not stat.S_ISREG(st.st_mode) or st.st_nlink!=1))):
        raise ValueError('State/secrets must be private and owned by the executing user')
    return path


def atomic(path,data,mode=0o600):
    path=checked(path)
    fd,stage=tempfile.mkstemp(prefix='.automation-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(stage,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(stage):os.unlink(stage)


def save(path,value):atomic(path,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


@contextlib.contextmanager
def lock(path):
    path=checked(path)
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1 or not stat.S_ISREG(st.st_mode):raise ValueError('Unsafe operation lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another operation holds this lock') from None
        yield
    finally:os.close(fd)


def run(argv, *, cwd=None, env=None, data=None, timeout=900, label=None):
    # Application scripts and external provisioners may print credentials. Keep
    # their output out of ordinary logs; return bounded diagnostics to callers.
    with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
        result=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,input=data,
            stdout=out,stderr=err,timeout=timeout)
        out.seek(0);stdout=out.read(1048577)
        err.seek(0);stderr=err.read(1048577)
    if result.returncode:raise ValueError((label or Path(argv[0]).name)+' failed (exit '+str(result.returncode)+'); output withheld to protect credentials')
    if len(stdout)>1048576 or len(stderr)>1048576:raise ValueError('Command output exceeded the bounded response limit')
    return stdout.decode('utf-8',errors='replace')


def https_url(url):
    value=urllib.parse.urlsplit(url)
    if (value.scheme!='https' or not value.hostname or value.username or value.password or value.fragment or value.query
            or any(ord(c)<33 for c in url) or '\\' in url):raise ValueError('Use an HTTPS URL without credentials, query, fragments or whitespace')
    host=value.hostname.encode('idna').decode('ascii').lower()
    if host=='forge.laravel.com' or host.endswith('.forge.laravel.com'):raise ValueError('Forge-hosted provisioning endpoints are not supported')
    port=value.port or 443
    if not 1<=port<=65535:raise ValueError('Invalid HTTPS port')
    return value,host,port


def fetch(url,limit=2097152):
    value,host,port=https_url(url)
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('HTTPS destination must resolve exclusively to public addresses')
    # Pin the validated address while retaining the original TLS hostname. No
    # environment proxies, second DNS lookup or redirect is permitted.
    connection=http.client.HTTPSConnection(host,port,timeout=25,context=ssl.create_default_context())
    connection._create_connection=lambda address,timeout=None,source_address=None,**kwargs:socket.create_connection((ips[0],port),timeout,source_address)
    try:
        connection.request('GET',value.path or '/',headers={'User-Agent':'AutomationToolkit/1'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('HTTPS download refused: non-200 response or redirect')
        body=response.read(limit+1)
        if len(body)>limit:raise ValueError('HTTPS download exceeded size limit')
        return body
    finally:connection.close()


def verified_script(url,sha256):
    if not isinstance(sha256,str) or not re.fullmatch('[a-f0-9]{64}',sha256):raise ValueError('Provide an independently verified SHA-256')
    body=fetch(url)
    if digest(body)!=sha256:raise ValueError('Provisioning script checksum mismatch')
    if b'\0' in body or not body.lstrip().startswith(b'#!'):raise ValueError('Expected a text shell script with a shebang')
    body.decode('utf-8')
    run(['bash','-n'],data=body,label='External script syntax validation',timeout=15)
    return body


class ManagedFiles:
    """Only previously observed owned configurations may be replaced."""
    def __init__(self,state):
        self.state=checked(state);self.registry=self.state/'managed-files.json';self.pending=self.state/'managed-files.pending.json'
    def recover(self):
        if not self.pending.exists():return
        private(self.pending)
        intent=read_json(self.pending)
        if not isinstance(intent,dict) or set(intent)!={'schema','backup','after'} or intent['schema']!=1 or not re.fullmatch(r'backup-[a-f0-9]{32}\.json',intent['backup']):raise ValueError('Invalid configuration recovery receipt')
        backup=private(self.state/intent['backup']);originals=read_json(backup)
        if not isinstance(intent['after'],dict) or set(originals)!=set(intent['after']):raise ValueError('Incomplete configuration recovery receipt')
        registry=read_json(self.registry) if self.registry.exists() else {}
        committed=all(registry.get(name)==value for name,value in intent['after'].items())
        plans=[]
        for name,entry in originals.items():
            path=checked(name)
            if set(entry)!={'before','mode'} or not isinstance(entry['mode'],int) or not 0<=entry['mode']<=0o777:raise ValueError('Invalid configuration backup')
            before=None if entry['before'] is None else base64.b64decode(entry['before'],validate=True)
            observed=path.read_bytes() if path.exists() else None
            if observed!=before and (observed is None or digest(observed)!=intent['after'][name]):raise ValueError('Later configuration edits prevent interrupted recovery: '+path.name)
            plans.append((path,before,entry['mode']))
        if not committed:
            for path,before,mode in plans:
                if before is None:
                    if path.exists():path.unlink()
                else:atomic(path,before,mode)
        self.pending.unlink()

    def apply(self,files,validate):
        self.recover()
        registry=read_json(self.registry) if self.registry.exists() else {}
        if not isinstance(registry,dict):raise ValueError('Invalid managed-file registry')
        originals={}
        for path,(data,mode) in files.items():
            path=checked(path)
            before=path.read_bytes() if path.exists() else None
            if before is not None:
                st=path.stat()
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1 or st.st_mode&0o022:
                    raise ValueError('Existing managed configuration has unsafe ownership or permissions')
            if before is not None and registry.get(str(path))!=digest(before):raise ValueError('Unowned or subsequently edited configuration: '+path.name)
            originals[path]=(before,path.stat().st_mode&0o777 if before is not None else mode)
        backup=self.state/('backup-'+uuid.uuid4().hex+'.json')
        save(backup,{str(p):{'before':None if b is None else base64.b64encode(b).decode(),'mode':m} for p,(b,m) in originals.items()})
        save(self.pending,{"schema":1,"backup":backup.name,"after":{str(path):digest(value[0]) for path,value in files.items()}})
        try:
            for path,(data,mode) in files.items():
                path.parent.mkdir(parents=True,exist_ok=True)
                if originals[path][0]!=data:atomic(path,data,mode)
            validate()
        except BaseException:
            for path,(before,mode) in originals.items():
                if not path.exists() or path.is_symlink() or path.read_bytes()!=files[path][0]:continue
                if before is None:path.unlink()
                else:atomic(path,before,mode)
            # Keep intent when a concurrent edit prevents complete restoration.
            if all((not path.exists() if before is None else path.exists() and not path.is_symlink() and path.read_bytes()==before) for path,(before,mode) in originals.items()):self.pending.unlink()
            raise
        registry.update({str(p):digest(value[0]) for p,value in files.items()})
        save(self.registry,registry)
        self.pending.unlink()
