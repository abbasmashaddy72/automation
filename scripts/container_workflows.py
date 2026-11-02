#!/usr/bin/env python3
"""Explicit package integration tests in disposable rootless Podman containers."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from validate import IMAGES, ROOT, output_path


def source_ignore(directory,names):
    ignored=shutil.ignore_patterns('.git','.env*','__pycache__','.cache','.venv','node_modules',
        'backups','logs','reports','*.pyc','*.pem','*.key','*.gguf','*.safetensors','*.zip')(directory,names)
    return set(ignored)|{name for name in names if (Path(directory)/name).is_symlink()}


def probe(name, *, allow_pull=False, with_lint=False, with_ai_build=False, with_system_tests=False, with_ollama_install=False, system_tests_only=False, log_dir=None, source=ROOT):
    image,family=IMAGES[name]
    def run(cmd,timeout=30): return subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    try:present=run(['podman','image','exists',image]).returncode
    except (OSError,subprocess.SubprocessError) as exc:
        return {'status':'fail','reason':'engine_query_failed','error_type':type(exc).__name__,'image':image}
    if present not in (0,1):return {'status':'fail','reason':'engine_query_failed','image':image}
    if present:
        if not allow_pull: return {'status':'skip','reason':'image_not_cached_pull_not_authorized'}
        if run(['podman','pull',image],600).returncode: return {'status':'fail','reason':'image_pull_failed'}
    container='automation-workflow-'+uuid.uuid4().hex[:12]
    cmd=['podman','run','--rm','--pull=never','--name',container,'--cap-drop=ALL',
         '--cap-add=CHOWN','--cap-add=DAC_OVERRIDE','--cap-add=FOWNER','--cap-add=SETUID','--cap-add=SETGID',
         '--security-opt=no-new-privileges','--user=0:0','--memory='+('6g' if with_ai_build else '1g'),'--cpus=2','--pids-limit=256',
         '--env','AUTOMATION_DISPOSABLE_CONTAINER=yes',
         '--env','AUTOMATION_WORKFLOW_LINT='+('yes' if with_lint and name == 'debian' else 'no'),
         '--env','AUTOMATION_WORKFLOW_SKIP_SMOKE='+('yes' if system_tests_only else 'no'),
         '--env','AUTOMATION_WORKFLOW_SYSTEM_TESTS_ONLY='+('yes' if system_tests_only else 'no'),
         '--env','AUTOMATION_WORKFLOW_OLLAMA_INSTALL='+('yes' if with_ollama_install else 'no'),
         '--env','AUTOMATION_WORKFLOW_SYSTEM_TESTS='+('yes' if with_system_tests else 'no'),
         '--env','AUTOMATION_WORKFLOW_AI_BUILD='+('yes' if with_ai_build and name=='debian' else 'no'),
         '--mount',f'type=bind,src={source},dst=/toolkit,readonly',
         image,'sh','/toolkit/scripts/container_workflow_probe.sh',family]
    report={'status':'fail','image':image}
    try:
        result=run(cmd,5400 if with_ai_build or with_ollama_install else 1800)
        if log_dir:
            (log_dir/(name+'.log')).write_text(result.stdout+'\n'+result.stderr)
        report={'status':'pass' if result.returncode==0 else 'fail','exit_code':result.returncode,
                'image':image,'details':(result.stdout+'\n'+result.stderr)[-12000:]}
        report['scope']='selected_integrations_without_package_smoke' if system_tests_only else 'native_package_workflow'
        report['checks']={}
        if with_system_tests:report['checks']['unprivileged_regressions']='UNPRIVILEGED_SYSTEM_REGRESSIONS=yes' in result.stdout
        if with_system_tests or not system_tests_only:report['checks']['checklist_automation']='CHECKLIST_AUTOMATION=yes' in result.stdout
        if with_lint and name=='debian':report['checks']['lint_tools']='LINT_TOOLS_CHECKED=yes' in result.stdout
        if with_ai_build and name=='debian':report['checks']['cpu_source_build']='LLAMACPP_CPU_SOURCE_BUILD=yes' in result.stdout
        if with_ollama_install:report['checks']['ollama_native_install']='OLLAMA_NATIVE_INSTALL_AND_REPEAT=yes' in result.stdout
        if not system_tests_only:report['checks']['native_package_smoke']=all(marker in result.stdout for marker in ('BOOTSTRAP=yes','PLAN=yes','GIT_INSTALL_VERIFIED=yes','REPEAT_INSTALL=yes','UNAVAILABLE_EXIT=5'))
        if result.returncode==0 and (not report['checks'] or not all(report['checks'].values())):report.update(status='fail',reason='requested_checks_missing')
    except subprocess.TimeoutExpired as exc:
        def decoded(value): return value.decode(errors='replace') if isinstance(value,bytes) else value or ''
        details=decoded(exc.stdout)+'\n'+decoded(exc.stderr)
        if log_dir: (log_dir/(name+'.log')).write_text(details)
        report={'status':'fail','reason':'workflow_timeout','image':image,'details':details[-12000:]}
    except (OSError,subprocess.SubprocessError) as exc:
        report={'status':'fail','reason':'workflow_process_failed','error_type':type(exc).__name__,'image':image}
    finally:
        try:
            run(['podman','rm','-f',container])
            report['teardown']=run(['podman','container','exists',container]).returncode==1
        except (OSError,subprocess.SubprocessError):report['teardown']=False
        if not report['teardown']:report.update(status='fail',reason='fixture_teardown_incomplete')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-install',action='store_true',help='authorize native package transactions inside disposable containers only')
    parser.add_argument('--allow-pull',action='store_true'); parser.add_argument('--output',required=True)
    parser.add_argument('--with-lint',action='store_true',help='install/run ShellCheck and shfmt inside the Debian test container')
    parser.add_argument('--with-ai-build',action='store_true',help='build the CPU-only llama-server in the disposable Debian container')
    parser.add_argument('--with-ollama-install',action='store_true',help='Run the official native Ollama installer and verify repeat installation inside the disposable layer')
    parser.add_argument('--with-system-tests',action='store_true',help='Run the full regression suite as an unprivileged fixture user; also test exact native Fish/Zsh where available')
    parser.add_argument('--system-tests-only',action='store_true',help='Bootstrap native test dependencies and rerun unprivileged regressions without repeating catalogue/package smoke')
    parser.add_argument('--skip-package-smoke',action='store_true',help='Run selected lint/build/native-installer/regression integrations without repeating package/catalogue smoke')
    parser.add_argument('--jobs',type=int,choices=(1,2,3),default=2,help='Maximum concurrent disposable distro workflows (default: 2)')
    parser.add_argument('--containers',default=','.join(IMAGES))
    args=parser.parse_args(argv)
    if args.system_tests_only:args.with_system_tests=True
    skip_smoke=args.skip_package_smoke or args.system_tests_only
    if skip_smoke and not (args.with_system_tests or args.with_lint or args.with_ai_build or args.with_ollama_install):parser.error('Select an integration to run with --skip-package-smoke')
    if not args.allow_install: parser.error('Explicit --allow-install is required')
    names=args.containers.split(',')
    if not names or len(names)!=len(set(names)) or any(n not in IMAGES for n in names): parser.error('Invalid distro list')
    if (args.with_lint or args.with_ai_build) and 'debian' not in names:parser.error('Lint/source-build integrations require selecting the Debian fixture')
    if skip_smoke and not args.with_system_tests and not args.with_ollama_install and any(name!='debian' for name in names):parser.error('Select only Debian for standalone lint/source-build integrations')
    out=output_path(args.output)
    if not shutil.which('podman'): parser.error('Rootless Podman is required')
    try:cp=subprocess.run(['podman','info','--format','{{.Host.Security.Rootless}}'],capture_output=True,text=True,timeout=20)
    except (OSError,subprocess.SubprocessError):parser.error('Local Podman unavailable or busy; no workload started. Use an isolated test storage configuration when the shared engine is locked.')
    if cp.returncode or cp.stdout.strip()!='true': parser.error('Rootless Podman is required')
    results={}
    with tempfile.TemporaryDirectory(prefix='automation-container-source-') as td:
        source=Path(td)/'source'
        shutil.copytree(ROOT,source,ignore=source_ignore)
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            pending={executor.submit(probe,n,allow_pull=args.allow_pull,with_lint=args.with_lint,with_ai_build=args.with_ai_build,with_system_tests=args.with_system_tests,with_ollama_install=args.with_ollama_install,system_tests_only=skip_smoke,log_dir=out,source=source):n for n in names}
            for future in as_completed(pending):
                name=pending[future]
                results[name]=future.result(); print(name+': '+results[name]['status'],flush=True)
                (out/'workflows.json').write_text(json.dumps({'scope':'disposable rootless containers only','containers':results},indent=2,sort_keys=True)+'\n')
    report={'scope':'disposable rootless containers; package installation only inside temporary layers','containers':results}
    (out/'workflows.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return 0 if all(r['status']=='pass' for r in results.values()) else 1


if __name__=='__main__': raise SystemExit(main())
