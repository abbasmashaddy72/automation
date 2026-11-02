#!/usr/bin/env python3
"""Opt-in real tiny-model inference in a disposable rootless Podman container."""
from __future__ import annotations
import argparse
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
import uuid
from unittest.mock import patch
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ai'))
import ai_health
import auth
import models
import snapshots
import gguf

IMAGE='ghcr.io/ggml-org/llama.cpp:server'
SPLIT_IMAGE='ghcr.io/ggml-org/llama.cpp:full'
MODEL='stories260K.gguf'
URL='https://huggingface.co/ggml-org/tiny-llamas/resolve/def3e2dd70df35ecbf6403ea347de4c5977220c1/stories260K.gguf'
SHA='047bf46455a544931cff6fef14d7910154c56afbc23ab1c5e56a72e69912c04b'
SIZE=1185376
PULL_TIMEOUT=1800
VLLM_IMAGE='docker.io/vllm/vllm-openai-cpu:latest-x86_64'
VLLM_REPO='HuggingFaceTB/SmolLM2-135M-Instruct'
VLLM_REVISION='12fd25f77366fa6b3b4b768ec3050bf629380bac'
VLLM_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
VLLM_ARTIFACTS={
    'config.json':(861,'8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'),
    'generation_config.json':(132,'87b916edaaab66b3899b9d0dd0752727dff6666686da0504d89ae0a6e055a013'),
    'model.safetensors':(269060552,VLLM_SHA),
    'special_tokens_map.json':(655,'2b7379f3ae813529281a5c602bc5a11c1d4e0a99107aaa597fe936c1e813ca52'),
    'tokenizer.json':(2104556,'9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'),
    'tokenizer_config.json':(3764,'4ec77d44f62efeb38d7e044a1db318f6a939438425312dfa333b8382dbad98df'),
}


def run(argv,timeout=30):
    return subprocess.run(argv,capture_output=True,text=True,timeout=timeout)


