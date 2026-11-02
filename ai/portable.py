#!/usr/bin/env python3
"""Portable, conservative Linux AI backend operations (stdlib only).

Ollama: upstream Linux installer after explicit opt-in. llama.cpp: CPU-only
source build in XDG data directory. vLLM: reviewed existing executable and local model.
No model deletes, external server exposure or shared systemd unit edits.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.parse
import ai_health

ROOT = Path.home() / '.local/share/automation-toolkit/ai'


def ollama_env(host='127.0.0.1',port=None):
    port=port if port is not None else ai_health.DEFAULT_PORTS['ollama']
    ai_health.endpoint('ollama',host,port)
    env=os.environ.copy()
    for name in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):
        env.pop(name,None)
    authority='[::1]' if host=='::1' else '127.0.0.1' if host=='localhost' else host
    env['OLLAMA_HOST']=f'{authority}:{port}'
    return env


def command(cmd, *, dry_run=False, timeout=1800, env=None):
    print('$', ' '.join(map(str,cmd)),flush=True)
    if dry_run:return 0
    try: return subprocess.run(cmd,timeout=timeout,env=env).returncode
    except subprocess.TimeoutExpired: return 124
    except OSError: return 127


def status(backend,model_root=None,*,host='127.0.0.1',port=None):
    if backend=='jan':
        print('Jan executable:',shutil.which('jan') or 'not found in PATH')
        print('Jan Desktop is managed in its GUI; this integration only probes its existing loopback API.');return 0
    if backend=='ollama':
        print('Ollama binary:',shutil.which('ollama') or 'not installed')
        if shutil.which('ollama'): return command(['ollama','--version'],timeout=15,env=ollama_env(host,port))
        return 0
    if backend=='llamacpp':
        binary=ROOT/'llamacpp/build/bin/llama-server'
        print('llama.cpp server:',str(binary) if binary.is_file() else 'not installed by portable manager')
        models=model_root or ROOT/'models'
        if models.is_dir():
            print('Locally found GGUF models (files not modified):')
            for p in sorted(models.glob('*.gguf'))[:100]:print(' -',p.name)
        return 0
    print('vLLM:',shutil.which('vllm') or 'no global vllm executable detected')
    print('Portable vLLM installation needs a platform-specific PyTorch/CUDA/ROCm assessment.')
    return 0


def installer_destination(url):
    """Only Ollama's official installer and its GitHub release delegation."""
    try:
        value=urllib.parse.urlsplit(url)
        if value.scheme!='https' or value.username or value.password or value.fragment or value.port not in (None,443) or any(ord(char)<33 for char in url):return False
        if value.hostname=='ollama.com':return value.path=='/install.sh' and not value.query
        if value.hostname=='github.com':return not value.query and bool(re.fullmatch(r'/ollama/ollama/releases/(?:latest/download|download/v[0-9][A-Za-z0-9._-]{0,63})/install\.sh',value.path))
        # Stable public repository ID confirmed through GitHub's official API.
        if value.hostname=='release-assets.githubusercontent.com':return bool(re.fullmatch(r'/github-production-release-asset/658928958/[a-fA-F0-9-]{36}',value.path))
    except (ValueError,AttributeError):return False
    return False


class InstallerRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):self.hops=0
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        self.hops+=1
        if self.hops>5 or not installer_destination(newurl):raise ValueError('Unexpected official installer redirect')
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def installer_payload():
    request=urllib.request.Request('https://ollama.com/install.sh',headers={'User-Agent':'LinuxAutomationToolkit/2'})
    with urllib.request.build_opener(InstallerRedirect()).open(request,timeout=25) as response:
        if not installer_destination(response.url):raise ValueError('Unexpected official installer destination')
        payload=response.read(500001)
    if len(payload)>500000 or not payload.startswith(b'#!') or b'ollama' not in payload[:50000].lower():raise ValueError('Unexpected official Ollama installer payload')
    payload.decode('utf-8')
    return payload


