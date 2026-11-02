"""Owned systemd user services for local AI; never adopts existing backend units."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import auth
import ai_health

BACKENDS=('llamacpp','vllm','ollama')
MARKER='# Managed by automation-toolkit AI service v1'


def checked(path):
    path=Path(path).expanduser()
    if not path.is_absolute():raise ValueError('Service paths must be absolute')
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('Symlink service paths are forbidden')
    return path


def paths(backend):
    if backend not in BACKENDS: raise ValueError('Unsupported managed backend')
    config=checked(Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config'))))
    return checked(config/'automation-toolkit/ai'/backend/'service.json'), checked(config/'systemd/user'/f'automation-ai-{backend}.service')


def private_json(path,value):
    checked(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.parent.stat().st_uid!=os.getuid() or path.parent.stat().st_mode&0o077:
        raise ValueError('AI configuration directory must be private (0700)')
    fd,stage=tempfile.mkstemp(prefix='.service-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(stage,path)
    finally:
        if os.path.exists(stage):os.unlink(stage)


def validate(value, *, assets=True):
    keys={'schema','backend','executable','model','port','context','threads','key_file','cpu_quota'}
    if not isinstance(value,dict) or not keys<=set(value) or set(value)-keys-{'model_alias','vllm_options'} or type(value['schema']) is not int or value['schema']!=1 or value['backend'] not in BACKENDS:
        raise ValueError('Invalid managed AI configuration schema')
    alias=value.get('model_alias')
    if alias is not None:
        import re
        if value['backend'] not in ('llamacpp','vllm') or not isinstance(alias,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}',alias):
            raise ValueError('Invalid served model alias')
    options=value.get('vllm_options',{})
    if not isinstance(options,dict) or set(options)-{'dtype','kv_cache_gib','omp_bind','tool_parser'} or options and value['backend']!='vllm':
        raise ValueError('Invalid vLLM runtime option schema')
    if options.get('dtype','auto') not in ('auto','bfloat16','float32','float16'):
        raise ValueError('Unsupported reviewed vLLM dtype')
    if type(options.get('kv_cache_gib',1)) is not int or not 1<=options.get('kv_cache_gib',1)<=64:
        raise ValueError('vLLM CPU KV cache must be 1–64 GiB')
    if options.get('omp_bind','nobind')!='nobind':raise ValueError('Only reviewed CPU nobind affinity is supported')
    if options.get('tool_parser') not in (None,'hermes','qwen3_coder'):raise ValueError('Unsupported native tool parser')
    if not isinstance(value['executable'],str) or not value['executable']:raise ValueError('Select a reviewed backend executable')
    for field in ('model','key_file'):
        if value[field] is not None and not isinstance(value[field],str):raise ValueError('AI model/key paths must be literal strings')
    if value['backend'] in ('llamacpp','vllm') and not value['model']:raise ValueError('Select an existing absolute local model path')
    for key,low,high in [('port',1024,65535),('context',128,1048576),('threads',1,4096),('cpu_quota',1,10000)]:
        if type(value[key]) is not int or not low<=value[key]<=high:raise ValueError('Invalid managed AI numeric setting: '+key)
    executable=Path(value['executable'])
    if not executable.is_absolute():raise ValueError('AI executable must be absolute')
    if not assets:
        for field in ('model','key_file'):
            if value[field] is not None and (not isinstance(value[field],str) or not Path(value[field]).is_absolute()):
                raise ValueError('AI model/key paths must be absolute')
        return value
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable,os.X_OK):
        raise ValueError('Managed AI executable must be an existing absolute executable')
    if executable.stat().st_mode&0o022 or executable.stat().st_uid not in (0,os.getuid()):raise ValueError('AI executable must be trusted and cannot be group/world writable')
    if value['backend']=='llamacpp':
        path=checked(value['model'])
        if not path.is_file() or path.suffix.lower()!='.gguf':raise ValueError('Select an existing absolute GGUF model')
    elif value['backend']=='vllm':
        path=checked(value['model'])
        if not path.is_dir() or not (path/'config.json').is_file():
            raise ValueError('vLLM requires an existing local model directory with config.json; remote code/downloads are disabled')
    elif value['model'] is not None or value['key_file'] is not None:
        raise ValueError('Ollama service does not support toolkit model or native key overrides')
    if value['key_file'] is not None:checked(value['key_file'])
    return value


def read(backend):
    config,_=paths(backend)
    checked(config)
    st=config.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>16384 or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise ValueError('Managed AI configuration must be private and owned by this user')
    value=validate(json.loads(config.read_text()),assets=False)
    if value['backend']!=backend:raise ValueError('Managed AI backend mismatch')
    return value


def invocation(value):
    value=validate(value); backend=value['backend']
    env=os.environ.copy()
    # Local model execution must not become a dependency/model downloader.
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if value['key_file']:auth.read(Path(value['key_file']))
    if backend=='llamacpp':
        cmd=[value['executable'],'--model',value['model'],'--host','127.0.0.1','--port',str(value['port']),
             '--ctx-size',str(value['context']),'--threads',str(value['threads']),'--n-gpu-layers','0']
        if value['key_file']:cmd+=['--api-key-file',value['key_file']]
        if value.get('model_alias'):cmd+=['--alias',value['model_alias']]
    elif backend=='vllm':
        cmd=[value['executable'],'serve',value['model'],'--host','127.0.0.1','--port',str(value['port']),
             '--max-model-len',str(value['context'])]
        options=value.get('vllm_options',{})
        if value.get('model_alias'):cmd+=['--served-model-name',value['model_alias']]
        if options.get('dtype'):cmd+=['--dtype',options['dtype']]
        if options.get('tool_parser'):cmd+=['--enable-auto-tool-choice','--tool-call-parser',options['tool_parser']]
        # Do not inherit a stale secret, remote-model cache or unreviewed vLLM
        # environment hook from a shell or the retired service configuration.
        for name in list(env):
            if name.startswith('VLLM_') or name in ('HF_HOME','HF_HUB_CACHE','HF_MODULES_CACHE','TRANSFORMERS_CACHE','LD_PRELOAD','PYTHONPATH','PYTHONSTARTUP'):
                env.pop(name,None)
        cache=runtime_cache()
        env.update(OMP_NUM_THREADS=str(value['threads']),VLLM_CPU_KVCACHE_SPACE=str(options.get('kv_cache_gib',1)),
            VLLM_CPU_OMP_THREADS_BIND='nobind',VLLM_CACHE_ROOT=str(cache),VLLM_NO_USAGE_STATS='1',VLLM_PLUGINS='',
            HF_HOME=str(cache/'huggingface'),HF_HUB_CACHE=str(cache/'huggingface/hub'),HF_MODULES_CACHE=str(cache/'modules'),DO_NOT_TRACK='1')
        if value['key_file']:env['VLLM_API_KEY']=auth.read(Path(value['key_file']))
    else:
        cmd=[value['executable'],'serve']
        for name in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):
            env.pop(name,None)
        env['OLLAMA_HOST']='127.0.0.1:'+str(value['port'])
        env['OLLAMA_CONTEXT_LENGTH']=str(value['context'])
    return cmd,env


def runtime_cache():
    path=checked(Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'automation-toolkit/ai/vllm')
    if path.exists() and (not path.is_dir() or path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077):
        raise ValueError('Toolkit vLLM runtime cache must be private and owned')
    return path


def prepare_runtime(value):
    if value['backend']=='vllm':
        path=runtime_cache();path.mkdir(mode=0o700,parents=True,exist_ok=True)
        runtime_cache()  # Revalidate ownership/permissions after creation.


def quote(value):
    if any(ord(c)<32 for c in value):raise ValueError('Control characters in systemd argument')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def unit_text(backend,value):
    config,_=paths(backend)
    command=[str(Path(sys.executable).resolve()),str(Path(__file__).resolve()),'--run',backend,str(config.parents[3])]
    return '\n'.join([MARKER,'[Unit]','Description=Automation Toolkit local AI '+backend,'[Service]','Type=simple',
        'ExecStart='+ ' '.join(quote(x) for x in command),'Restart=on-failure','RestartSec=3',
        'TimeoutStopSec=20','KillMode=control-group','NoNewPrivileges=yes','UMask=0077',
        'CPUQuota='+str(value['cpu_quota'])+'%','[Install]','WantedBy=default.target',''])


def owned(backend):
    config,unit=paths(backend)
    if not unit.exists():return False
    checked(unit)
    if not unit.is_file() or unit.stat().st_size>16384 or unit.stat().st_uid!=os.getuid():
        raise ValueError('Unsafe AI unit')
    value=read(backend)
    if unit.read_text()!=unit_text(backend,value):
        raise ValueError('Unit differs from the toolkit-owned configuration; refusing to modify it')
    return True


def control(*args):
    try:return subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=30).returncode
    except (OSError,subprocess.TimeoutExpired):return 3


def port_available(port):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',port))
        except OSError:return False
    return True


def configure(args):
    config,unit=paths(args.backend)
    if unit.exists() and not owned(args.backend):raise ValueError('Existing unrelated AI unit; refusing adoption')
    old=read(args.backend) if config.exists() else None
    import resources
    resources.apply(args,old)
    if unit.exists() and control('is-active','--quiet',unit.name)==0 and not args.dry_run:
        print('Stop this toolkit service explicitly before changing its configuration.');return 3
    import portable
    choices={'llamacpp':str(portable.ROOT/'llamacpp/build/bin/llama-server'),'vllm':shutil.which('vllm'),'ollama':shutil.which('ollama')}
    executable=args.executable or (old or {}).get('executable') or choices[args.backend]
    if args.backend=='llamacpp' and (not executable or not Path(executable).is_file()):executable=shutil.which('llama-server')
    if not executable:print('Install a reviewed backend executable before service configuration.');return 3
    value={'schema':1,'backend':args.backend,'executable':str(Path(executable).expanduser().resolve()),
        'model':args.model or (old or {}).get('model'),
        'port':args.port or (old or {}).get('port') or ai_health.DEFAULT_PORTS[args.backend],
        'context':args.context or (old or {}).get('context') or 4096,
        'threads':args.cpu_threads or (old or {}).get('threads') or min(4,os.cpu_count() or 1),
        'cpu_quota':int(args.cpu_quota[:-1]) if args.cpu_quota else (old or {}).get('cpu_quota',300),
        'key_file':str(args.key_file) if args.key_file else (old or {}).get('key_file')}
    alias=getattr(args,'model_alias',None) or (old or {}).get('model_alias')
    if alias is not None:value['model_alias']=alias
    options=dict((old or {}).get('vllm_options',{}))
    for name,flag in (('dtype','dtype'),('kv_cache_gib','kv_cache_gib'),('tool_parser','tool_parser')):
        option=getattr(args,flag,None)
        if option is not None:options[name]=option
    if options:value['vllm_options']=options
    validate(value)
    if value['key_file']:auth.read(Path(value['key_file']))
    if args.dry_run:print('Dry run: would configure only',unit.name);return 0
    if not args.yes:print('Service configuration requires --yes.');return 4
    unit.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if unit.parent.stat().st_uid!=os.getuid() or unit.parent.stat().st_mode&0o022:
        raise ValueError('User unit directory must be owned by this user and not group/world writable')
    previous=unit.read_bytes() if unit.exists() else None
    previous_config=config.read_bytes() if config.exists() else None
    text=unit_text(args.backend,value)
    try:
        private_json(config,value)
        fd,stage=tempfile.mkstemp(prefix='.automation-ai-',dir=unit.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
            os.replace(stage,unit)
        finally:
            if os.path.exists(stage):os.unlink(stage)
        if control('daemon-reload'):raise ValueError('systemd user daemon-reload failed')
    except BaseException:
        if previous is None:unit.unlink(missing_ok=True)
        else:unit.write_bytes(previous)
        if previous_config is None:config.unlink(missing_ok=True)
        else:private_json(config,json.loads(previous_config))
        control('daemon-reload')
        raise
    print('Configured:',unit.name,'; existing services and models preserved. Start/autostart require separate commands.')
    return 0


def main(args):
    if args.backend not in BACKENDS:return 3
    config,unit=paths(args.backend);action=args.action
    if action=='service-status':
        if not unit.exists():print('No toolkit-owned AI user service.');return 0
        if not owned(args.backend):return 3
        print('Toolkit service:',unit.name,'active:',control('is-active','--quiet',unit.name)==0)
        return 0
    if action=='logs':
        if not unit.exists():print('No toolkit-owned service logs.');return 3
        owned(args.backend)
        cp=subprocess.run(['journalctl','--user','-u',unit.name,'--no-pager','-n','100','-o','cat'],capture_output=True,text=True,timeout=15)
        text=cp.stdout
        value=read(args.backend)
        if value['key_file'] and Path(value['key_file']).exists():text=text.replace(auth.read(Path(value['key_file'])),'********')
        import re
        text=re.sub(r'sk-local-[A-Za-z0-9_-]+','********',text)
        print(text,end='');return cp.returncode
    if not args.dry_run and (not shutil.which('systemctl') or control('show-environment')):
        print('An active systemd user session is required; no services changed.');return 3
    if action=='configure':return configure(args)
    if not owned(args.backend):print('Configure a toolkit-owned AI service first.');return 3
    if args.dry_run:print('Dry run:',action,unit.name);return 0
    if not args.yes:print('Service changes require --yes.');return 4
    if action in ('start','restart'):
        value=read(args.backend)
        invocation(value)  # Validate assets/key before stopping or starting a unit.
        if action=='start' and control('is-active','--quiet',unit.name)==0:return 0
        if action=='start' and not port_available(value['port']):print('Selected loopback port is occupied; no service started.');return 3
        result=control(action,unit.name)
        if result:return result
        # Systemd success is a process result, not proof of model/API readiness.
        print('Service command accepted. Verify readiness with test-api and authentication with test-auth.')
        return 0 if control('is-active','--quiet',unit.name)==0 else 3
    if action=='stop':return control('stop',unit.name)
    if action=='autostart':return control('enable' if args.enabled=='yes' else 'disable',unit.name)
    if action=='uninstall':
        if control('disable','--now',unit.name):return 3
        unit.unlink()
        print('Removed toolkit service unit only. Model files, binaries, keys and saved configuration retained.')
        return control('daemon-reload')
    raise ValueError('Unsupported AI service action')


if __name__=='__main__':
    try:
        if len(sys.argv)!=4 or sys.argv[1]!='--run':raise ValueError('Managed service runtime only')
        backend=sys.argv[2]
        os.environ['XDG_CONFIG_HOME']=str(checked(sys.argv[3]))
        if not owned(backend):raise ValueError('Service ownership not verified')
        value=read(backend)
        cmd,env=invocation(value)
        prepare_runtime(value)
        os.umask(0o077)
        os.execve(cmd[0],cmd,env)
    except (OSError,ValueError):
        print('Managed AI runtime configuration failed validation.',file=sys.stderr);sys.exit(3)