def vllm_sandbox(*,allow_pull=False,allow_download=False,yes=False):
    """Independent CPU vLLM test, no host Python install or relaxed capabilities."""
    if not yes or not allow_download:raise ValueError('Real inference requires --yes --allow-download')
    if not shutil.which('podman'):return {'status':'skip','reason':'podman_unavailable'}
    if run(['podman','info','--format','{{.Host.Security.Rootless}}']).stdout.strip()!='true':return {'status':'skip','reason':'rootless_podman_required'}
    if run(['podman','image','exists',VLLM_IMAGE]).returncode:
        if not allow_pull:return {'status':'skip','reason':'CPU_vllm_image_not_cached'}
        if run(['podman','pull',VLLM_IMAGE],timeout=PULL_TIMEOUT).returncode:return {'status':'fail','reason':'vllm_image_pull_failed'}
    checks={};name='automation-vllm-smoke-'+uuid.uuid4().hex[:12]
    report={'status':'fail','backend':'vllm','model':VLLM_REPO,'revision':VLLM_REVISION,
        'image_id':run(['podman','image','inspect','--format','{{.Id}}',VLLM_IMAGE]).stdout.strip(),
        'scope':'CPU rootless container only; no host systemd/GPU/desktop verification','checks':checks}
    with tempfile.TemporaryDirectory(prefix='automation-vllm-smoke-') as td:
        temp=Path(td);model=temp/'model';model.mkdir()
        if shutil.disk_usage(temp).free<600*1024**2:raise ValueError('Insufficient disk for vLLM fixture')
        memory=ai_health.hardware().get('available_memory_mib')
        if memory is None or memory<7168:return {**report,'status':'skip','reason':'need_7_GiB_available_RAM_for_isolated_vllm_test'}
        # Only safetensors weights and literal JSON are downloaded; never remote Python.
        import hashlib
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),models.HTTPSRedirect())
        for filename,(size,checksum) in VLLM_ARTIFACTS.items():
            url='https://huggingface.co/'+VLLM_REPO+'/resolve/'+VLLM_REVISION+'/'+filename
            digest=hashlib.sha256();count=0
            with opener.open(url,timeout=30) as response,(model/filename).open('xb') as stream:
                while True:
                    chunk=response.read(min(1024**2,size-count+1))
                    if not chunk:break
                    count+=len(chunk)
                    if count>size:raise ValueError('vLLM fixture exceeds pinned size')
                    stream.write(chunk);digest.update(chunk)
            if count!=size:raise ValueError('vLLM fixture size mismatch')
            if digest.hexdigest()!=checksum:raise ValueError('vLLM fixture checksum mismatch')
        checks['safetensors_checksum']=True
        manifest={'schema':1,'repository':VLLM_REPO,'revision':VLLM_REVISION,
            'files':[{'path':filename,'size':size,'sha256':checksum} for filename,(size,checksum) in VLLM_ARTIFACTS.items()]}
        store=temp/'store'
        snapshots.import_snapshot(store,manifest,source=model,yes=True)
        active=snapshots.destination(store,manifest)
        checks['verified_snapshot_copy']=snapshots.owned(active)==manifest
        key=temp/'auth/api-key';auth.save(key,'sk-local-'+secrets.token_urlsafe(36))
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        runtime=temp/'runtime';runtime.mkdir()
        for module in ('services.py','auth.py','ai_health.py'):shutil.copy2(ROOT/'ai'/module,runtime/module)
        # Use the actual shared invocation builder. The sandbox alone adapts the
        # container's internal bind for rootless port publication; the host bind
        # remains 127.0.0.1. Normal managed services retain literal loopback.
        launcher=f"""import os,sys,shutil
sys.path.insert(0,'/smoke/runtime')
import services
value={{'schema':1,'backend':'vllm','executable':shutil.which('vllm'),
 'model':'/smoke/store/{VLLM_REPO}/{VLLM_REVISION}','model_alias':'tiny-fixture',
 'port':8000,'context':256,'threads':2,'cpu_quota':200,'key_file':'/smoke/auth/api-key',
 'vllm_options':{{'dtype':'float32','kv_cache_gib':1,'omp_bind':'nobind'}}}}
command,env=services.invocation(value)
services.prepare_runtime(value)
command[command.index('--host')+1]='0.0.0.0'
command+=['--max-num-seqs','1','--load-format','safetensors','--enforce-eager']
os.umask(0o077)
os.execve(command[0],command,env)
"""
        cmd=['podman','run','--rm','--pull=never','-d','--name',name,'--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--memory=6g','--cpus=2','--pids-limit=512','--shm-size=512m',
            '--env','HF_HUB_OFFLINE=1','--env','TRANSFORMERS_OFFLINE=1','--env','VLLM_CPU_KVCACHE_SPACE=1',
            '--env','VLLM_CPU_OMP_THREADS_BIND=nobind','--env','OMP_NUM_THREADS=2','--env','VLLM_NO_USAGE_STATS=1',
            '--env','DO_NOT_TRACK=1','--env','HOME=/tmp','--env','XDG_CACHE_HOME=/tmp/toolkit-cache',
            '-p',f'127.0.0.1:{port}:8000','--mount',f'type=bind,src={temp},dst=/smoke,readonly',
            '--entrypoint','python3',VLLM_IMAGE,'-c',launcher]
        try:
            started=run(cmd,timeout=60);checks['container_started']=started.returncode==0
            if started.returncode:report['reason']='container_start_failed';return report
            deadline=time.monotonic()+300;ready=False
            while time.monotonic()<deadline:
                if ai_health.check_api('vllm',port=port,key_file=key)==0:ready=True;break
                if run(['podman','inspect','--format','{{.State.Running}}',name]).stdout.strip()!='true':break
                time.sleep(2)
            checks['api_ready']=ready
            checks['shared_runtime_invocation']=ready
            if ready:
                checks['native_authentication']=auth.test_endpoint('vllm',key,port=port)==0
                checks['inference']=ai_health.smoke_inference('vllm','tiny-fixture',port=port,key_file=key,timeout=120)==0
                checks['invalid_auth_rejected']=ai_health.check_api('vllm',port=port)==3
                checks['effective_context']=ai_health.runtime_context('vllm',port=port,desired=256,key_file=key)==0
                checks['context_mismatch_detected']=ai_health.runtime_context('vllm',port=port,desired=512,key_file=key)==5
            if not ready or not checks.get('inference'):
                report['reason']='native_inference_failed' if ready else 'api_readiness_failed'
                # Private model fixture has no user data; redact the generated key.
                logs=run(['podman','logs','--tail','30',name])
                report['diagnostic']=(logs.stdout+logs.stderr).replace(auth.read(key),'********')[-16384:]
        finally:
            run(['podman','rm','-f',name],timeout=30)
            checks['container_removed']=run(['podman','container','exists',name]).returncode==1
            key.unlink(missing_ok=True)
        checks['endpoint_stopped']=ai_health.check_api('vllm',port=port)==3
        snapshots.remove_snapshot(store,VLLM_REPO,VLLM_REVISION,yes=True)
        checks['snapshot_removed']=not active.exists()
        checks['original_fixture_preserved']=models.digest(model/'model.safetensors')==VLLM_SHA
    report['status']='pass' if all(checks.values()) else 'fail'
    return report


