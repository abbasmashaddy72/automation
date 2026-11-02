#!/usr/bin/env python3
"""Release validator: offline tests, optional sandboxed distro/host probes.

Default execution never installs software, pulls images, restarts services or
sends model prompts. Container pulls and inference require separate opt-ins.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
IMAGES={
    'arch':('docker.io/library/archlinux:base','arch'),
    'ubuntu':('docker.io/library/ubuntu:24.04','debian'),
    'debian':('docker.io/library/debian:13','debian'),
    'fedora':('registry.fedoraproject.org/fedora:42','fedora'),
    'rocky':('docker.io/rockylinux/rockylinux:9','rhel'),
    'opensuse':('registry.opensuse.org/opensuse/tumbleweed:latest','opensuse'),
    'alpine':('docker.io/library/alpine:3.22','alpine'),
}


def exec_check(cmd, *, timeout=120, env=None):
    try:
        cp=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=timeout,
                          env=env,check=False)
        out=(cp.stdout+'\n'+cp.stderr)[-6000:]
        return {'status':'pass' if cp.returncode==0 else 'fail','exit_code':cp.returncode,'details':out.strip()}
    except subprocess.TimeoutExpired:
        return {'status':'fail','reason':'timeout'}
    except OSError as exc:
        return {'status':'fail','reason':type(exc).__name__}


def python_syntax():
    import ast
    files=sorted(ROOT.rglob('*.py'))
    errors=[]
    for f in files:
        if any(part in ('__pycache__','.venv','backups') for part in f.relative_to(ROOT).parts):continue
        try: ast.parse(f.read_text(encoding='utf-8'), filename=str(f))
        except (SyntaxError,UnicodeError) as exc: errors.append(f'{f.relative_to(ROOT)}: {type(exc).__name__}')
    return {'status':'fail' if errors else 'pass','files':len(files),'errors':errors}


def offline_checks(*,strict_tools=False,strict_format=False):
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    checks={
        'python_unit':exec_check([sys.executable,'-m','unittest','discover','-s','tests','-q'],timeout=180,env=env),
        'bash_syntax':exec_check(['bash','scripts/check-scripts.sh','--syntax-only'],timeout=90,env=env),
        'python_syntax':python_syntax(),
    }
    shell_files=[str(x.relative_to(ROOT)) for x in sorted(ROOT.rglob('*.sh')) if 'backups' not in x.parts]
    for exe,command in [('shellcheck',['shellcheck','--severity=error',*shell_files]),
                        ('shfmt',['shfmt','-l','-i','4','-ci','-sr',*shell_files])]:
        if not shutil.which(exe):
            checks[exe]={'status':'fail' if strict_tools else 'skip','reason':'tool_not_installed'}
            continue
        result=exec_check(command,timeout=120,env=env)
        if exe=='shfmt' and result['status']=='pass' and result['details']:
            result={'status':'fail' if strict_format else 'warn', 'reason':'formatting_differences',
                    'details':result['details']}
        checks[exe]=result
    return checks


def engine_name(preference):
    if preference!='auto':return preference if shutil.which(preference) else None
    return next((name for name in ('podman','docker') if shutil.which(name)),None)


def container_checks(*,engine='auto',containers=None,allow_pull=False):
    names=containers or tuple(IMAGES)
    selected=engine_name(engine)
    if not selected:
        return {name:{'status':'skip','reason':'container_engine_unavailable'} for name in names}
    results={}
    for name in names:
        image,family=IMAGES[name]
        inspect_cmd=[selected,'image','exists',image] if selected=='podman' else [selected,'image','inspect',image]
        check=exec_check(inspect_cmd,timeout=20)
        if check['status']!='pass':
            if allow_pull:
                pulled=exec_check([selected,'pull',image],timeout=600)
                if pulled['status']!='pass':
                    results[name]={'status':'fail','reason':'image_pull_failed','details':pulled.get('details','')[-300:]}
                    continue
            else:
                results[name]={'status':'skip','reason':'image_not_cached_pull_not_authorized','image':image}
                continue
        # Each probe is isolated, unprivileged, read-only and has no network.
        run=[selected,'run','--rm','--network=none','--read-only','--cap-drop=ALL',
             '--security-opt=no-new-privileges','--user=65534:65534',
             '--mount',f'type=bind,src={ROOT},dst=/toolkit,readonly',image,
             'sh','/toolkit/scripts/container_probe.sh',family]
        if selected=='podman':run.insert(2,'--pull=never')
        if selected=='docker':run.insert(2,'--pull=never')
        result=exec_check(run,timeout=90)
        result['image']=image
        result['family']=family
        results[name]=result
    return results


def output_path(out):
    path=Path(out).expanduser().absolute()
    current=path
    while current != current.parent:
        if current.is_symlink():raise ValueError('Symlink report paths are forbidden')
        current=current.parent
    path=path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError('Validation reports must be outside the source tree')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.stat().st_mode & 0o022:
        raise ValueError('Report directory must not be group/world writable')
    return path


def save_report(directory,report):
    import tempfile
    report_dir=output_path(directory)
    counts={'pass':0,'fail':0,'skip':0,'warn':0}
    for group in ('offline','containers'):
        for item in report.get(group,{}).values():
            counts[item['status']]+=1
    for item in report.get('host',{}).get('checks',{}).values():
        counts[item['status']]+=1
    report['summary']=counts
    data=json.dumps(report,indent=2,sort_keys=True)+'\n'
    fd,p=tempfile.mkstemp(prefix='.validation-',dir=report_dir)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(p,report_dir/'validation.json')
    finally:
        if os.path.exists(p):os.unlink(p)
    rows=['# Linux Automation Toolkit — Consolidated release validation','',
          'Run (UTC): '+report['timestamp'],'',
          f"Passed: {counts['pass']} · Failed: {counts['fail']} · Skipped: {counts['skip']} · Warnings: {counts['warn']}",
          '', '| Scope | Check | Result |', '|---|---|---|']
    for group in ('offline','containers'):
        for name,item in report.get(group,{}).items():
            rows.append(f"| {group} | {name} | {item['status']} |")
    for name,item in report.get('host',{}).get('checks',{}).items():
        rows.append(f"| host | {name} | {item['status']} |")
    rows+=['','Container probes validate family and presence of package-manager binaries, **not** package installation or full Lerd desktop operation.',
           'Host probes do not certify an entire distribution family. Missing capability is skipped rather than passed.',
           '']
    path=report_dir/'validation.md'
    fd,p=tempfile.mkstemp(prefix='.validation-',dir=report_dir)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:f.write('\n'.join(rows));f.flush();os.fsync(f.fileno())
        os.replace(p,path)
    finally:
        if os.path.exists(p):os.unlink(p)
    return counts


def main(argv=None):
    p=argparse.ArgumentParser(description='Safe consolidated validation; default offline, no installation')
    p.add_argument('--mode',choices=('offline','containers','host','all'),default='offline')
    p.add_argument('--output',default=str(Path.home()/'.local/state/automation-toolkit/validation'))
    p.add_argument('--engine',choices=('auto','podman','docker'),default='auto')
    p.add_argument('--containers',default=','.join(IMAGES),help='comma-separated distro names from: '+','.join(IMAGES))
    p.add_argument('--allow-pull',action='store_true',help='explicitly allow downloading container images')
    p.add_argument('--require-containers',action='store_true',help='fail when a requested container check is skipped')
    p.add_argument('--strict-tools',action='store_true',help='fail when shellcheck or shfmt is unavailable')
    p.add_argument('--strict-format',action='store_true',help='fail on formatting differences')
    p.add_argument('--lerd-doctor',action='store_true',help='opt in to official Lerd doctor command (host mode)')
    p.add_argument('--inference-backend',choices=('ollama','llamacpp','vllm'))
    p.add_argument('--inference-model')
    p.add_argument('--inference-port',type=int)
    p.add_argument('--allow-inference',action='store_true',help='explicitly permit a local inference smoke prompt')
    a=p.parse_args(argv)
    names=[x.strip() for x in a.containers.split(',')]
    if not names or any(x not in IMAGES for x in names) or len(set(names))!=len(names):
        p.error('Invalid/duplicate distro in --containers; valid choices: '+','.join(IMAGES))
    report={'timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'mode':a.mode,'scope':'offline checks never install packages or change services'}
    if a.mode in ('offline','all'):report['offline']=offline_checks(strict_tools=a.strict_tools,strict_format=a.strict_format)
    if a.mode in ('containers','all'):report['containers']=container_checks(engine=a.engine,containers=names,allow_pull=a.allow_pull)
    if a.mode in ('host','all'):
        from host_diagnostics import host_report
        report['host']=host_report(run_lerd_doctor=a.lerd_doctor,
                   inference_backend=a.inference_backend,inference_model=a.inference_model,
                   inference_port=a.inference_port,allow_inference=a.allow_inference)
    try:counts=save_report(a.output,report)
    except (OSError,ValueError) as exc:
        p.error(str(exc))
    print('Validation results:', ', '.join(f'{k}={v}' for k,v in counts.items()))
    print('Reports:',str(output_path(a.output)/'validation.json'),str(output_path(a.output)/'validation.md'))
    strict_skip=a.require_containers and any(v['status']=='skip' for v in report.get('containers',{}).values())
    return 1 if counts['fail'] or strict_skip else 0

if __name__=='__main__':sys.exit(main())
