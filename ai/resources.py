"""Read-only CPU/memory/port planning; device presence never enables a GPU."""
from __future__ import annotations
import math
import os
from pathlib import Path
import socket
import ai_health

ROOT=Path(__file__).resolve().parents[1]


def settings():
    from automation import config_file,validate_settings
    result=config_file(ROOT/'config/defaults.env')
    result.update(config_file(ROOT/'.env'))
    return validate_settings(result)


def budget(details):
    cores=float(details.get('cpu_threads') or 1)
    try:cores=min(cores,float(len(os.sched_getaffinity(0))))
    except (AttributeError,OSError):pass
    try:
        quota,period=Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota!='max':cores=min(cores,int(quota)/int(period))
    except (OSError,ValueError,ZeroDivisionError):pass
    memory=details.get('available_memory_mib')
    try:
        limit=Path('/sys/fs/cgroup/memory.max').read_text().strip()
        used=int(Path('/sys/fs/cgroup/memory.current').read_text())
        if limit!='max':memory=min(memory,int(limit)//1048576-used//1048576) if memory is not None else max(0,(int(limit)-used)//1048576)
    except (OSError,ValueError):pass
    return max(0.01,cores),memory


def free_port(backend,host='127.0.0.1'):
    family=socket.AF_INET6 if host=='::1' else socket.AF_INET
    address='::1' if family==socket.AF_INET6 else '127.0.0.1'
    start=ai_health.DEFAULT_PORTS[backend]
    for port in range(start,min(65536,start+100)):
        with socket.socket(family,socket.SOCK_STREAM) as listener:
            try:listener.bind((address,port))
            except OSError:continue
            return port
    raise ValueError('No free loopback port in this backend range; choose an explicit port')


def apply(args,old=None):
    config=settings();old=old or {}
    selections={}
    for flag,key,stored in (('cpu_threads','AUTOMATION_AI_THREADS','threads'),('cpu_quota','AUTOMATION_AI_QUOTA','cpu_quota'),('port','AUTOMATION_AI_PORT','port')):
        chosen=getattr(args,flag,None)
        if chosen is None and stored in old:chosen=str(old[stored])+'%' if flag=='cpu_quota' else old[stored]
        selections[flag]=config.get(key,'auto') if chosen is None else chosen
    details=ai_health.hardware() if 'auto' in selections.values() or getattr(args,'action',None)=='resources' else {}
    cores,memory=budget(details)
    count=max(1,min(32,int(cores)-1 if cores>=2 else 1))
    if memory is not None:count=max(1,min(count,max(0,memory)//256))
    resolved={}
    for flag,key,stored,automatic in (
        ('cpu_threads','AUTOMATION_AI_THREADS','threads',count),
        ('cpu_quota','AUTOMATION_AI_QUOTA','cpu_quota',str(max(1,min(10000,int(min(cores,count)*100))))+'%'),
        ('port','AUTOMATION_AI_PORT','port',None)):
        chosen=selections[flag]
        host='127.0.0.1' if getattr(args,'action',None) in ('configure','model-select') else getattr(args,'host','127.0.0.1')
        if chosen=='auto':chosen=free_port(args.backend,host) if flag=='port' else automatic
        if flag!='cpu_quota':chosen=int(chosen)
        setattr(args,flag,chosen);resolved[key]=chosen
    if getattr(args,'context',None) is None and not old:args.context=int(config.get('AUTOMATION_AI_CONTEXT','4096'))
    return {**resolved,'cpu_budget':cores,'available_memory_mib':memory,
            'acceleration':'not inferred; CPU settings only','note':'A free port is a planning observation; startup rechecks it. Model memory and GPU runtime support require separate verification.'}
