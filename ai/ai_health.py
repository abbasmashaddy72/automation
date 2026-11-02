"""Localhost-only AI runtime probing and read-only hardware assessment.

No device driver installation or runtime changes are performed here.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.error
import urllib.request

DEFAULT_PORTS = {'ollama':11434, 'llamacpp':8080, 'vllm':8000, 'jan':1337}
API_ROUTES = {'ollama':'/api/tags', 'llamacpp':'/health', 'vllm':'/v1/models','jan':'/v1/models'}
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def hardware():
    data={'architecture':platform.machine(), 'cpu_threads':os.cpu_count() or 1,
          'memory_mib':None,'available_memory_mib':None,'storage_free_mib':None,'gpu_memory_mib':[],
          'gpu_tools':{name:bool(shutil.which(name)) for name in
                 ('nvidia-smi','rocminfo','vulkaninfo')},'gpu_devices':[]}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemTotal:'):
                data['memory_mib']=int(line.split()[1])//1024
            if line.startswith('MemAvailable:'):
                data['available_memory_mib']=int(line.split()[1])//1024
    except (OSError, ValueError, IndexError): pass
    try: data['storage_free_mib']=shutil.disk_usage(Path.home()).free//1048576
    except OSError: pass
    if data['gpu_tools']['nvidia-smi']:
        try:
            result=subprocess.run(['nvidia-smi','--query-gpu=memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
            if result.returncode==0:
                data['gpu_memory_mib']=[int(row.strip()) for row in result.stdout.splitlines() if row.strip().isdigit()][:16]
        except (OSError,subprocess.TimeoutExpired): pass
    try:
        drm=Path('/sys/class/drm')
        for card in sorted(drm.glob('card[0-9]*')):
            vendor=card/'device/vendor'
            if vendor.is_file():
                value=vendor.read_text().strip()
                data['gpu_devices'].append({'device':card.name,'vendor':value,
                    'manufacturer':{'0x10de':'NVIDIA','0x1002':'AMD','0x8086':'Intel'}.get(value,'unknown')})
    except OSError: pass
    data['acceleration_note']='Tool/device detection is not confirmation of CUDA/ROCm/Vulkan runtime compatibility'
    return data


def print_hardware(*, as_json=False):
    details=hardware()
    if as_json: print(json.dumps(details, indent=2,sort_keys=True))
    else:
        print('Architecture:',details['architecture'])
        print('CPU threads:',details['cpu_threads'])
        print('RAM (MiB):',details['memory_mib'])
        print('GPU tool availability:',details['gpu_tools'])
        print('DRM devices:',details['gpu_devices'])
        print(details['acceleration_note'])
    return 0


def endpoint(backend, host, port):
    if backend not in API_ROUTES: raise ValueError('Unsupported AI backend')
    if host not in LOCAL_HOSTS: raise ValueError('Remote AI API checks are not enabled: use localhost')
    if not isinstance(port,int) or port < 1 or port > 65535: raise ValueError('Invalid API port')
    hostname='[::1]' if host=='::1' else '127.0.0.1' if host=='localhost' else host
    return f'http://{hostname}:{port}{API_ROUTES[backend]}'


def auth_headers(key_file=None):
    if key_file is None: return {}
    import auth
    return {'Authorization':'Bearer '+auth.read(key_file)}


def model_inventory(backend,host='127.0.0.1',port=None,*,key_file=None):
    if backend not in ('vllm','jan'):raise ValueError('OpenAI model inventory supports vLLM/Jan')
    url=endpoint(backend,host,port if port is not None else DEFAULT_PORTS[backend])
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(urllib.request.Request(url,headers=auth_headers(key_file)),timeout=5) as response:
            raw=response.read(65537)
            if response.status!=200 or len(raw)>65536:raise ValueError('Invalid model inventory')
        value=json.loads(raw)
        if not isinstance(value,dict) or not isinstance(value.get('data'),list):raise ValueError('Invalid model inventory schema')
        names=[row['id'] for row in value['data'] if isinstance(row,dict) and isinstance(row.get('id'),str)]
        print(json.dumps({'backend':backend,'models':names[:250]},indent=2));return 0
    except (OSError,ValueError) as exc:
        if isinstance(exc,urllib.error.HTTPError):exc.close()
        print('Model inventory unavailable:',type(exc).__name__);return 3


def check_api(backend, host='127.0.0.1', port=None, *, key_file=None):
    url=endpoint(backend,host,port if port is not None else DEFAULT_PORTS[backend])
    request=urllib.request.Request(url,headers={'User-Agent':'LinuxAutomationToolkit/3',**auth_headers(key_file)})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None  # Never follow redirects to non-loopback addresses.
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(request,timeout=5) as response:
            status=response.status
            payload=response.read(65537)
        if 200 <= status < 300:
            if len(payload)>65536: raise ValueError('API response too large')
            body=json.loads(payload)
            if not isinstance(body,dict): raise ValueError('API object required')
            if backend=='llamacpp':
                if body.get('status')=='loading model':
                    print('Model is still loading; inference readiness not confirmed'); return 5
                if body.get('status')!='ok': raise ValueError('Invalid health response')
            elif not isinstance(body.get('models' if backend=='ollama' else 'data'),list):
                raise ValueError('Invalid model inventory response')
            print(f'{backend} local API healthy: {url} (HTTP {status})')
            return 0
        print(f'{backend} HTTP {status}: {url}')
        return 3
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError) as error:
        if isinstance(error,urllib.error.HTTPError): error.close()
        print(f'{backend} API unavailable at {url}: {type(error).__name__}')
        return 3


def runtime_context(backend, host='127.0.0.1', port=None, desired=None, *, key_file=None):
    """Compare *running* context, never merely configured context.

    llama.cpp exposes effective per-slot n_ctx from GET /props; Ollama exposes
    model context_length for currently loaded models from GET /api/ps.
    """
    if backend not in ('llamacpp','ollama','vllm'):
        print('Runtime context inspection is not implemented for this backend.')
        return 3
    from urllib.parse import urlsplit
    address=urlsplit(endpoint(backend,host,port if port is not None else DEFAULT_PORTS[backend]))
    route={'llamacpp':'/props','ollama':'/api/ps','vllm':'/v1/models'}[backend]
    url=f'{address.scheme}://{address.netloc}{route}'
    # endpoint() has already validated the literal loopback address and port.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(urllib.request.Request(url,headers=auth_headers(key_file)),timeout=5) as response:
            if response.status != 200: return 3
            raw=response.read(65537)
            if len(raw)>65536: raise ValueError('Context response too large')
            payload=json.loads(raw)
            if not isinstance(payload,dict): raise ValueError('Invalid context response')
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        if isinstance(exc,urllib.error.HTTPError): exc.close()
        print(f'Unable to inspect {backend} runtime context: {type(exc).__name__}')
        return 3
    if backend=='llamacpp':
        settings=payload.get('default_generation_settings',{})
        if not isinstance(settings,dict): print('Invalid runtime settings response'); return 3
        contexts=[('running llama.cpp',settings.get('n_ctx'))]
    elif backend=='ollama':
        if not isinstance(payload.get('models',[]),list): print('Invalid model inventory response'); return 3
        contexts=[(row.get('name','unnamed'),row.get('context_length'))
                  for row in payload.get('models',[]) if isinstance(row,dict)]
    else:
        if not isinstance(payload.get('data'),list):print('Invalid vLLM model cards');return 3
        contexts=[(row.get('id','unnamed'),row.get('max_model_len')) for row in payload['data'] if isinstance(row,dict)]
    if not contexts:
        print('No loaded model/context information reported by server.')
        return 3
    mismatch=False
    for name,current in contexts:
        print(f'{name}: effective context={current} tokens')
        if not isinstance(current,int) or current<1:
            print('Context size unavailable for this model')
            mismatch=True
        elif desired is not None and current<desired:
            print(f'WARNING: active runtime context {current} is below requested {desired}')
            mismatch=True
    return 5 if mismatch else 0


def smoke_inference(backend, model, host='127.0.0.1', port=None, *, timeout=35, key_file=None):
    """Opt-in bounded inference on an already-running loopback-only service.

    A health response is not proof of generation. This sends a minimal prompt,
    rejects redirects/proxies and checks for nonempty generated text. No models
    are downloaded and no service is installed or restarted.
    """
    import re
    if backend not in API_ROUTES: raise ValueError('Unsupported backend')
    if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}',model):
        raise ValueError('Invalid model ID')
    if not isinstance(timeout,(int,float)) or not 1 <= timeout <= 120:
        raise ValueError('Inference timeout must be between 1 and 120 seconds')
    from urllib.parse import urlsplit
    parsed=urlsplit(endpoint(backend,host,port if port is not None else DEFAULT_PORTS[backend]))
    base=f'{parsed.scheme}://{parsed.netloc}'
    if backend=='ollama':
        route='/api/generate'
        payload={'model':model,'prompt':'Reply with OK.','stream':False,'options':{'num_predict':12}}
    elif backend=='llamacpp':
        route='/completion'
        payload={'prompt':'Reply with OK.','n_predict':12,'stream':False}
    else:
        route='/v1/chat/completions'
        payload={'model':model,'messages':[{'role':'user','content':'Reply with OK.'}],
                 'max_tokens':16,'stream':False}
    request=urllib.request.Request(base+route,data=json.dumps(payload).encode('utf-8'),
                                   headers={'Content-Type':'application/json','User-Agent':'LinuxAutomationToolkit/4',**auth_headers(key_file)},
                                   method='POST')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,request,fp,code,msg,headers,newurl):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(request,timeout=timeout) as response:
            if response.status!=200:
                print(f'{backend} inference failed: HTTP {response.status}')
                return 3
            raw=response.read(262145)
        if len(raw)>262144:
            print(f'{backend} inference failed: oversized response')
            return 3
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('error'):
            print(f'{backend} inference failed: invalid/error response')
            return 3
        if backend=='ollama': answer=data.get('response')
        elif backend=='llamacpp': answer=data.get('content')
        else:
            choices=data.get('choices')
            answer=choices[0].get('message',{}).get('content') if isinstance(choices,list) and choices and isinstance(choices[0],dict) else None
        if not isinstance(answer,str) or not answer.strip():
            print(f'{backend} inference failed: no generated text')
            return 5
        print(f'{backend} local inference confirmed: nonempty generation (output redacted)')
        return 0
    except (OSError,ValueError,urllib.error.HTTPError,urllib.error.URLError) as exc:
        if isinstance(exc,urllib.error.HTTPError): exc.close()
        print(f'{backend} inference unavailable: {type(exc).__name__}')
        return 3
