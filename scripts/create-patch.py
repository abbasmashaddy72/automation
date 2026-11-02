#!/usr/bin/env python3
"""Create a patch ZIP by comparing the unpacked original source to this tree.

Usage: python3 scripts/create-patch.py /path/to/original/source /path/to/patch.zip
"""
import hashlib
import json
import subprocess
import argparse
import tempfile
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDES = {'.env','.env.local','.git','.cache','backups','logs','reports','__pycache__','.pytest_cache','.venv','node_modules'}

def files(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*')
            if p.is_file() and not p.is_symlink() and not any(x in EXCLUDES for x in p.relative_to(root).parts)
            and not p.name.startswith('.env') and not p.name.endswith(('.pyc','.pem','.key','.gguf','.safetensors','.zip'))}

def main():
    parser=argparse.ArgumentParser(description='Create checksum-verified, optionally Ed25519-signed patch ZIP')
    parser.add_argument('original_dir');parser.add_argument('output_zip')
    parser.add_argument('--sign-key',help='trusted Ed25519 private PEM; NEVER place private keys in toolkit ZIP')
    args=parser.parse_args()
    original,final=files(Path(args.original_dir).resolve()),files(ROOT)
    ops=[]
    def sha(b): return hashlib.sha256(b).hexdigest()
    for name in sorted(set(original)|set(final)):
        a,b=original.get(name),final.get(name)
        old_mode = 0o755 if a is not None and (Path(args.original_dir)/name).stat().st_mode & 0o111 else 0o644
        new_mode = 0o755 if b is not None and (ROOT/name).stat().st_mode & 0o111 else 0o644
        if a==b and old_mode==new_mode: continue
        action='delete' if b is None else 'add' if a is None else 'modify'
        entry={'action':action,'path':name}
        if a is not None: entry['old_sha256']=sha(a)
        if b is not None: entry['sha256']=sha(b)
        if b is not None: entry['mode']=new_mode
        ops.append(entry)
    manifest=(json.dumps({'format':1,'operations':ops},indent=2)+'\n').encode()
    signature=None
    if args.sign_key:
        signing_path=Path(args.sign_key).resolve()
        if signing_path == ROOT or ROOT in signing_path.parents:
            raise ValueError('Keep private signing keys outside the project directory')
        with tempfile.TemporaryDirectory(prefix='automation-sign-') as tmp:
            msg=Path(tmp)/'manifest'; sig=Path(tmp)/'signature'
            msg.write_bytes(manifest)
            subprocess.run(['openssl','pkeyutl','-sign','-inkey',args.sign_key,'-rawin',
                            '-in',str(msg),'-out',str(sig)],check=True,timeout=10)
            signature=sig.read_bytes()
    with zipfile.ZipFile(args.output_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        z.writestr('manifest.json',manifest)
        if signature: z.writestr('signature.ed25519',signature)
        for op in ops:
            if op['action']!='delete': z.writestr('payload/'+op['path'],final[op['path']])
    print('Created operations:',len(ops),'; add:',sum(x['action']=='add' for x in ops),
          '; modify:',sum(x['action']=='modify' for x in ops),'; delete:',sum(x['action']=='delete' for x in ops))
if __name__=='__main__':main()
