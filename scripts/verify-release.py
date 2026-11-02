#!/usr/bin/env python3
"""Verify full/patch release roundtrips against a disposable baseline copy."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import patch_manager


def fingerprint(root):
    return {p.relative_to(root).as_posix():(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mode&0o777)
            for p in root.rglob('*') if p.is_file() and not p.is_symlink() and p.name not in ('manifest.json','signature.ed25519')}


def verify(baseline, release):
    release=Path(release).resolve(); baseline=Path(baseline).resolve()
    full=release/'automation-full.zip'; incremental=release/'automation-patch.zip'
    checks={}
    with tempfile.TemporaryDirectory(prefix='automation-release-test-') as td:
        temp=Path(td); extracted=temp/'extracted'; extracted.mkdir()
        with zipfile.ZipFile(full) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            names={x['path']:x for x in manifest['files']}
            for info in archive.infolist():
                name=patch_manager.valid_name(info.filename)
                if name in ('manifest.json','signature.ed25519'): continue
                data=archive.read(info)
                if hashlib.sha256(data).hexdigest()!=names[name]['sha256']: raise ValueError('Full ZIP checksum mismatch')
                path=extracted/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data); path.chmod(names[name]['mode'])
            checks['full_manifest_checksums']=len(names)==len(fingerprint(extracted))
        checks['no_local_env_or_models']=not any(name.startswith('.env') or name.endswith(('.gguf','.key','.pem')) for name in names)
        baseline_fingerprint=fingerprint(baseline)
        for kind,script,archive in [('patch','patch_manager.py',incremental),('full','full_update.py',full)]:
            target=temp/kind; shutil.copytree(baseline,target)
            env={**os.environ,'AUTOMATION_PATCH_BACKUP_DIR':str(temp/(kind+'-backups')),'PYTHONDONTWRITEBYTECODE':'1'}
            def command(*args):
                cp=subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--root',str(target),*args],env=env,capture_output=True,text=True,timeout=60)
                if cp.returncode: raise ValueError(kind+' verification failed: '+cp.stdout+cp.stderr)
            before=set(temp.iterdir())
            command('--check',str(archive)); checks[kind+'_check_is_readonly']=before==set(temp.iterdir())
            command('--apply',str(archive)); checks[kind+'_apply_matches_full']=fingerprint(target)==fingerprint(extracted)
            (target/'.env').write_text('private-preserved\n'); (target/'.env').chmod(0o600)
            if kind=='full': command('--apply',str(archive)); checks['full_repeat_preserves_env']=(target/'.env').read_text()=='private-preserved\n'
            rollback=subprocess.run([sys.executable,str(ROOT/'scripts/patch_manager.py'),'--root',str(target),'--rollback'],env=env,capture_output=True,text=True,timeout=60)
            checks[kind+'_rollback_exit']=rollback.returncode==0
            (target/'.env').unlink()
            checks[kind+'_rollback_matches_baseline']=fingerprint(target)==baseline_fingerprint
        cp=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=extracted,
                          env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=180)
        checks['extracted_full_unit_suite']=cp.returncode==0
        (release/'extracted-tests.log').write_text(cp.stdout+'\n'+cp.stderr)
    report={'checks':checks,'status':'pass' if all(checks.values()) else 'fail'}
    (release/'verification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('baseline'); parser.add_argument('release')
    args=parser.parse_args(); report=verify(args.baseline,args.release)
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report['status']=='pass' else 1)
