"""Import supported legacy unit settings as data, preserving the original unit/state.

No legacy commands are executed. Unknown flags, GPU settings and implicit remote
model resolution are refused. Stop/disable the old service separately first.
"""
from __future__ import annotations
from argparse import Namespace
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import auth
import services

UNITS={'llamacpp':('llamacpp-local.service','# Managed by 93-llamacpp-setup.sh'),
       'vllm':('vllm-local.service','# Managed by 92-vllm-playground-setup.sh')}


def parse(args):
    if args.backend not in UNITS:raise ValueError('Legacy settings migration supports CPU llama.cpp and reviewed vLLM CPU settings only')
    name,marker=UNITS[args.backend]
    expected=services.checked(Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'systemd/user'/name)
    if not args.legacy_unit or services.checked(args.legacy_unit)!=expected:raise ValueError('Select the exact old unit in your systemd user directory')
    st=expected.stat()
    if not expected.is_file() or st.st_uid!=os.getuid() or st.st_mode&0o022 or st.st_nlink!=1 or st.st_size>16384:
        raise ValueError('Legacy unit must be a bounded owned regular file, not writable by others')
    raw=expected.read_bytes();text=raw.decode('utf-8')
    if marker not in text.splitlines():raise ValueError('Unrecognized legacy unit ownership marker')
    commands=[];quota=None;section='';environment={};key_sources=[]
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('['):section=line
        allowed_directives={'Type','WorkingDirectory','CPUQuota','ExecStart','Restart','RestartSec','TimeoutStartSec'}
        if args.backend=='vllm':allowed_directives.update(('Environment','EnvironmentFile'))
        if section=='[Service]' and '=' in line and not line.startswith(('#',';')) and line.split('=',1)[0] not in allowed_directives:
            raise ValueError('Unsupported legacy service override; configure explicitly instead')
        if section=='[Service]' and line.startswith(('Environment=','EnvironmentFile=')):
            field,literal=line.split('=',1)
            if any(c in literal for c in ('%','$','`','\\')):raise ValueError('Legacy environment expansion is forbidden')
            tokens=shlex.split(literal)
            if field=='EnvironmentFile':
                if len(tokens)!=1 or key_sources:raise ValueError('Ambiguous legacy environment file')
                key_sources.append(services.checked(tokens[0]));continue
            for token in tokens:
                if '=' not in token:raise ValueError('Invalid literal legacy environment entry')
                key,item=token.split('=',1)
                allowed_env={'HF_HOME','HF_HUB_CACHE','VLLM_CACHE_ROOT','VLLM_CPU_KVCACHE_SPACE',
                    'VLLM_CPU_OMP_THREADS_BIND','OMP_NUM_THREADS','HF_HUB_DISABLE_TELEMETRY','LD_PRELOAD'}
                if key not in allowed_env or key in environment:raise ValueError('Unknown or duplicate legacy environment setting')
                environment[key]=item
        if section=='[Service]' and line.startswith('ExecStart='):commands.append(line[len('ExecStart='):])
        if section=='[Service]' and line.startswith('CPUQuota='):
            if quota is not None:raise ValueError('Duplicate CPU quota')
            quota=line[len('CPUQuota='):]
    if len(commands)!=1 or any(c in commands[0] for c in ('%','$','`','\\','\n')):
        raise ValueError('Ambiguous legacy command or executable expansion; configure explicitly instead')
    command=shlex.split(commands[0])
    if not command or not Path(command[0]).is_absolute():raise ValueError('Legacy executable must be an absolute native path')
    executable=command.pop(0)
    original_model=None
    if args.backend=='vllm':
        if len(command)<2 or command.pop(0)!='serve':raise ValueError('Only a native vLLM serve command can migrate')
        original_model=command.pop(0)
    options={}
    allowed=({'--model','--alias','--host','--port','--ctx-size','--n-gpu-layers','--threads','--threads-batch','--api-key-file'} if args.backend=='llamacpp' else
             {'--host','--port','--dtype','--max-model-len','--download-dir','--enable-auto-tool-choice','--tool-call-parser'})
    while command:
        flag=command.pop(0)
        if flag=='--enable-auto-tool-choice' and args.backend=='vllm':
            if flag in options:raise ValueError('Duplicate tool-choice flag')
            options[flag]=True;continue
        if flag not in allowed or flag in options or not command:raise ValueError('Unknown or duplicate legacy runtime flag; configure explicitly')
        options[flag]=command.pop(0)
    if options.get('--host','127.0.0.1')!='127.0.0.1':raise ValueError('Only literal IPv4 loopback legacy services can migrate')
    if options.get('--n-gpu-layers','0')!='0':raise ValueError('GPU runtime migration requires independent review; use explicit configuration')
    if options.get('--threads-batch',options.get('--threads'))!=options.get('--threads'):raise ValueError('Distinct batch threads require explicit configuration')
    model=args.model or options.get('--model') or original_model
    if not model or not Path(model).is_absolute():raise ValueError('Select an exact local model path; remote/cache model IDs are never resolved implicitly')
    key=args.key_file or options.get('--api-key-file')
    if 'LD_PRELOAD' in environment and not getattr(args,'ignore_legacy_preload',False):
        raise ValueError('Legacy executable allocator preload is not imported; review and use --ignore-legacy-preload to omit it explicitly')
    for field in ('HF_HOME','HF_HUB_CACHE','VLLM_CACHE_ROOT'):
        if field in environment:services.checked(environment[field])
    if '--download-dir' in options:services.checked(options['--download-dir'])
    if environment.get('HF_HUB_DISABLE_TELEMETRY','1')!='1':raise ValueError('Only disabled legacy telemetry settings are supported')
    if key_sources:
        if not args.key_file:raise ValueError('Import the private legacy key with key-import, then provide --key-file')
        import secrets
        if not secrets.compare_digest(auth.read_legacy(key_sources[0]),auth.read(args.key_file)):
            raise ValueError('Imported key differs from the legacy key; migrate keys separately before changing authentication')
    def number(flag,default):
        value=options.get(flag,str(default))
        if not re.fullmatch('[0-9]{1,7}',value):raise ValueError('Invalid legacy numeric value')
        return int(value)
    if quota is None:quota='300%'
    if not re.fullmatch(r'[1-9][0-9]{0,3}%',quota):raise ValueError('Invalid legacy CPU quota')
    if args.cpu_quota is not None and not re.fullmatch(r'[1-9][0-9]{0,3}%',args.cpu_quota):raise ValueError('Invalid requested CPU quota')
    value={'schema':1,'backend':args.backend,'executable':args.executable or executable,'model':model,
        'port':args.port or number('--port',8080 if args.backend=='llamacpp' else 8000),
        'context':args.context or number('--ctx-size' if args.backend=='llamacpp' else '--max-model-len',4096),
        'threads':args.cpu_threads or number('--threads',min(4,os.cpu_count() or 1)),
        'cpu_quota':int((args.cpu_quota or quota)[:-1]),'key_file':str(key) if key else None}
    alias=getattr(args,'model_alias',None) or options.get('--alias')
    if args.backend=='vllm':
        if not Path(original_model).is_absolute():
            import models
            models.repository(original_model)
            if alias is None:alias=original_model
        def env_integer(name,default):
            literal=environment.get(name,str(default))
            if not re.fullmatch('[0-9]{1,4}',literal):raise ValueError('Invalid legacy CPU environment integer')
            return int(literal)
        value['threads']=args.cpu_threads or env_integer('OMP_NUM_THREADS',value['threads'])
        parser=options.get('--tool-call-parser')
        if bool(options.get('--enable-auto-tool-choice'))!=bool(parser):raise ValueError('Tool choice and parser must be specified together')
        value['vllm_options']={'dtype':getattr(args,'dtype',None) or options.get('--dtype','auto'),
            'kv_cache_gib':getattr(args,'kv_cache_gib',None) or env_integer('VLLM_CPU_KVCACHE_SPACE',1),
            'omp_bind':environment.get('VLLM_CPU_OMP_THREADS_BIND','nobind')}
        parser=getattr(args,'tool_parser',None) or parser
        if parser:value['vllm_options']['tool_parser']=parser
    if alias is not None:value['model_alias']=alias
    services.validate(value)
    if key:auth.read(Path(key))
    return value,expected,raw


