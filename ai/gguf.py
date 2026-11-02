"""Verified GGUF bundles and read-only legacy selection recovery (stdlib only)."""
from __future__ import annotations
from argparse import Namespace
import json
from pathlib import Path
import re
import shutil
import urllib.parse
import ai_health
import models
import snapshots

MARKER='.llama-automation.json'


def quantization(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_]{1,32}',value):raise ValueError('Provide a literal quantization label')
    return value


def series(names):
    """One unsharded file or one complete, unambiguous adjacent shard series."""
    if not isinstance(names,list) or not names or len(names)>snapshots.MAX_FILES or any(not isinstance(name,str) for name in names):raise ValueError('Invalid GGUF file set')
    if len(set(names))!=len(names):raise ValueError('Duplicate GGUF filename')
    parsed=[]
    for name in names:
        models.filename(name)
        if 'mmproj' in name.lower():raise ValueError('Multimodal projector bundles require separate verification')
        match=re.fullmatch(r'(.+)-(\d{5})-of-(\d{5})\.gguf',name,re.I)
        parsed.append(match.groups() if match else None)
    if len(names)==1 and parsed[0] is None:return names[0]
    if any(row is None for row in parsed):raise ValueError('Do not mix multiple models or single/sharded files in one bundle')
    base=parsed[0][0];count=int(parsed[0][2])
    if count!=len(names) or any(row[0]!=base or int(row[2])!=count for row in parsed) or {int(row[1]) for row in parsed}!=set(range(1,count+1)):
        raise ValueError('Incomplete or ambiguous GGUF shard series')
    return names[next(i for i,row in enumerate(parsed) if int(row[1])==1)]


def validate(value):
    if not isinstance(value,dict) or set(value)!={'schema','repository','revision','quantization','files'} or type(value['schema']) is not int or value['schema']!=1:
        raise ValueError('Invalid GGUF bundle schema')
    quantization(value['quantization'])
    if not isinstance(value['files'],list):raise ValueError('Invalid GGUF bundle files')
    rows=[]
    for row in value['files']:
        if not isinstance(row,dict) or set(row)!={'path','size','sha256','url'}:raise ValueError('Each GGUF file requires an explicit URL, size and independent SHA-256')
        if not isinstance(row['url'],str):raise ValueError('Provide an explicit literal HTTPS artifact URL')
        if len(row['url'])>4096 or not row['url'].isascii() or any(ord(c)<33 for c in row['url']):raise ValueError('Artifact URLs must be bounded literal ASCII without whitespace/control characters')
        models.https_url(row['url'])
        if urllib.parse.urlsplit(row['url']).query:raise ValueError('Bundle URLs must be public HTTPS without query credentials')
        if type(row['size']) is not int or row['size']<4:raise ValueError('Each GGUF artifact needs its exact size and header')
        rows.append({key:row[key] for key in ('path','size','sha256')})
    snapshot={'schema':1,'repository':value['repository'],'revision':value['revision'],'files':rows}
    snapshots.validate(snapshot);series([row['path'] for row in rows])
    return value,snapshot


def manifest(path):
    path=models.checked_root(path)
    if not path.is_file() or path.stat().st_size>262144:raise ValueError('GGUF bundle manifest must be a bounded regular JSON file')
    return validate(snapshots.decode(path))[0]


def bundle_root(root,value):
    root=models.checked_root(root);snapshots.private_directory(root)
    return snapshots.private_directory(root/quantization(value['quantization']))


def resolve(root,value):
    value,snapshot=validate(value)
    target=snapshots.destination(bundle_root(root,value),snapshot)
    snapshots.owned(target,snapshot)
    primary=series([row['path'] for row in snapshot['files']])
    for row in snapshot['files']:
        with (target/row['path']).open('rb') as stream:
            if stream.read(4)!=b'GGUF':raise ValueError('Invalid GGUF header in verified bundle')
    return target/primary


