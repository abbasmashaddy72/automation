#!/usr/bin/env python3
"""Non-mutating host checks for Lerd prerequisites and local AI runtime."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
sys.path.insert(0,str(ROOT/'ai'))
import automation
import ai_health


def probe(cmd, timeout=12):
    try:
        p=subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, timeout=timeout, check=False)
        # Do not retain outputs that might include configuration or secrets.
        if cmd[:2]==['podman','info'] and p.returncode==0 and p.stdout.strip().lower()!='true':
            return {'status':'fail','reason':'podman_not_rootless'}
        return {'status':'pass' if p.returncode==0 else 'fail','exit_code':p.returncode}
    except FileNotFoundError:
        return {'status':'skip','reason':'executable_missing'}
    except subprocess.TimeoutExpired:
        return {'status':'fail','reason':'timeout'}
    except OSError:
        return {'status':'fail','reason':'execution_error'}


def host_report(*, run_lerd_doctor=False, inference_backend=None, inference_model=None,
                inference_port=None, allow_inference=False):
    info=automation.platform_info()
    info={k:v for k,v in info.items() if k in ('id','version','family','arch','wsl','container','init','user_systemd','desktop','immutable')}
    checks={
        'systemd_user':probe(['systemctl','--user','show-environment'],timeout=8) if shutil.which('systemctl') else {'status':'skip','reason':'systemctl_unavailable'},
        'rootless_podman':probe(['podman','info','--format','{{.Host.Security.Rootless}}'],timeout=10) if shutil.which('podman') else {'status':'skip','reason':'podman_unavailable'},
        'crun_present':{'status':'pass' if shutil.which('crun') else 'skip','reason':'recommended_not_mandatory' if not shutil.which('crun') else 'available'},
        'lerd_installed':{'status':'pass' if shutil.which('lerd') else 'skip','reason':'not_installed' if not shutil.which('lerd') else 'available'},
    }
    if run_lerd_doctor:
        checks['lerd_doctor']=probe(['lerd','doctor'],timeout=45) if shutil.which('lerd') else {'status':'skip','reason':'lerd_unavailable'}
    else:
        checks['lerd_doctor']={'status':'skip','reason':'explicit_opt_in_required'}
    if inference_backend is not None:
        if not allow_inference:
            checks['ai_inference']={'status':'skip','reason':'use_--allow-inference'}
        elif not inference_model:
            checks['ai_inference']={'status':'skip','reason':'a_model_is_required'}
        else:
            rc=ai_health.smoke_inference(inference_backend,inference_model,port=inference_port)
            checks['ai_inference']={'status':'pass' if rc==0 else 'fail', 'exit_code':rc,
                                    'backend':inference_backend}
    return {'host':info,'checks':checks,'scope':'read_only_except_explicit_local_inference'}


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only Lerd/AI host diagnostic (no installation)')
    p.add_argument('--lerd-doctor',action='store_true',help='call the official Lerd diagnostics')
    p.add_argument('--inference-backend',choices=('ollama','llamacpp','vllm'))
    p.add_argument('--inference-model')
    p.add_argument('--inference-port',type=int)
    p.add_argument('--allow-inference',action='store_true',help='send a small prompt to an already running localhost model')
    a=p.parse_args(argv)
    try:
        results=host_report(run_lerd_doctor=a.lerd_doctor,inference_backend=a.inference_backend,
                            inference_model=a.inference_model,inference_port=a.inference_port,
                            allow_inference=a.allow_inference)
    except ValueError as exc:
        p.error(str(exc))
    print(json.dumps(results,indent=2,sort_keys=True))
    # Diagnostics can be unavailable on a host not configured for Lerd.
    return 0 if not any(c['status']=='fail' for c in results['checks'].values()) else 1

if __name__=='__main__':sys.exit(main())