def ollama_sandbox(*,allow_pull=False,allow_download=False,yes=False):
    """Official CPU container, imported verified fixture only; no host installer."""
    if not yes or not allow_download:raise ValueError('Real inference requires --yes --allow-download')
    image='docker.io/ollama/ollama:latest'
    if not shutil.which('podman'):return {'status':'skip','reason':'podman_unavailable'}
    if run(['podman','info','--format','{{.Host.Security.Rootless}}']).stdout.strip()!='true':return {'status':'skip','reason':'rootless_podman_required'}
    if run(['podman','image','exists',image]).returncode:
        if not allow_pull:return {'status':'skip','reason':'ollama_image_not_cached'}
        if run(['podman','pull',image],timeout=PULL_TIMEOUT).returncode:return {'status':'fail','reason':'ollama_image_pull_failed'}
    checks={};name='automation-ollama-smoke-'+uuid.uuid4().hex[:12]
    report={'status':'fail','backend':'ollama','checks':checks,
        'image_id':run(['podman','image','inspect','--format','{{.Id}}',image]).stdout.strip(),
        'scope':'official CPU container and private fixture; no native installer/systemd/GPU or API-key enforcement claim'}
    with tempfile.TemporaryDirectory(prefix='automation-ollama-smoke-') as td:
        temp=Path(td);model_root=temp/'models'
        checks['download_checksum']=models.download(model_root,MODEL,URL,SHA,SIZE,yes=True)==0
        (temp/'Modelfile').write_text('FROM /fixture/models/'+MODEL+'\nPARAMETER num_ctx 128\nPARAMETER num_thread 2\n')
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        command=['podman','run','--pull=never','--name',name,'-d','--read-only',
            '--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--memory=1g','--cpus=2','--pids-limit=256',
            '--tmpfs','/tmp:rw,nosuid,mode=1777,size=512m','--env','HOME=/tmp/ollama',
            '--env','OLLAMA_MODELS=/tmp/models','--env','OLLAMA_HOST=0.0.0.0:11434',
            '--env','OLLAMA_NUM_PARALLEL=1','-p',f'127.0.0.1:{port}:11434',
            '--mount',f'type=bind,src={temp},dst=/fixture,readonly',image,'serve']
        try:
            checks['container_started']=run(command,timeout=60).returncode==0
            if not checks['container_started']:return report
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if ai_health.check_api('ollama',port=port)==0:break
                if run(['podman','inspect','--format','{{.State.Running}}',name]).stdout.strip()!='true':break
                time.sleep(1)
            checks['api_ready']=ai_health.check_api('ollama',port=port)==0
            if checks['api_ready']:
                checks['model_import']=run(['podman','exec',name,'ollama','create','tiny-fixture','-f','/fixture/Modelfile'],timeout=120).returncode==0
                if checks['model_import']:
                    listing=run(['podman','exec',name,'ollama','list'])
                    checks['model_discovery']=listing.returncode==0 and 'tiny-fixture:latest' in listing.stdout
                    # Exercise the actual toolkit pull/reuse decision against
                    # the real container CLI; forbid any registry refresh.
                    import portable
                    native_run=subprocess.run;native_which=shutil.which
                    def container_cli(argv,**kwargs):
                        if argv and argv[0]=='ollama':argv=['podman','--remote=false','exec','--env','OLLAMA_HOST=127.0.0.1:11434',name,*argv]
                        return native_run(argv,**kwargs)
                    with patch.object(portable.subprocess,'run',side_effect=container_cli),patch.object(portable.shutil,'which',side_effect=lambda tool: '/fixture/ollama' if tool=='ollama' else native_which(tool)),patch.object(portable,'command',side_effect=ValueError('Cached model unexpectedly requested a registry refresh')):
                        checks['toolkit_cached_tag_reuse']=portable.pull_ollama(argparse.Namespace(model='tiny-fixture',yes=True,dry_run=False,host='127.0.0.1',port=11434,refresh_model=False))==0
                    checks['inference']=ai_health.smoke_inference('ollama','tiny-fixture',port=port,timeout=60)==0
                    checks['effective_context']=ai_health.runtime_context('ollama',port=port,desired=128)==0
                    checks['owned_fixture_removal']=run(['podman','exec',name,'ollama','rm','tiny-fixture']).returncode==0
                    listing=run(['podman','exec',name,'ollama','list'])
                    checks['model_removed']=listing.returncode==0 and 'tiny-fixture' not in listing.stdout
            checks['source_preserved']=models.digest(model_root/MODEL)==SHA
        finally:
            run(['podman','rm','-f',name],timeout=30)
            checks['container_removed']=run(['podman','container','exists',name]).returncode==1
        checks['endpoint_stopped']=ai_health.check_api('ollama',port=port)==3
    report['status']='pass' if checks and all(checks.values()) else 'fail'
    return report