def install_ollama(args):
    if shutil.which('ollama') and args.action=='install':
        print('Ollama already installed; use status or explicit repair/update.');return 0
    if args.action not in ('install','repair','update'):
        print('Ollama models and services are not deleted by this tool.');return 3
    print('Official Ollama Linux installer: https://ollama.com/install.sh')
    print('WARNING: The upstream installer uses system sudo, may overwrite a previous Ollama install, and has no pinned artifact signature here.')
    if not args.yes:
        print('Explicit --yes required, even when running interactively.');return 4
    if args.dry_run: return command(['sh','/tmp/ollama-official-install.sh'],dry_run=True)
    with tempfile.TemporaryDirectory(prefix='automation-ollama-') as td:
        file=Path(td)/'install.sh'
        payload=installer_payload()
        file.write_bytes(payload);file.chmod(0o700)
        syntax=subprocess.run(['sh','-n',str(file)],capture_output=True,timeout=15)
        if syntax.returncode:raise ValueError('Official installer shell syntax validation failed')
        return command(['sh',str(file)],timeout=2400)


def install_llamacpp(args):
    target=ROOT/'llamacpp'
    src=target/'src'
    build=target/'build'
    if args.action == 'install' and (build/'bin/llama-server').is_file():
        print('llama.cpp already built; use explicit repair or update.'); return 0
    for binary in ('git','cmake','make','c++'):
        if not shutil.which(binary):
            print(f'Missing build requirement: {binary} (install it using setup.sh packages)')
            return 3
    if args.action not in ('install','update','repair'):return 3
    if not args.yes:
        print('Source checkout/build requires explicit --yes.');return 4
    if any(p.is_symlink() for p in (target,*target.parents)):
        print('Refusing symlink installation path.'); return 3
    if not args.dry_run: target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if src.exists():
        if not (src/'.git').is_dir():
            print('Unexpected source directory; refusing to overwrite:',src)
            return 3
        origin=subprocess.run(['git','-C',str(src),'remote','get-url','origin'],capture_output=True,text=True,timeout=15)
        if origin.returncode or origin.stdout.strip().rstrip('/') not in ('https://github.com/ggml-org/llama.cpp','https://github.com/ggml-org/llama.cpp.git'):
            print('Existing source has an unexpected origin; refusing to build or update it.');return 3
        clean=subprocess.run(['git','-C',str(src),'status','--porcelain'],capture_output=True,text=True,timeout=15)
        if clean.returncode or clean.stdout.strip():
            print('llama.cpp source has local edits; refusing update to preserve changes.');return 3
        if args.action=='update':
            if command(['git','-C',str(src),'pull','--ff-only'],dry_run=args.dry_run,timeout=120):return 1
    else:
        if command(['git','clone','--depth','1','https://github.com/ggml-org/llama.cpp',str(src)],dry_run=args.dry_run,timeout=240):return 1
    returncode=command(['cmake','-G','Unix Makefiles','-S',str(src),'-B',str(build),'-DGGML_NATIVE=OFF','-DGGML_CUDA=OFF','-DGGML_VULKAN=OFF',
        '-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF','-DLLAMA_BUILD_APP=OFF','-DLLAMA_BUILD_UI=OFF',
        '-DLLAMA_USE_PREBUILT_UI=OFF','-DLLAMA_OPENSSL=OFF','-DLLAMA_CONNECT=OFF','-DLLAMA_SUBPROCESS=OFF',
        '-DCMAKE_BUILD_TYPE=Release'],dry_run=args.dry_run,timeout=600)
    if returncode:return returncode
    jobs=max(1,min(4,getattr(args,'cpu_threads',None) or os.cpu_count() or 2))
    result=command(['cmake','--build',str(build),'--config','Release','--target','llama-server','-j',str(jobs)],dry_run=args.dry_run,timeout=3600)
    if not result:
        print('Models preserved in', ROOT/'models')
        print('Run server manually with --host 127.0.0.1 and a reviewed model path.')
    return result


