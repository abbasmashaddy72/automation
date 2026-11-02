#!/usr/bin/env python3
"""Opt-in actual Laravel/PHP/Nginx/PostgreSQL integration in disposable Ubuntu."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import os
ROOT=Path(__file__).resolve().parents[1]
def source_ignore(directory,names):
    return [name for name in names if name.startswith('.env') or name in ('.git','__pycache__','.venv','node_modules','vendor','test-results') or name.endswith(('.key','.pem','.pyc'))]
def output_path(value):
    path=Path(value).expanduser().absolute()
    for candidate in (path,*path.parents):
        if candidate.is_symlink():raise ValueError('Symlink output path refused')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.stat().st_uid!=os.geteuid() or path.stat().st_mode&0o077:raise ValueError('Output directory must be private and owned')
    return path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-install',action='store_true',help='Approve disposable native packages and official Laravel fixture dependency downloads')
    parser.add_argument('--allow-pull',action='store_true');parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    if not args.allow_install:parser.error('Explicit --allow-install is required; no host provisioning is performed')
    output=output_path(args.output)
    info=subprocess.run(['podman','--remote=false','info','--format','{{.Host.Security.Rootless}}'],capture_output=True,text=True,timeout=20)
    if info.returncode or info.stdout.strip()!='true':parser.error('Installed local rootless Podman is required')
    image='docker.io/library/ubuntu:24.04'
    exists=subprocess.run(['podman','--remote=false','image','exists',image],capture_output=True,timeout=20)
    if exists.returncode:
        if not args.allow_pull:parser.error('Ubuntu image not cached; explicit --allow-pull required')
        result=subprocess.run(['podman','--remote=false','pull',image],capture_output=True,timeout=600)
        if result.returncode:parser.error('Ubuntu image pull failed')
    nonce=uuid.uuid4().hex;name='automation-laravel-test-'+nonce
    result={'status':'fail','image':image,'scope':'disposable Ubuntu; actual native daemons/framework; simulated systemd manager; no public ACME issuance','teardown':False}
    with tempfile.TemporaryDirectory(prefix='automation-laravel-source-') as temp:
        source=Path(temp)/'source';shutil.copytree(ROOT,source,ignore=source_ignore)
        command=['podman','--remote=false','run','--name',name,'--pull=never','--memory=3g','--cpus=2','--pids-limit=512',
            # Scoped sudo is tested inside this rootless user namespace. NNP
            # would prohibit that legitimate in-container privilege transition.
            '--label','org.automation-toolkit.laravel-sandbox='+nonce,'--env','AUTOMATION_DISPOSABLE_CONTAINER=yes',
            '--mount',f'type=bind,src={source},dst=/portable-laravel,readonly',image,'bash','/portable-laravel/tests/container_probe.sh']
        try:
            completed=subprocess.run(command,capture_output=True,text=True,timeout=2400)
            # Fixture inputs contain no real credentials; withhold generic raw
            # application output anyway and record only known boolean markers.
            expected=('INDEPENDENT_UBUNTU_TESTS=yes','FRESH_PROVISION=yes','REPEAT_PROVISION=yes','NATIVE_NGINX_FPM_POSTGRES=yes','CONFIG_PRESERVED=yes',
                'REAL_LARAVEL_COMPOSER_NPM=yes','ATOMIC_RELEASES=yes','DATABASE_MIGRATIONS=yes','ROLLBACK_HEALTH=yes','SHARED_UPLOAD_PRESERVED=yes')
            result.update(exit_code=completed.returncode,checks={marker:marker in completed.stdout for marker in expected})
            safe=[line for line in (completed.stdout+'\n'+completed.stderr).splitlines() if line.startswith(('LARAVEL_STAGE=','Provisioning error:','Deployment error:','Laravel error:','Laravel IO/process failure'))]
            result['diagnostics']=safe[-12:]
            result['status']='pass' if completed.returncode==0 and all(result['checks'].values()) else 'fail'
            if completed.returncode:result['reason']='native_workflow_failed; inspect the disposable fixture before teardown using an explicitly requested debug run'
        except subprocess.TimeoutExpired:result['reason']='native_workflow_timeout'
        except KeyboardInterrupt:result['reason']='interrupted_by_operator'
        finally:
            inspected=subprocess.run(['podman','--remote=false','container','inspect',name],capture_output=True,text=True,timeout=20)
            if inspected.returncode==0:
                rows=json.loads(inspected.stdout)
                if len(rows)==1 and rows[0].get('Config',{}).get('Labels',{}).get('org.automation-toolkit.laravel-sandbox')==nonce:
                    subprocess.run(['podman','--remote=false','rm','--force',rows[0]['Id']],capture_output=True,timeout=120)
            missing=subprocess.run(['podman','--remote=false','container','exists',name],capture_output=True,timeout=20)
            result['teardown']=missing.returncode==1
            if not result['teardown']:result['status']='fail';result['reason']='fixture_teardown_incomplete'
    path=output/'laravel-sandbox.json';path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps(result,indent=2))
    return 130 if result.get('reason')=='interrupted_by_operator' else 0 if result['status']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