def split_fixture(temp,model_root,store,checks):
    """Generate genuine tiny GGUF shards entirely in an unprivileged container."""
    name='automation-gguf-split-'+uuid.uuid4().hex[:12]
    legacy=temp/'legacy-shards';quant='fixture_shards';repo='ggml-org/tiny-llamas'
    folder=legacy/'models'/(repo.replace('/','--')+'--'+quant);folder.mkdir(parents=True,mode=0o700)
    command=['podman','run','--pull=never','-d','--name',name,'--read-only','--network=none',
        '--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--memory=256m','--cpus=2','--pids-limit=64','--tmpfs','/out:rw,noexec,nosuid,mode=1777,size=16m',
        '--mount',f'type=bind,src={model_root},dst=/input,readonly','--entrypoint','/bin/sh',SPLIT_IMAGE,
        '-c','/app/llama-gguf-split --split-max-tensors 4 /input/stories260K.gguf /out/tiny && touch /out/ready && sleep 120']
    try:
        result=run(command,timeout=60)
        if result.returncode:raise ValueError('GGUF split fixture container could not start')
        deadline=time.monotonic()+30;ready=False
        while time.monotonic()<deadline:
            if run(['podman','exec',name,'test','-f','/out/ready']).returncode==0:ready=True;break
            if run(['podman','inspect','--format','{{.State.Running}}',name]).stdout.strip()!='true':break
            time.sleep(0.5)
        if not ready:raise ValueError('Native GGUF splitter did not produce its fixture')
        if run(['podman','cp',name+':/out/.',str(folder)],timeout=30).returncode:raise ValueError('Could not copy generated fixture shards')
    finally:
        run(['podman','rm','-f',name],timeout=20)
        checks['split_helper_removed']=run(['podman','container','exists',name]).returncode==1
    names=sorted(path.name for path in folder.glob('*.gguf'))
    if not 2<=len(names)<=32:raise ValueError('Expected a genuine bounded multi-shard fixture')
    gguf.series(names)
    value={'schema':1,'repository':repo,'revision':'def3e2dd70df35ecbf6403ea347de4c5977220c1','quantization':quant,
        'files':[{'path':filename,'size':(folder/filename).stat().st_size,'sha256':models.digest(folder/filename),
                  'url':'https://fixture.invalid/'+filename} for filename in names]}
    (folder/gguf.MARKER).write_text(json.dumps({'directory':folder.name,'repository':repo,'quantization':quant,'files':names}))
    (legacy/'config').mkdir();(legacy/'config/selected-model').write_text(repo+'\n');(legacy/'config/runtime-settings').write_text('context=128\n')
    checks['sharded_legacy_import']=gguf.import_legacy(store,value,legacy,yes=True)==0
    return gguf.resolve(store,value),value


