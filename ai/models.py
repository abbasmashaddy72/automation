"""Explicit checksum-pinned GGUF downloads; never touches shared model caches."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import ai_health


def catalogue_json(url, *, limit=262144):
    """Public metadata only: no credentials, proxies, redirects or unbounded JSON."""
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='huggingface.co' or not parsed.path.startswith('/api/models'):
        raise ValueError('Only the public Hugging Face model API is permitted')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'LinuxAutomationToolkit/3'}),timeout=10) as response:
        raw=response.read(limit+1)
        if response.status!=200 or len(raw)>limit:raise ValueError('Invalid model catalogue response')
    return json.loads(raw)


def repository(value):
    if not isinstance(value,str) or len(value)>200 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*',value):
        raise ValueError('Provide a literal publisher/model repository ID')
    if any('..' in component for component in value.split('/')):raise ValueError('Noncanonical repository ID')
    return value


def search(query, *, backend='llamacpp', limit=10, rank=None, scope='hub', offset=0):
    """Read-only publisher model discovery; results never authorize downloads."""
    if not isinstance(query,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ /-]{0,95}',query):
        raise ValueError('Use a short literal model name or publisher query')
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('Model search limit must be 1–50')
    if rank not in (None,'downloads','likes','trending') or scope not in ('hub','warm') or type(offset) is not int or not 0<=offset<=10000:
        raise ValueError('Invalid model catalogue ranking, scope or page offset')
    params={'search':query,'limit':str(limit)}
    if backend=='llamacpp':params['filter']='gguf'
    else:params['pipeline_tag']='text-generation'
    if rank:params.update(sort={'trending':'trendingScore'}.get(rank,rank),direction='-1')
    if offset:params['skip']=str(offset)
    if scope=='warm':params['inference_provider']='all'
    url='https://huggingface.co/api/models?'+urllib.parse.urlencode(params)
    data=catalogue_json(url)
    if not isinstance(data,list):raise ValueError('Invalid model catalogue schema')
    results=[]
    for row in data[:limit]:
        name=row.get('id') if isinstance(row,dict) else None
        try:repository(name)
        except ValueError:continue
        if name not in {x['model'] for x in results}:
            results.append({'model':name,'url':'https://huggingface.co/'+name,
                'note':'Discovery only: ranking is Hub activity, not quality or runtime compatibility; warm means hosted inference availability. Inspect license, hardware, exact size and independent SHA-256 before downloading'})
    return results


def model_files(repo,revision, *, backend='llamacpp',quant=None):
    repository(repo)
    if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Pin an exact 40-character lowercase commit revision')
    if backend not in ('llamacpp','vllm'):raise ValueError('Unsupported model-file backend')
    if quant is not None and (backend!='llamacpp' or not re.fullmatch('[A-Za-z0-9_]{1,32}',quant)):raise ValueError('Use a literal GGUF quantization')
    data=catalogue_json(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true',limit=1048576)
    if not isinstance(data,dict) or data.get('sha')!=revision or data.get('id')!=repo or not isinstance(data.get('siblings'),list) or len(data['siblings'])>4096:
        raise ValueError('Model repository, revision or file schema mismatch')
    files=[];seen=set()
    for row in data['siblings']:
        if not isinstance(row,dict):raise ValueError('Invalid model file metadata')
        name=row.get('rfilename')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}',name):continue
        if name in seen:raise ValueError('Duplicate model filename')
        seen.add(name)
        if backend=='llamacpp':
            if not name.lower().endswith('.gguf') or 'mmproj' in name.lower():continue
            if quant and not re.search(r'[-_]'+re.escape(quant)+r'(?=-\d{5}-of-\d{5}\.gguf$|\.gguf$)',name,re.I):continue
        elif not name.endswith(('.safetensors','.json','.model','.txt','.jinja')):continue
        lfs=row.get('lfs');lfs=lfs if isinstance(lfs,dict) else {}
        size=row.get('size',lfs.get('size'));checksum=lfs.get('sha256')
        if type(size) is not int or not 0<=size<=100*1024**3:raise ValueError('Missing or invalid exact model file size')
        if checksum is not None and (not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum)):raise ValueError('Invalid SHA-256 metadata')
        files.append({'name':name,'size':size,'publisher_sha256':checksum,
            'url':f'https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name,safe="")}'})
    groups={}
    for row in files:
        match=re.fullmatch(r'(.+)-(\d{5})-of-(\d{5})\.gguf',row['name'],re.I)
        if match:
            base,index,total=match.groups();groups.setdefault(base,[]).append((int(index),int(total)))
    for shards in groups.values():
        total=shards[0][1]
        if not 1<=total<=4096 or any(count!=total for _,count in shards) or {i for i,_ in shards}!=set(range(1,total+1)):
            raise ValueError('Incomplete or ambiguous GGUF shard series; refusing a partial selection')
    return {'repository':repo,'revision':revision,'files':files,
        'note':'Metadata only. Independently verify SHA-256 and size before explicit downloads. No model code is executed; no files or receipts are created.'}


def checked_root(root, *, create=False):
    root = Path(root).expanduser()
    if not root.is_absolute() or root == Path('/'):
        raise ValueError('Model directory must be absolute and non-root')
    for part in (root, *root.parents):
        if part.is_symlink(): raise ValueError('Symlink model directories are forbidden')
    root=root.resolve()
    if root==Path('/'): raise ValueError('Model directory cannot resolve to the filesystem root')
    if create: root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def filename(value):
    if not value or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,175}\.gguf', value):
        raise ValueError('Select one plain GGUF filename, without directories')
    return value


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def https_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Model URL must be explicit HTTPS without credentials or fragments')
    return value


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def atomic_receipt(path, record):
    fd, stage = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        if os.path.exists(stage): os.unlink(stage)


def download(root, name, url, checksum, size, *, yes=False, dry_run=False):
    root = checked_root(root)
    name = filename(name); https_url(url)
    if not checksum or not re.fullmatch('[a-f0-9]{64}', checksum):
        raise ValueError('An independently verified SHA-256 is required')
    if not isinstance(size, int) or not 4 <= size <= 100*1024**3:
        raise ValueError('Exact expected model size is required (4 bytes–100 GiB)')
    target = root/name
    receipt = root/(name + '.receipt.json')
    if target.is_symlink() or receipt.is_symlink(): raise ValueError('Symlink model/receipt is forbidden')
    if receipt.exists():
        if not receipt.is_file() or receipt.stat().st_size>4096: raise ValueError('Invalid preexisting model receipt')
        if json.loads(receipt.read_text()) != {'format':1,'name':name,'sha256':checksum,'size':size}:
            raise ValueError('Existing receipt differs; refusing to overwrite it')
    if target.exists():
        if target.is_file() and target.stat().st_size == size and digest(target) == checksum:
            with target.open('rb') as stream:
                if stream.read(4)!=b'GGUF':raise ValueError('Cached model has an invalid GGUF header')
            print('Verified cached model reused; no download.'); return 0
        raise ValueError('Existing model differs; refusing to overwrite it')
    if dry_run:
        print(f'Dry run: would verify/download {name} ({size} bytes), preserving existing models.'); return 0
    if not yes: print('Model download requires --yes.'); return 4
    ancestor = root
    while not ancestor.exists(): ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < size + max(64*1024**2, size//20):
        raise ValueError('Insufficient free disk space for model and safety reserve')
    hardware = ai_health.hardware()
    ram = hardware.get('available_memory_mib')
    if ram is None:ram=hardware.get('memory_mib')
    if ram is None or ram*1024**2 < size + 256*1024**2:
        raise ValueError('Insufficient or unknown RAM for conservative CPU model loading')
    root = checked_root(root, create=True)
    fd, stage = tempfile.mkstemp(prefix='.download-', dir=root)
    try:
        total = 0; hashed = hashlib.sha256(); magic = b''
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSRedirect())
        with os.fdopen(fd, 'wb') as stream:
            with opener.open(urllib.request.Request(url, headers={'User-Agent':'LinuxAutomationToolkit/3'}), timeout=20) as response:
                if response.status != 200: raise ValueError('Model server did not return HTTP 200')
                while True:
                    chunk = response.read(min(1024*1024, size-total+1))
                    if not chunk: break
                    total += len(chunk)
                    if total > size: raise ValueError('Downloaded model exceeds expected size')
                    if len(magic) < 4: magic = (magic + chunk)[:4]
                    stream.write(chunk); hashed.update(chunk)
            stream.flush(); os.fsync(stream.fileno())
        if total != size or hashed.hexdigest() != checksum or magic != b'GGUF':
            raise ValueError('Model size, GGUF header or SHA-256 verification failed')
        record = {'format':1, 'name':name, 'sha256':checksum, 'size':size}
        # Issue ownership only after observing exclusive activation. A failed
        # activation must not authorize deletion of a concurrent user's file.
        os.link(stage, target)
        atomic_receipt(receipt, record)
        print('Model downloaded and checksum verified:', name)
    finally:
        if os.path.exists(stage): os.unlink(stage)
    return 0


def remove(root, name, *, yes=False, dry_run=False):
    root = checked_root(root); name = filename(name)
    target = root/name; receipt = root/(name+'.receipt.json')
    if target.is_symlink() or receipt.is_symlink(): raise ValueError('Symlink model/receipt is forbidden')
    if not target.is_file() or not receipt.is_file():
        raise ValueError('Removal requires a toolkit download receipt and a regular model')
    if receipt.stat().st_size > 4096: raise ValueError('Invalid model receipt')
    record = json.loads(receipt.read_text())
    if record.get('format') != 1 or record.get('name') != name or record.get('size') != target.stat().st_size or record.get('sha256') != digest(target):
        raise ValueError('Model changed since download; removal refused')
    if dry_run: print('Dry run: would remove this receipt-owned model only:', name); return 0
    if not yes: print('Model removal requires --yes.'); return 4
    target.unlink(); receipt.unlink()
    print('Removed receipt-owned model:', name)
    return 0