def inventory(root, *, quant=None):
    root=models.checked_root(root);snapshots.private_directory(root)
    if quant is not None:quantization(quant)
    if not root.exists():return []
    rows=[];visited=0
    def children(path):
        nonlocal visited
        for child in snapshots.entries(path,1024):
            visited+=1
            if visited>8192:raise ValueError('GGUF store inventory exceeds its bound')
            if child.name.startswith('.'):continue
            models.checked_root(child)
            if child.is_dir():yield child
    for directory in children(root):
        quantization(directory.name)
        if quant and directory.name!=quant:continue
        snapshots.private_directory(directory)
        for owner in children(directory):
            for model in children(owner):
                repo=owner.name+'/'+model.name;snapshots.repo_parts(repo)
                for target in children(model):
                    snapshots.revision(target.name)
                    row={'repository':repo,'revision':target.name,'quantization':directory.name,'directory':str(target),'status':'unverified'}
                    try:
                        value=snapshots.owned(target)
                        if value['repository']!=repo or value['revision']!=target.name:raise ValueError('Bundle receipt identity mismatch')
                        primary=series([entry['path'] for entry in value['files']])
                        for entry in value['files']:
                            with (target/entry['path']).open('rb') as stream:
                                if stream.read(4)!=b'GGUF':raise ValueError('Invalid GGUF header')
                        row.update(status='verified',primary=str(target/primary),bytes=sum(entry['size'] for entry in value['files']))
                    except (OSError,ValueError):row['note']='Incomplete, changed or unmanaged snapshot; selection/removal refused'
                    rows.append(row)
                    if len(rows)>1024:raise ValueError('Too many GGUF bundles')
    return rows