def sandbox(*, allow_pull=False, allow_download=False, yes=False,with_gguf_shards=False):
    if not yes or not allow_download: raise ValueError('Real inference requires --yes --allow-download')
    if not shutil.which('podman'): return {'status':'skip','reason':'podman_unavailable'}
    rootless=run(['podman','info','--format','{{.Host.Security.Rootless}}'])
    if rootless.returncode or rootless.stdout.strip() != 'true': return {'status':'skip','reason':'rootless_podman_required'}
    exists=run(['podman','image','exists',IMAGE])
    if exists.returncode:
        if not allow_pull: return {'status':'skip','reason':'image_not_cached_pull_not_authorized'}
        if run(['podman','pull',IMAGE],timeout=PULL_TIMEOUT).returncode: return {'status':'fail','reason':'image_pull_failed'}
    if with_gguf_shards and run(['podman','image','exists',SPLIT_IMAGE]).returncode:
        if not allow_pull:return {'status':'skip','reason':'split_image_not_cached_pull_not_authorized'}
        print('Preparing optional official CPU split-fixture image...',flush=True)
        if run(['podman','pull',SPLIT_IMAGE],timeout=PULL_TIMEOUT).returncode:return {'status':'fail','reason':'split_image_pull_failed'}
    image=run(['podman','image','inspect','--format','{{.Id}}',IMAGE]).stdout.strip()
    checks={}
    report={'status':'fail','backend':'llamacpp','model':MODEL,'model_bytes':SIZE,'model_sha256':SHA,
            'image_id':image,'scope':'CPU container only; no host services, GPU or desktop verification','checks':checks}
    name='automation-ai-smoke-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='automation-ai-smoke-') as td:
        temp=Path(td); model_root=temp/'models'; key=temp/'auth/api-key'
        checks['download_checksum']=models.download(model_root,MODEL,URL,SHA,SIZE,yes=True)==0
        checks['reuse_verified_cache']=models.download(model_root,MODEL,URL,SHA,SIZE,yes=True)==0
        bundle={'schema':1,'repository':'ggml-org/tiny-llamas','revision':'def3e2dd70df35ecbf6403ea347de4c5977220c1','quantization':'fixture',
            'files':[{'path':MODEL,'size':SIZE,'sha256':SHA,'url':URL}]}
        store=temp/'bundles'
        checks['verified_gguf_bundle']=gguf.download(store,bundle,yes=True)==0
        checks['verified_bundle_reuse']=gguf.download(store,bundle,yes=True)==0
        primary=gguf.resolve(store,bundle)
        auth.save(key,'sk-local-'+secrets.token_urlsafe(36))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        cmd=['podman','run','--pull=never','--rm','-d','--name',name,'--read-only',
             '--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
             '--cap-drop=ALL','--security-opt=no-new-privileges','--memory=512m','--cpus=2','--pids-limit=128',
             '--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
             '-p',f'127.0.0.1:{port}:8080','--mount',f'type=bind,src={temp},dst=/smoke,readonly',
             IMAGE,'--model','/smoke/'+primary.relative_to(temp).as_posix(),'--alias','tiny-fixture','--host','0.0.0.0','--port','8080',
             '--ctx-size','128','--parallel','1','--threads','2','--n-gpu-layers','0',
             '--api-key-file','/smoke/auth/api-key','--no-webui']
        try:
            started=run(cmd,timeout=60)
            checks['container_started']=started.returncode==0
            if started.returncode:
                report['reason']='container_start_failed'
                # No secrets are passed through argv or printed from container logs.
                return report
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if ai_health.check_api('llamacpp',port=port)==0: break
                time.sleep(0.5)
            else: report['reason']='readiness_timeout'; return report
            checks['native_authentication']=auth.test_endpoint('llamacpp',key,port=port)==0
            checks['inference']=ai_health.smoke_inference('llamacpp',MODEL,port=port,key_file=key)==0
            checks['invalid_auth_inference_rejected']=ai_health.smoke_inference('llamacpp',MODEL,port=port)==3
            checks['effective_context']=ai_health.runtime_context('llamacpp',port=port,desired=128,key_file=key)==0
            checks['context_mismatch_detected']=ai_health.runtime_context('llamacpp',port=port,desired=256,key_file=key)==5
            # Native process tests are separate from the systemd unit fixtures.
            from ai_health import auth_headers
            import services
            checks['occupied_port_detected']=not services.port_available(port)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),auth.NoRedirect())
            try:
                with opener.open(urllib.request.Request(f'http://127.0.0.1:{port}/completion',
                    data=b'{"prompt":',headers={'Content-Type':'application/json',**auth_headers(key)}),timeout=5) as response:
                    checks['malformed_request_rejected']=False
            except urllib.error.HTTPError as exc:
                checks['malformed_request_rejected']=exc.code in (400,422);exc.close()
            old_key=temp/'auth/old-api-key'
            auth.save(old_key,auth.read(key))
            auth.save(key,'sk-local-'+secrets.token_urlsafe(36),replace=True)
            run(['podman','rm','-f',name],timeout=20)
            restarted=run(cmd,timeout=60)
            checks['restart_after_rotation']=restarted.returncode==0
            ready=False
            if restarted.returncode==0:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if ai_health.check_api('llamacpp',port=port)==0:ready=True;break
                    time.sleep(0.5)
            checks['rotated_key_accepted']=ready and auth.test_endpoint('llamacpp',key,port=port)==0
            checks['previous_key_rejected']=ready and auth.test_endpoint('llamacpp',old_key,port=port)==5
            if with_gguf_shards:
                run(['podman','rm','-f',name],timeout=20)
                primary,shards=split_fixture(temp,model_root,store,checks)
                report['split_image_id']=run(['podman','image','inspect','--format','{{.Id}}',SPLIT_IMAGE]).stdout.strip()
                shard_cmd=cmd.copy();shard_cmd[shard_cmd.index('--model')+1]='/smoke/'+primary.relative_to(temp).as_posix()
                started=run(shard_cmd,timeout=60)
                if started.returncode:raise ValueError('Native sharded fixture server failed to start')
                deadline=time.monotonic()+60;ready=False
                while time.monotonic()<deadline:
                    if ai_health.check_api('llamacpp',port=port)==0:ready=True;break
                    time.sleep(0.5)
                checks['sharded_native_inference']=ready and ai_health.smoke_inference('llamacpp','tiny-fixture',port=port,key_file=key)==0
                checks['sharded_native_authentication']=ready and auth.test_endpoint('llamacpp',key,port=port)==0
            old_key.unlink()
            key.unlink()
            checks['stored_key_revoked']=not key.exists()
        finally:
            run(['podman','rm','-f',name],timeout=20)
            checks['container_removed']=run(['podman','container','exists',name]).returncode == 1
            checks['model_removed']=models.remove(model_root,MODEL,yes=True)==0
            key.unlink(missing_ok=True)
        checks['inference_unavailable_after_shutdown']=ai_health.check_api('llamacpp',port=port)==3
        _,snapshot=gguf.validate(bundle)
        checks['bundle_removed']=snapshots.remove_snapshot(gguf.bundle_root(store,bundle),snapshot['repository'],snapshot['revision'],yes=True)==0
        if with_gguf_shards:
            _,snapshot=gguf.validate(shards)
            checks['sharded_bundle_removed']=snapshots.remove_snapshot(gguf.bundle_root(store,shards),snapshot['repository'],snapshot['revision'],yes=True)==0
    report['status']='pass' if all(checks.values()) else 'fail'
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes',action='store_true'); parser.add_argument('--allow-pull',action='store_true')
    parser.add_argument('--allow-download',action='store_true'); parser.add_argument('--output',required=True)
    parser.add_argument('--backend',choices=['llamacpp','vllm','ollama'],default='llamacpp')
    parser.add_argument('--with-gguf-shards',action='store_true',help='Also generate/test genuine tiny GGUF shards using the optional official full CPU image')
    args=parser.parse_args(argv)
    if args.with_gguf_shards and args.backend!='llamacpp':parser.error('--with-gguf-shards supports llama.cpp only')
    # Reuse the validator's outside-source and symlink protections.
    from validate import output_path
    out=output_path(args.output)
    function={'vllm':vllm_sandbox,'ollama':ollama_sandbox,'llamacpp':sandbox}[args.backend]
    options={'with_gguf_shards':True} if args.with_gguf_shards else {}
    interrupted=False
    try:report=function(allow_pull=args.allow_pull,allow_download=args.allow_download,yes=args.yes,**options)
    except KeyboardInterrupt:
        interrupted=True;report={'status':'fail','backend':args.backend,'reason':'interrupted','teardown_verified':False}
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        report={'status':'fail','backend':args.backend,'reason':'sandbox_exception','error_type':type(exc).__name__,'teardown_verified':False}
    path=out/'ai-sandbox.json'; path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); path.chmod(0o600)
    print('AI sandbox:',report['status'],'Report:',path)
    return 130 if interrupted else 0 if report['status']=='pass' else 1


if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print('Sandbox failed:',type(exc).__name__,file=sys.stderr); sys.exit(2)
