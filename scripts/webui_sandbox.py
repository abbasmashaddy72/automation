#!/usr/bin/env python3
"""Opt-in actual Open WebUI auth/persistence/recovery in isolated rootless resources."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import webui
from validate import output_path

MARKER = 'org.automation-toolkit.webui-sandbox'


def request(port, path, *, token=None, body=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args): return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    headers = {'Content-Type':'application/json'}
    if token is not None: headers['Authorization']='Bearer '+token
    req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
        data=json.dumps(body).encode() if body is not None else None,headers=headers)
    try:
        with opener.open(req,timeout=4) as response:
            data=response.read(1_000_001)
            if len(data)>1_000_000: raise ValueError('Oversized fixture response')
            return response.status,json.loads(data)
    except urllib.error.HTTPError as exc:
        return exc.code,None


def ready(port):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        try:
            status,data=request(port,'/health')
            if status==200 and isinstance(data,dict) and data.get('status') is True:return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise ValueError('Actual app readiness deadline exceeded; private app logs were not retained')


def probe(image, *, allow_pull=False):
    if os.geteuid()==0 or not shutil.which('podman'):return {'status':'skip','reason':'rootless_podman_required'}
    webui.run_command(image,3000,'review')
    if webui.call(['info','--format','{{.Host.Security.Rootless}}']).stdout.strip()!='true':
        return {'status':'skip','reason':'rootless_podman_required'}
    if webui.inspect('image',image) is None and not allow_pull:
        return {'status':'skip','reason':'pinned_image_not_cached_pull_not_authorized','image':image}
    nonce=uuid.uuid4().hex
    name='automation-webui-test-'+nonce
    volume=name+'-data'; network=name+'-net'
    original_call=webui.call
    network_created=False
    result={'status':'fail','image':image,'checks':{},'teardown':False}
    def invoke(command,**kwargs):
        command=list(command)
        if command[0]=='run':
            command[1:1]=['--network',network,'--label',MARKER+'='+nonce,
                '--memory=1g','--cpus=2','--pids-limit=256','--cap-drop=ALL',
                '--security-opt=no-new-privileges','--env','ENABLE_OLLAMA_API=False',
                '--env','ENABLE_OPENAI_API=False','--env','OFFLINE_MODE=True',
                '--env','HF_HUB_OFFLINE=1','--env','DO_NOT_TRACK=True',
                '--env','ANONYMIZED_TELEMETRY=False']
        elif command[:2]==['volume','create']:
            command[2:2]=['--label',MARKER+'='+nonce]
        return original_call(command,**kwargs)
    def action(*args):
        with contextlib.redirect_stdout(io.StringIO()):return webui.main(list(args))
    with tempfile.TemporaryDirectory(prefix='automation-webui-fixture-') as temp,\
         patch.dict(os.environ,{'XDG_STATE_HOME':temp}),patch.object(webui,'NAME',name),\
         patch.object(webui,'VOLUME',volume),patch.object(webui,'call',side_effect=invoke):
        try:
            created=original_call(['network','create','--internal','--label',MARKER+'='+nonce,network])
            if created.returncode:raise ValueError('Isolated test network creation failed')
            network_created=True
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            writer=webui.write_metadata
            def interrupt(path,value,**kwargs):
                if path==webui.receipt_path():raise InterruptedError('fixture receipt interruption')
                return writer(path,value,**kwargs)
            flags=['install','--image',image,'--port',str(port),'--yes']
            if allow_pull:flags.append('--allow-pull')
            with patch.object(webui,'write_metadata',side_effect=interrupt):
                try: action(*flags)
                except InterruptedError:pass
                else:raise ValueError('Receipt interruption fixture did not execute')
            if webui.receipt() is not None or webui.pending() is None:raise ValueError('Interrupted creation did not preserve pending metadata')
            if action('recover','--yes'):raise ValueError('Actual container recovery failed')
            result['checks']['interrupted_recovery']=True
            ready(port)
            signup_status,signup=request(port,'/api/v1/auths/signup',body={
                'name':'Migration Fixture','email':'fixture-'+nonce+'@example.invalid',
                'password':secrets.token_urlsafe(32)})
            if signup_status!=200 or not isinstance(signup,dict) or not isinstance(signup.get('token'),str):
                raise ValueError('Fresh fixture account creation failed')
            token=signup['token']
            status,user=request(port,'/api/v1/auths/',token=token)
            if status!=200 or not isinstance(user,dict) or not user.get('id'):raise ValueError('Valid credential rejected by protected endpoint')
            for credential in (None,'invalid-fixture-token'):
                status,_=request(port,'/api/v1/auths/',token=credential)
                if status not in (401,403):raise ValueError('Invalid or absent credentials were not rejected')
            result['checks']['protected_endpoint_valid_invalid_absent']=True
            before=webui.receipt()
            for command in ('stop','remove','recreate'):
                if action(command,'--yes'):raise ValueError('Owned lifecycle action failed')
            ready(port)
            status,restored=request(port,'/api/v1/auths/',token=token)
            if status!=200 or restored.get('id')!=user['id'] or webui.receipt()['id']==before['id']:
                raise ValueError('Account/session did not survive actual container recreation')
            checked=original_call(['exec',webui.receipt()['id'],'sh','-c',
                'test "$(stat -c %a /app/backend/data/.webui_secret_key)" = 600'])
            if checked.returncode:raise ValueError('Persisted session key is not private')
            result['checks']['account_session_private_key_persistence']=True
            result['status']='pass'
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            # No HTTP response bodies, credentials or app logs are retained.
            result['reason']=type(exc).__name__
        finally:
            try:
                row=webui.inspect('container',name)
                if row is not None:
                    if row.get('Config',{}).get('Labels',{}).get(MARKER)!=nonce:raise ValueError('Foreign container in sandbox namespace')
                    if original_call(['rm','--force',row['Id']],timeout=120).returncode:raise ValueError('Container teardown failed')
                row=webui.inspect('volume',volume)
                if row is not None:
                    if row.get('Labels',{}).get(MARKER)!=nonce:raise ValueError('Foreign volume in sandbox namespace')
                    if original_call(['volume','rm',volume]).returncode:raise ValueError('Volume teardown failed')
                if network_created and original_call(['network','rm',network]).returncode:raise ValueError('Network teardown failed')
                result['teardown']=webui.inspect('container',name) is None and webui.inspect('volume',volume) is None
                if original_call(['network','exists',network]).returncode!=1:result['teardown']=False
            except (OSError,ValueError,subprocess.SubprocessError): result['teardown']=False
            if not result['teardown']:result['status']='fail';result['reason']='sandbox_teardown_incomplete'
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--yes',action='store_true',help='Approve only disposable fixture resources and fixture account')
    parser.add_argument('--allow-pull',action='store_true')
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    webui.run_command(args.image,3000,'review')
    if not args.yes:parser.error('Actual app testing requires --yes; image pulls separately require --allow-pull')
    output=output_path(args.output)
    result=probe(args.image,allow_pull=args.allow_pull)
    path=output/'webui-sandbox.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='pass' else 3


if __name__=='__main__':sys.exit(main())
