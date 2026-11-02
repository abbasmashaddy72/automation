#!/usr/bin/env python3
"""Reproducible clean full ZIP and incremental patch, with optional publisher signature."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('create_patch', ROOT/'scripts/create-patch.py')
patch = importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)


def signature(data, key):
    if not key: return None
    key = Path(key).expanduser().resolve()
    if ROOT == key or ROOT in key.parents: raise ValueError('Private signing keys must remain outside the toolkit')
    with tempfile.TemporaryDirectory(prefix='automation-sign-') as td:
        path = Path(td); (path/'manifest').write_bytes(data)
        subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path/'manifest'),'-out',str(path/'signature')],check=True,timeout=10,capture_output=True)
        signed = (path/'signature').read_bytes()
        if len(signed) != 64: raise ValueError('An Ed25519 signing key is required')
        return signed


def write_zip(path, entries, modes=None):
    # Constant timestamp, sorted paths and normalized permission bits.
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as archive:
        for name,data in sorted(entries.items()):
            item = zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
            item.create_system = 3; item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100000 | (modes or {}).get(name,0o644)) << 16
            archive.writestr(item,data,compresslevel=8)


def build(original_dir, output_dir, *, sign_key=None):
    original_dir = Path(original_dir).resolve(); output_dir = Path(output_dir).resolve()
    if output_dir == ROOT or ROOT in output_dir.parents: raise ValueError('Release output must be outside source')
    old, new = patch.files(original_dir), patch.files(ROOT)
    for name in new:
        # Other local env files, credentials and downloaded artifacts never ship.
        if name.startswith('.env') or name.endswith(('.zip','.gguf','.safetensors','.env')) and name != 'config/defaults.env':
            raise ValueError('Potential private/generated artifact in release: '+name)
    def sha(data): return hashlib.sha256(data).hexdigest()
    def mode(root,name): return 0o755 if (root/name).stat().st_mode & 0o111 else 0o644
    changed=[]; full_files=[]
    for name in sorted(set(old)|set(new)):
        a,b=old.get(name),new.get(name)
        op={'action':'delete' if b is None else 'add' if a is None else 'modify','path':name}
        if a is not None: op['old_sha256']=sha(a)
        if b is not None:
            op.update(sha256=sha(b),mode=mode(ROOT,name))
            full_files.append({'path':name,'sha256':sha(b),'mode':mode(ROOT,name),'old_sha256':sha(a) if a is not None else None})
        if a != b or a is not None and b is not None and mode(original_dir,name) != mode(ROOT,name): changed.append(op)
    patch_manifest=(json.dumps({'format':1,'operations':changed},indent=2,sort_keys=True)+'\n').encode()
    full_manifest=(json.dumps({'format':2,'files':full_files,'deletions':[op for op in changed if op['action']=='delete']},indent=2,sort_keys=True)+'\n').encode()
    output_dir.mkdir(parents=True,exist_ok=True)
    patch_entries={'manifest.json':patch_manifest,**{'payload/'+op['path']:new[op['path']] for op in changed if op['action']!='delete'}}
    full_entries={**new,'manifest.json':full_manifest}
    for entries, manifest in ((patch_entries,patch_manifest),(full_entries,full_manifest)):
        signed=signature(manifest,sign_key)
        if signed: entries['signature.ed25519']=signed
    full_path=output_dir/'automation-full.zip'; patch_path=output_dir/'automation-patch.zip'
    write_zip(full_path,full_entries,{x['path']:x['mode'] for x in full_files})
    write_zip(patch_path,patch_entries)
    report={'format':1,'signed':bool(sign_key),'baseline':'untouched workspace snapshot',
            'changed':changed,'files':full_files,
            'archives':{p.name:sha(p.read_bytes()) for p in (full_path,patch_path)}}
    (output_dir/'release-manifest.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (output_dir/'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name,value in report['archives'].items()))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline'); parser.add_argument('output'); parser.add_argument('--sign-key')
    args=parser.parse_args()
    report=build(args.baseline,args.output,sign_key=args.sign_key)
    print('Built full and patch ZIPs;',len(report['changed']),'changed paths; signed:',report['signed'])


if __name__=='__main__': main()
