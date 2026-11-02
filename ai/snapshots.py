"""Revision-aware model inventory and verified copies; source caches are read-only."""
from __future__ import annotations
import hashlib
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import models

RECEIPT='.automation-snapshot.json'
MAX_FILES=1024
MAX_BYTES=100*1024**3


def revision(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{40}',value):raise ValueError('Pin an exact 40-character lowercase revision')
    return value


def repo_parts(value):
    models.repository(value)
    if '--' in value:raise ValueError('Ambiguous cache repository ID')
    return value.split('/')


def file_path(value):
    if not isinstance(value,str) or len(value)>240:raise ValueError('Invalid snapshot asset path')
    path=PurePosixPath(value)
    if path.is_absolute() or str(path)!=value or len(path.parts)>8 or any(
        not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}',part) or part in ('.','..') for part in path.parts):
        raise ValueError('Noncanonical snapshot asset path')
    if not value.endswith(('.safetensors','.json','.model','.txt','.jinja','.gguf','.tiktoken')):
        raise ValueError('Only model weights/tokenizer/config assets are supported; executable/pickle files are refused')
    return value


def manifest(path):
    path=models.checked_root(path)
    if not path.is_file() or path.stat().st_size>262144:raise ValueError('Manifest must be a bounded regular JSON file')
    return validate(decode(path))


def decode(path, *, limit=262144):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate snapshot JSON field')
            result[key]=value
        return result
    try:
        with path.open('rb') as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('Snapshot JSON exceeds its bounded size')
        return json.loads(raw.decode('utf-8'),object_pairs_hook=unique)
    except (UnicodeError,RecursionError) as exc:raise ValueError('Invalid bounded snapshot JSON') from exc


def validate(value):
    if not isinstance(value,dict) or set(value)!={'schema','repository','revision','files'} or type(value['schema']) is not int or value['schema']!=1:
        raise ValueError('Invalid snapshot manifest schema')
    repo_parts(value['repository']);revision(value['revision'])
    if not isinstance(value['files'],list) or not 1<=len(value['files'])<=MAX_FILES:raise ValueError('Invalid snapshot asset count')
    seen=set();total=0
    for row in value['files']:
        if not isinstance(row,dict) or set(row)!={'path','size','sha256'}:raise ValueError('Invalid snapshot asset schema')
        name=file_path(row['path'])
        if name in seen:raise ValueError('Duplicate snapshot asset')
        seen.add(name)
        if type(row['size']) is not int or not 0<=row['size']<=MAX_BYTES:raise ValueError('Invalid exact snapshot asset size')
        if not isinstance(row['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',row['sha256']):raise ValueError('Every snapshot asset needs an independently verified SHA-256')
        total+=row['size']
    if total>MAX_BYTES:raise ValueError('Snapshot exceeds the 100 GiB bound')
    # Do not silently import a partial GGUF or safetensors shard series.
    groups={}
    for name in seen:
        match=re.fullmatch(r'(.+)-(\d{5})-of-(\d{5})(\.gguf|\.safetensors)',name,re.I)
        if match:
            base,index,count,suffix=match.groups();groups.setdefault((base,suffix),[]).append((int(index),int(count)))
    for shards in groups.values():
        count=shards[0][1]
        if not 1<=count<=MAX_FILES or any(n!=count for _,n in shards) or {i for i,_ in shards}!=set(range(1,count+1)):
            raise ValueError('Incomplete or ambiguous model shard series')
    if len(json.dumps({'schema':1,'observed_copy':True,'manifest':value},sort_keys=True))>262144:
        raise ValueError('Snapshot receipt would exceed its bounded size')
    return value


def entries(path,limit):
    result=[]
    with os.scandir(path) as iterator:
        for entry in iterator:
            result.append(Path(entry.path))
            if len(result)>limit:raise ValueError('Model inventory exceeds its bounded entry count')
    return sorted(result)


def regular(path):
    st=path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid not in (0,os.getuid()) or st.st_mode&0o022:
        raise ValueError('Model asset must be a regular file not writable by others')
    return st


def cache_asset(cache,repo,commit,name):
    owner,model=repo_parts(repo);revision(commit)
    root=models.checked_root(cache)/f'models--{owner}--{model}'
    snapshot=models.checked_root(root/'snapshots'/commit)
    # File symlinks in a Hub snapshot are expected, but they must point to one
    # regular blob in that same repository, never into another cache or home.
    path=snapshot/name
    if any(p.is_symlink() for p in path.parents):raise ValueError('Symlink cache directory is forbidden')
    if path.is_symlink():
        try:resolved=path.resolve(strict=True)
        except RuntimeError as exc:raise ValueError('Cyclic cache asset link') from exc
        except OSError as exc:
            if exc.errno==errno.ELOOP:raise ValueError('Cyclic cache asset link') from exc
            raise
        blobs=models.checked_root(root/'blobs')
        if resolved.parent!=blobs or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',resolved.name):
            raise ValueError('Cache asset link escapes its own repository blobs')
        # Resolve must not hide an intermediate symlink in the blob directory.
        literal=os.path.normpath(path.parent/os.readlink(path))
        if literal!=str(resolved) or (blobs/resolved.name).is_symlink():raise ValueError('Indirect cache blob links are forbidden')
        path=resolved
    else:models.checked_root(path)
    regular(path)
    return path


def inventory(cache):
    cache=models.checked_root(cache)
    if not cache.exists():return []
    if not cache.is_dir():raise ValueError('Cache root must be a directory')
    results=[]
    for folder in entries(cache,4096):
        if not folder.name.startswith('models--'):continue
        pieces=folder.name.split('--')
        if len(pieces)!=3:continue
        repo='/'.join(pieces[1:]);repo_parts(repo)
        models.checked_root(folder)
        revisions=folder/'snapshots'
        if not revisions.exists():continue
        models.checked_root(revisions)
        for snapshot in entries(revisions,1024):
            revision(snapshot.name);models.checked_root(snapshot)
            pending=[snapshot];files=0;size=0;visited=0
            while pending:
                parent=pending.pop()
                if len(parent.relative_to(snapshot).parts)>8:raise ValueError('Cache tree is too deep')
                for path in entries(parent,MAX_FILES):
                    visited+=1
                    if visited>MAX_FILES*9:raise ValueError('Cache snapshot has too many entries')
                    if path.is_dir() and not path.is_symlink():pending.append(path);continue
                    files+=1
                    if files>MAX_FILES:raise ValueError('Cache snapshot has too many assets')
                    relative=path.relative_to(snapshot).as_posix()
                    # Inventory does not execute or authorize any file type.
                    asset=cache_asset(cache,repo,snapshot.name,relative)
                    size+=asset.stat().st_size
            results.append({'repository':repo,'revision':snapshot.name,'files':files,'bytes':size,
                'ownership':'external cache; inventory grants no deletion rights'})
            if len(results)>4096:raise ValueError('Too many cached revisions')
    return results


def destination(root,value):
    root=models.checked_root(root)
    source=Path(__file__).resolve().parents[1]
    if root==source or source in root.parents:raise ValueError('Store model snapshots outside the toolkit source tree')
    owner,model=repo_parts(value['repository'])
    for path in (root,root/owner,root/owner/model):private_directory(path)
    return models.checked_root(root/owner/model/revision(value['revision']))


def private_directory(path, *, create=False):
    path=models.checked_root(path)
    if create:
        missing=[];parent=path
        while not parent.exists():missing.append(parent);parent=parent.parent
        for folder in reversed(missing):
            folder.mkdir(mode=0o700,exist_ok=True)
            if folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:raise ValueError('New snapshot directory must be private and owned')
    if path.exists() and (not path.is_dir() or path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077):
        raise ValueError('Toolkit snapshot directories must be private and owned (0700)')
    return path


def verify_asset(path,row):
    models.checked_root(path);st=regular(path)
    if st.st_size!=row['size'] or models.digest(path)!=row['sha256']:raise ValueError('Model asset differs from the independently verified manifest')


def owned(target,value=None):
    target=models.checked_root(target);private_directory(target)
    receipt=target/RECEIPT
    models.checked_root(receipt);st=regular(receipt)
    if st.st_mode&0o077 or st.st_nlink!=1 or st.st_size>262144:raise ValueError('Unsafe snapshot receipt')
    record=decode(receipt)
    if not isinstance(record,dict) or set(record)!={'schema','observed_copy','manifest'} or type(record['schema']) is not int or record['schema']!=1 or record['observed_copy'] is not True:
        raise ValueError('Removal requires an observed toolkit-copy receipt')
    recorded=validate(record['manifest'])
    if value is not None and recorded!=value:raise ValueError('Snapshot identity/manifest conflicts with its receipt')
    expected={row['path'] for row in recorded['files']};found=set();pending=[target];directories=set()
    expected_dirs={str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent)!='.'}
    while pending:
        parent=pending.pop()
        if len(parent.relative_to(target).parts)>8:raise ValueError('Snapshot tree is too deep')
        for path in entries(parent,MAX_FILES+1):
            models.checked_root(path)
            if path.is_dir():
                private_directory(path);directories.add(path.relative_to(target).as_posix())
                if len(directories)>MAX_FILES*8:raise ValueError('Unexpected snapshot directories')
                pending.append(path)
            elif path!=receipt:
                found.add(path.relative_to(target).as_posix())
                if len(found)>MAX_FILES:raise ValueError('Unexpected snapshot assets')
    if found!=expected or directories!=expected_dirs:raise ValueError('Snapshot has missing or subsequent user files/directories; operation refused')
    for row in recorded['files']:
        path=target/row['path']
        if path.stat().st_nlink!=1 or path.stat().st_mode&0o777!=0o600:raise ValueError('Snapshot asset links/permissions changed; refusing ownership/deletion')
        verify_asset(path,row)
    return recorded


def import_snapshot(root,value, *, cache=None,source=None,yes=False,dry_run=False):
    value=validate(value);target=destination(root,value)
    if bool(cache)==bool(source):raise ValueError('Select exactly one --cache-root or --source-dir')
    source=models.checked_root(source) if source else None
    if source and (target==source or source in target.parents or target in source.parents):raise ValueError('Source and snapshot destination cannot overlap')
    if cache:
        cache=models.checked_root(cache)
        if target==cache or cache in target.parents or target in cache.parents:raise ValueError('Cache and snapshot destination cannot overlap')
    if target.exists():
        owned(target,value);print('Verified toolkit snapshot reused; original cache preserved.');return 0
    sources=[]
    for row in value['files']:
        asset=cache_asset(cache,value['repository'],value['revision'],row['path']) if cache else models.checked_root(source/row['path'])
        verify_asset(asset,row);sources.append(asset)
    if dry_run:print('Dry run: would copy the verified revision into a separate private snapshot; no cache or model changed.');return 0
    if not yes:print('Snapshot copy requires --yes after independent checksum/size review.');return 4
    parent=Path(root).expanduser()
    ancestor=parent
    while not ancestor.exists():ancestor=ancestor.parent
    size=sum(row['size'] for row in value['files'])
    if shutil.disk_usage(ancestor).free<size+64*1024**2:raise ValueError('Insufficient disk space for a separate verified model copy')
    private_directory(parent,create=True)
    # Staging is private; nothing in the external cache is linked or modified.
    with tempfile.TemporaryDirectory(prefix='.snapshot-',dir=parent) as directory:
        stage=Path(directory)
        for row,asset in zip(value['files'],sources):
            copy=stage/row['path'];copy.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with asset.open('rb') as incoming,copy.open('xb') as outgoing:
                os.chmod(copy,0o600);hashed=hashlib.sha256();total=0
                while True:
                    chunk=incoming.read(min(1024**2,row['size']-total+1))
                    if not chunk:break
                    total+=len(chunk)
                    if total>row['size']:raise ValueError('Source model grew during copy')
                    hashed.update(chunk);outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            if total!=row['size'] or hashed.hexdigest()!=row['sha256']:raise ValueError('Source model changed during copy; no snapshot activated')
        for folder in (target.parent.parent,target.parent):private_directory(folder,create=True)
        target.mkdir(mode=0o700)  # exclusive reservation; never overwrite even an empty directory
        # Publish verified files exclusively, then commit the receipt last. A
        # caught interruption preserves an incomplete directory without ownership.
        for row in value['files']:
            path=target/row['path'];path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            os.link(stage/row['path'],path)
        models.atomic_receipt(stage/RECEIPT,{'schema':1,'observed_copy':True,'manifest':value})
        os.link(stage/RECEIPT,target/RECEIPT)
    owned(target,value)
    print('Verified snapshot copied:',target,'; original models/cache preserved.');return 0


def remove_snapshot(root,repo,commit, *, yes=False,dry_run=False):
    identity={'repository':repo,'revision':commit}
    target=destination(root,identity);value=owned(target)
    if value['repository']!=repo or value['revision']!=commit:raise ValueError('Snapshot receipt identity mismatch')
    if dry_run:print('Dry run: would remove only this verified toolkit copy; external cache is never deleted.');return 0
    if not yes:print('Snapshot removal requires --yes.');return 4
    # The toolkit can establish only the state of its own recorded services.
    # Never stop a server or delete its configured model as a side effect.
    import services
    for backend in ('llamacpp','vllm'):
        config,unit=services.paths(backend)
        if not config.exists() or not unit.exists():continue
        services.owned(backend)
        configured=Path(services.read(backend)['model'])
        if configured==target or target in configured.parents:
            import subprocess
            cp=subprocess.run(['systemctl','--user','show',unit.name,'--property=ActiveState','--value'],capture_output=True,text=True,timeout=10)
            if cp.returncode or cp.stdout.strip() not in ('inactive','failed'):
                raise ValueError('Stop the configured toolkit service explicitly before removing its snapshot')
    # Revalidate before the first deletion. Delete exact receipt files only;
    # unknown directories/files are never recursively removed.
    owned(target,value)
    for row in value['files']:verify_asset(target/row['path'],row)
    for row in value['files']:(target/row['path']).unlink()
    directories={parent for row in value['files'] for parent in (target/row['path']).parents if target in parent.parents}
    for folder in sorted(directories,key=lambda p:len(p.parts),reverse=True):folder.rmdir()
    (target/RECEIPT).unlink();target.rmdir()
    print('Removed verified toolkit snapshot copy; external cache preserved.');return 0