def pull_ollama(args):
    """Explicit opt-in; never deletes or silently updates local models."""
    model=getattr(args,'model',None)
    env=ollama_env(getattr(args,'host','127.0.0.1'),getattr(args,'port',None))
    if not model or len(model)>200 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?',model):
        print('Provide a valid Ollama model tag with --model; no shell syntax accepted.')
        return 2
    if not getattr(args,'yes',False):
        print('Model download requires explicit --yes.')
        return 4
    if not shutil.which('ollama') and not args.dry_run:
        print('Ollama is not installed.')
        return 3
    if not args.dry_run and not getattr(args,'refresh_model',False):
        try:
            existing=subprocess.run(['ollama','list'],capture_output=True,text=True,timeout=20,env=env)
            names={line.split()[0] for line in existing.stdout.splitlines()[1:] if line.split()}
            canonical=model if ':' in model.rsplit('/',1)[-1] else model+':latest'
            if existing.returncode==0 and (model in names or canonical in names):
                print('Ollama model already present; skipping duplicate pull. Add --refresh-model --yes to request a refresh.')
                return 0
        except (OSError,subprocess.TimeoutExpired): pass
    return command(['ollama','pull',model],dry_run=args.dry_run,timeout=7200,env=env)


def serve_ollama(args):
    if not getattr(args,'yes',False):
        print('Launching Ollama server requires --yes.')
        return 4
    if getattr(args,'cpu_quota',None) or getattr(args,'cpu_threads',None):
        print('Ollama foreground service does not support toolkit CPU quota/thread overrides.')
        return 2
    if not shutil.which('ollama') and not args.dry_run:
        print('Install Ollama first.')
        return 3
    host=getattr(args,'host','127.0.0.1')
    if host not in ai_health.LOCAL_HOSTS:return 2
    port=getattr(args,'port',None) or ai_health.DEFAULT_PORTS['ollama']
    if not 1024 <= port <= 65535:return 2
    env=ollama_env(host,port)
    if getattr(args,'context',None):env['OLLAMA_CONTEXT_LENGTH']=str(args.context)
    print('Ollama foreground server bound to localhost:',env['OLLAMA_HOST'])
    if args.context:print('Requested context:',args.context,'(verify effective context with ai ollama context)')
    return command(['ollama','serve'],dry_run=args.dry_run,timeout=86400,env=env)


def list_models(args):
    if args.backend in ('vllm','jan'):
        return ai_health.model_inventory(args.backend,getattr(args,'host','127.0.0.1'),getattr(args,'port',None),key_file=getattr(args,'key_file',None))
    if args.backend=='ollama':
        if not shutil.which('ollama'):
            print('Ollama is not installed.')
            return 3
        return command(['ollama','list'],timeout=30,env=ollama_env(getattr(args,'host','127.0.0.1'),getattr(args,'port',None)))
    if args.backend=='llamacpp':
        model_root=Path(args.root).expanduser() if args.root else ROOT/'models'
        if not model_root.is_dir():
            print('No model directory:',model_root)
            return 0
        for p in sorted(model_root.glob('*.gguf'))[:250]:
            if p.is_file() and not p.is_symlink(): print(p.name, f'({p.stat().st_size//1048576} MiB)')
        return 0
    print('vLLM models belong to its managed Python/Hugging Face environment; no shared inventory has been configured.')
    return 3


def serve_llamacpp(args):
    """Run a local llama-server in foreground. Do not create or modify systemd units."""
    model=getattr(args,'model',None)
    if not model:
        print('Select an existing GGUF file using --model=/absolute/path.gguf')
        return 2
    path=Path(model).expanduser()
    if not path.is_absolute() or not path.is_file() or path.is_symlink() or path.suffix.lower()!='.gguf':
        print('GGUF model must be an existing, regular, absolute .gguf file (no symlinks).')
        return 3
    if getattr(args,'cpu_quota',None):
        print('--cpu-quota applies to managed systemd services, not a foreground server.')
        return 2
    if not args.yes:
        print('Launching a foreground AI server requires --yes.')
        return 4
    binary=ROOT/'llamacpp/build/bin/llama-server'
    executable=str(binary) if binary.is_file() else shutil.which('llama-server')
    if not executable:
        print('llama-server is missing; install llama.cpp first.')
        return 3
    host=getattr(args,'host','127.0.0.1')
    if host not in ai_health.LOCAL_HOSTS:
        print('Only localhost bindings are supported.')
        return 2
    port=getattr(args,'port',None) or ai_health.DEFAULT_PORTS['llamacpp']
    if not 1024 <= port <= 65535: return 2
    import services
    if not args.dry_run and not services.port_available(port):
        print('Requested loopback port is occupied; no process started.');return 3
    cmd=[executable,'--model',str(path),'--host',host,'--port',str(port)]
    if args.context: cmd+=['--ctx-size',str(args.context)]
    if args.cpu_threads: cmd+=['--threads',str(args.cpu_threads)]
    if getattr(args, 'key_file', None):
        import auth
        auth.read(args.key_file)
        cmd += ['--api-key-file', str(args.key_file)]
    if getattr(args,'model_alias',None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}',args.model_alias):raise ValueError('Invalid served model alias')
        cmd+=['--alias',args.model_alias]
    return command(cmd,dry_run=args.dry_run,timeout=86400)