def main(args):
    value,path,original=parse(args)
    if args.action=='legacy-plan' or args.dry_run:
        print(json.dumps({'legacy_unit':path.name,'configuration':value,
            'note':'Supported settings only; old environment/key values never printed or executed. Stop and disable the old unit yourself before legacy-import. External model/cache paths are not adopted for runtime writes: vLLM uses a fresh private toolkit runtime cache. Original units, models and caches are preserved; no deletion receipt is granted.'},indent=2))
        return 0
    if not args.yes:print('Legacy import requires --yes after reviewing legacy-plan.');return 4
    config,unit=services.paths(args.backend)
    if config.exists() or unit.exists():raise ValueError('Toolkit configuration/unit already exists; legacy import never overwrites it')
    cp=subprocess.run(['systemctl','--user','show',path.name,'--property=ActiveState','--property=UnitFileState'],capture_output=True,text=True,timeout=10)
    if cp.returncode or len(cp.stdout)>4096:raise ValueError('Cannot establish old unit state; import refused')
    status=dict(line.split('=',1) for line in cp.stdout.splitlines() if '=' in line)
    if status.get('ActiveState') not in ('inactive','failed') or status.get('UnitFileState')!='disabled':
        raise ValueError('Old unit must be stopped and disabled before import; this command never changes it')
    if path.read_bytes()!=original:raise ValueError('Legacy unit changed during review')
    selected=Namespace(**{**vars(args),'action':'configure','executable':value['executable'],'model':value['model'],
        'port':value['port'],'context':value['context'],'cpu_threads':value['threads'],'cpu_quota':str(value['cpu_quota'])+'%',
        'key_file':Path(value['key_file']) if value['key_file'] else None,'model_alias':value.get('model_alias'),
        'dtype':value.get('vllm_options',{}).get('dtype'),'kv_cache_gib':value.get('vllm_options',{}).get('kv_cache_gib'),
        'tool_parser':value.get('vllm_options',{}).get('tool_parser')})
    result=services.main(selected)
    if result==0:print('Legacy settings imported. Original unit/state/models/keys preserved; start and autostart are separate reviewed actions.')
    return result