def download(root,value, *, yes=False,dry_run=False):
    value,snapshot=validate(value);base=bundle_root(root,value);target=snapshots.destination(base,snapshot)
    if target.exists():resolve(root,value);print('Verified GGUF bundle reused; no download.');return 0
    cache_root=models.checked_root(root)/'.downloads'/value['quantization']
    cache=snapshots.destination(cache_root,snapshot)
    # Preflight every file/receipt before any network or write; no fuzzy file
    # selection, new Hub dependency or implicit repository revision lookup.
    missing=0
    for row in value['files']:
        models.download(cache,row['path'],row['url'],row['sha256'],row['size'],dry_run=True)
        if not (cache/row['path']).exists():missing+=row['size']
    if dry_run:print('Dry run: complete GGUF bundle planned; no network, model or selection changed.');return 0
    if not yes:print('GGUF bundle download requires --yes after independent URL/checksum/size review.');return 4
    size=sum(row['size'] for row in snapshot['files'])
    hardware=ai_health.hardware();ram=hardware.get('available_memory_mib')
    if ram is None:ram=hardware.get('memory_mib')
    if ram is None or ram*1024**2<size+256*1024**2:raise ValueError('Insufficient or unknown available RAM for the entire GGUF bundle')
    ancestor=Path(root).expanduser()
    while not ancestor.exists():ancestor=ancestor.parent
    if shutil.disk_usage(ancestor).free<size+missing+max(64*1024**2,size//20):raise ValueError('Insufficient disk for downloads and a separate complete GGUF bundle')
    for path in (Path(root).expanduser(),Path(root).expanduser()/'.downloads',cache_root):snapshots.private_directory(path,create=True)
    snapshots.private_directory(cache,create=True)
    for row in value['files']:
        print('Verifying/downloading GGUF artifact:',row['path'],flush=True)
        result=models.download(cache,row['path'],row['url'],row['sha256'],row['size'],yes=True)
        if result:return result
    # Shared snapshot publishing verifies all bytes again and commits one
    # observed-copy receipt last. Partial downloads remain reusable cache only.
    result=snapshots.import_snapshot(base,snapshot,source=cache,yes=True)
    if result==0:resolve(root,value)
    return result


def read_data(path,limit):
    path=models.checked_root(path);st=snapshots.regular(path)
    if st.st_size>limit:raise ValueError('Legacy GGUF metadata exceeds its bound')
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Legacy GGUF metadata grew beyond its bound')
    return raw.decode('utf-8')


def legacy_inventory(root, *, ignore_state=False):
    root=models.checked_root(root);selected=None;context=None;rows=[]
    selection=root/'config/selected-model';settings=root/'config/runtime-settings'
    if not ignore_state and (selection.exists() or selection.is_symlink()):
        selected=read_data(selection,256).strip();models.repository(selected)
    if not ignore_state and (settings.exists() or settings.is_symlink()):
        literal=read_data(settings,64).strip()
        if not re.fullmatch(r'context=[0-9]{1,7}',literal):raise ValueError('Invalid old context settings; file was not executed')
        context=int(literal.split('=',1)[1])
        if not 128<=context<=1048576:raise ValueError('Old context is out of bounds')
    folder=models.checked_root(root/'models')
    if folder.exists():
        for child in snapshots.entries(folder,1024):
            if child.is_symlink():raise ValueError('Symlink legacy GGUF folder')
            marker=child/MARKER
            if not child.is_dir() or not (marker.exists() or marker.is_symlink()):continue
            read_data(marker,65536);data=snapshots.decode(marker,limit=65536)
            if not isinstance(data,dict) or set(data)!={'directory','repository','quantization','files'} or data['directory']!=child.name:
                raise ValueError('Invalid old GGUF marker schema')
            repo=data['repository'];models.repository(repo);quant=quantization(data['quantization'])
            if child.name!=repo.replace('/','--')+'--'+quant:raise ValueError('Legacy GGUF directory identity mismatch')
            names=data['files']
            if not isinstance(names,list):raise ValueError('Invalid old GGUF file list')
            primary=series(names);size=0
            for name in names:
                file=models.checked_root(child/name);st=snapshots.regular(file)
                if st.st_size<4:raise ValueError('Empty legacy model/shard')
                with file.open('rb') as stream:
                    if stream.read(4)!=b'GGUF':raise ValueError('Invalid old GGUF header')
                size+=st.st_size
            rows.append({'repository':repo,'quantization':quant,'directory':str(child),'files':names,'primary':str(child/primary),'bytes':size,
                'verification':'legacy marker only; independent hashes required for import, no deletion ownership'})
    return {'selected_repository':selected,'context':context,'models':rows,'legacy_state':'explicitly ignored' if ignore_state else 'validated',
        'note':'Read-only; no old unit, marker, selection, cache or key was changed.'}


def import_legacy(root,value,legacy_root, *, yes=False,dry_run=False,ignore_state=False):
    value,snapshot=validate(value)
    source=models.checked_root(legacy_root);destination=models.checked_root(root)
    if source==destination or source in destination.parents or destination in source.parents:raise ValueError('Use a separate store outside the legacy tree')
    inventory=legacy_inventory(source,ignore_state=ignore_state)
    matches=[row for row in inventory['models'] if row['repository']==value['repository'] and row['quantization']==value['quantization']]
    if len(matches)!=1 or set(matches[0]['files'])!={row['path'] for row in snapshot['files']}:
        raise ValueError('Manifest must match exactly one complete legacy model/quantization')
    return snapshots.import_snapshot(bundle_root(root,value),snapshot,source=matches[0]['directory'],yes=yes,dry_run=dry_run)


def main(args):
    import portable
    if args.backend!='llamacpp':raise ValueError('GGUF bundle operations support llama.cpp only')
    if args.action!='gguf-select' and any(getattr(args,key,None) is not None for key in ('executable','model_alias','context','cpu_threads','cpu_quota','port','key_file')):
        raise ValueError('GGUF runtime/key flags apply only to explicit gguf-select configuration')
    root=args.root or portable.ROOT/'gguf-bundles'
    if args.action=='gguf-list':
        print(json.dumps(inventory(root,quant=args.quant),indent=2));return 0
    if args.action=='gguf-legacy-list':
        if not args.legacy_root:raise ValueError('gguf-legacy-list requires --legacy-root')
        print(json.dumps(legacy_inventory(args.legacy_root,ignore_state=getattr(args,'ignore_legacy_state',False)),indent=2));return 0
    if not args.manifest:raise ValueError('GGUF bundle operation requires a reviewed --manifest')
    value=manifest(args.manifest)
    if args.model and args.model!=value['repository'] or args.quant and args.quant!=value['quantization'] or args.revision and args.revision!=value['revision']:
        raise ValueError('CLI identity conflicts with the GGUF bundle manifest')
    if args.action=='gguf-download':return download(root,value,yes=args.yes,dry_run=args.dry_run)
    if args.action=='gguf-legacy-import':
        if not args.legacy_root:raise ValueError('gguf-legacy-import requires --legacy-root')
        return import_legacy(root,value,args.legacy_root,yes=args.yes,dry_run=args.dry_run,ignore_state=getattr(args,'ignore_legacy_state',False))
    if args.action=='gguf-remove':
        _,snapshot=validate(value)
        resolve(root,value)
        return snapshots.remove_snapshot(bundle_root(root,value),snapshot['repository'],snapshot['revision'],yes=args.yes,dry_run=args.dry_run)
    path=resolve(root,value)
    if args.action=='gguf-resolve':print(path);return 0
    if args.action!='gguf-select':raise ValueError('Unknown GGUF bundle operation')
    context=args.context
    if args.legacy_root:
        ignored=getattr(args,'ignore_legacy_state',False)
        saved=legacy_inventory(args.legacy_root,ignore_state=ignored)
        if not ignored and saved['selected_repository']!=value['repository']:raise ValueError('Reviewed bundle does not match the old selected repository')
        if context is None:context=saved['context']
    import services
    selected=Namespace(**{**vars(args),'action':'configure','model':str(path),'context':context,
        'model_alias':args.model_alias or value['repository']+':'+value['quantization']})
    return services.main(selected)