def serve_vllm(args):
    if not args.yes:print('Foreground vLLM execution requires --yes.');return 4
    if args.cpu_quota:print('CPU quotas require a configured user service.');return 2
    import services
    executable=getattr(args,'executable',None) or shutil.which('vllm')
    if not executable:print('No existing vLLM executable; hardware-specific installation is not automatic.');return 3
    value={'schema':1,'backend':'vllm','executable':str(Path(executable).expanduser().resolve()),
        'model':args.model,'context':args.context or 4096,'threads':args.cpu_threads or min(4,os.cpu_count() or 1),
        'port':args.port or ai_health.DEFAULT_PORTS['vllm'],'key_file':str(args.key_file) if args.key_file else None,'cpu_quota':300}
    if getattr(args,'model_alias',None):value['model_alias']=args.model_alias
    options={name:getattr(args,flag) for name,flag in (('dtype','dtype'),('kv_cache_gib','kv_cache_gib'),('tool_parser','tool_parser')) if getattr(args,flag,None) is not None}
    if options:value['vllm_options']=options
    cmd,env=services.invocation(value)
    if not args.dry_run and not services.port_available(value['port']):print('Requested loopback port is occupied.');return 3
    if not args.dry_run:services.prepare_runtime(value)
    return command(cmd,dry_run=args.dry_run,env=env,timeout=86400)

def main(args):
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
    from automation import platform_info
    info=platform_info()
    if info['family']=='unknown':
        print('Unrecognized distribution: portable AI operations disabled.');return 3
    if args.action in ('check','status','doctor'):
        if args.action=='doctor': ai_health.print_hardware()
        return status(args.backend,Path(args.root).expanduser() if args.root else None,host=getattr(args,'host','127.0.0.1'),port=getattr(args,'port',None))
    if args.backend=='jan' and args.action not in ('test-api','models'):
        print('Jan Desktop installation and lifecycle must be managed through its supported GUI.');return 3
    if args.action=='context':
        return ai_health.runtime_context(args.backend,getattr(args,'host','127.0.0.1'),
                                         getattr(args,'port',None),getattr(args,'context',None),key_file=getattr(args,'key_file',None))
    if args.action=='test-api':
        return ai_health.check_api(args.backend,getattr(args,'host','127.0.0.1'),
                                   getattr(args,'port',None),key_file=getattr(args,'key_file',None))
    if args.action=='models': return list_models(args)
    if args.action=='pull':
        return pull_ollama(args) if args.backend=='ollama' else 3
    if args.action=='serve':
        if args.backend=='llamacpp':return serve_llamacpp(args)
        if args.backend=='ollama':return serve_ollama(args)
        if args.backend=='vllm':return serve_vllm(args)
        return 3
    if args.action=='uninstall':
        print('Automatic AI uninstallation disabled; preserve models and unrelated system services.')
        return 3
    if args.backend=='ollama':
        if info['arch'] not in ('x86_64','aarch64','arm64','amd64'):
            print('Unsupported Ollama installer architecture:',info['arch']);return 3
        return install_ollama(args)
    if args.backend=='llamacpp': return install_llamacpp(args)
    print('Cross-distribution vLLM installation is not verified. Use a platform-specific managed environment.')
    return 3
