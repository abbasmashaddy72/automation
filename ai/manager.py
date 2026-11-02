#!/usr/bin/env python3
"""Unified local AI dispatcher. Existing services and model stores are preserved."""
from __future__ import annotations
import argparse
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
BACKENDS = {'llamacpp': 'CPU source build / native binary',
            'vllm': 'existing executable; installation requires hardware assessment',
            'ollama': 'official Linux installer / existing executable',
            'jan':'existing Desktop loopback API only; GUI installation/lifecycle is manual'}
SUPPORTED = {'status','check','update','repair','install','uninstall','models',
             'doctor','test-api','pull','serve','context','smoke'}


def batch_install(argv):
    parser=argparse.ArgumentParser(prog='setup.sh ai install',description='Explicitly select supported installers; never install every backend by default')
    parser.add_argument('--backends',required=True,help='Comma-separated backend names')
    parser.add_argument('--yes',action='store_true');parser.add_argument('--dry-run',action='store_true');parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    selected=args.backends.split(',')
    if not selected or len(selected)!=len(set(selected)) or any(name not in BACKENDS for name in selected):parser.error('Select distinct known backend names')
    if not args.check and any(name not in ('llamacpp','ollama') for name in selected):
        print('Native batch installation supports llama.cpp and Ollama only. vLLM needs a reviewed existing runtime; Jan GUI installation is manual. No backend was installed.');return 3
    for name in selected:
        code=main([name,'check' if args.check else 'install','--dry-run'])
        if code:return code
    if args.check or args.dry_run:return 0
    if not args.yes:print('Selected backend installation requires --yes after review');return 4
    for name in selected:
        code=main([name,'install','--yes'])
        if code:return code
    return 0


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0]=='install':return batch_install(argv[1:])
    p = argparse.ArgumentParser(description='Local AI compatibility and backend management',
        epilog='llama.cpp: CPU build, local GGUF, owned services and keys. vLLM: reviewed existing executable/local model or independent CPU sandbox; native installation is manual. Jan: existing Desktop API only. Ollama: official installer, native CLI and owned services; no native key enforcement is claimed.')
    p.add_argument('backend', nargs='?', choices=[*BACKENDS, 'list', 'hardware'], default='list')
    p.add_argument('action', nargs='?', default='status',help='status/check, install/repair/update, configure/start/stop/restart/service-status/logs/autostart/uninstall, serve/models/pull, model-search/model-files/model-download/model-remove/model-select, cache-list/snapshot-import/snapshot-remove, gguf-download/gguf-list/gguf-legacy-list/gguf-legacy-import/gguf-resolve/gguf-select/gguf-remove, legacy-plan/legacy-import, test-api/smoke/context, api-config/key-* (backend limits apply)')
    p.add_argument('--check', action='store_true')
    p.add_argument('--repair', action='store_true')
    p.add_argument('--uninstall', action='store_true')
    p.add_argument('--status', action='store_true')
    p.add_argument('--test-api', action='store_true')
    p.add_argument('--list-models', action='store_true')
    p.add_argument('--root',help='Explicit GGUF directory or separate private snapshot store; never an existing service root')
    p.add_argument('--cache-root',type=Path,help='Explicit external Hub cache, always read-only')
    p.add_argument('--source-dir',type=Path,help='Explicit regular model directory for verified snapshot copying')
    p.add_argument('--manifest',type=Path,help='Reviewed model/snapshot JSON with exact revision, independent SHA-256 and sizes')
    p.add_argument('--legacy-root',type=Path,help='Explicit old llama.cpp tree for read-only GGUF inventory/selection recovery')
    p.add_argument('--ignore-legacy-state',action='store_true',help='Explicitly omit old selected-model/context data; verify markers/assets and use a reviewed GGUF manifest instead')
    p.add_argument('--executable',help='Reviewed existing backend executable for an owned user service')
    p.add_argument('--enabled',choices=['yes','no'],default='yes',help='Explicit autostart choice')
    p.add_argument('--key-file', type=Path, help='Private native API-key file; secrets are never passed in argv')
    p.add_argument('--legacy-key-file',type=Path,help='Explicit old private raw/env key for key-import; original preserved')
    p.add_argument('--url', help='Explicit HTTPS GGUF artifact URL')
    p.add_argument('--sha256', help='Independently verified model SHA-256')
    p.add_argument('--size-bytes', type=int, help='Exact expected model artifact size')
    p.add_argument('--query',help='Literal publisher/model discovery query')
    p.add_argument('--limit',type=int,default=10)
    p.add_argument('--rank',choices=['downloads','likes','trending'],help='Hub activity ordering, never a quality ranking')
    p.add_argument('--scope',choices=['hub','warm'],default='hub',help='Warm means hosted inference availability, not local readiness')
    p.add_argument('--offset',type=int,default=0)
    p.add_argument('--revision',help='Pinned 40-character model commit for model-files')
    p.add_argument('--quant',help='Exact GGUF quantization filter for model-files')
    p.add_argument('--model', help='Single model ID for Ollama pull or local GGUF path for llama.cpp serve')
    p.add_argument('--model-alias',help='Explicit llama.cpp/vLLM served model alias')
    p.add_argument('--dtype',choices=['auto','bfloat16','float32','float16'],help='Reviewed vLLM dtype (hardware support is separate)')
    p.add_argument('--kv-cache-gib',type=int,help='Reviewed vLLM CPU KV cache size (1–64 GiB)')
    p.add_argument('--tool-parser',choices=['hermes','qwen3_coder'],help='Explicit native vLLM automatic tool parser')
    p.add_argument('--legacy-unit',type=Path,help='Exact old user unit for legacy-plan/legacy-import; never executed or deleted')
    p.add_argument('--ignore-legacy-preload',action='store_true',help='Explicitly omit an old executable allocator preload during legacy migration')
    p.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1','localhost','::1'])
    p.add_argument('--json', action='store_true', help='Machine-readable hardware inventory')
    p.add_argument('--refresh-model', action='store_true', help='Allow explicit refresh of an already installed Ollama model')
    p.add_argument('--models',help=argparse.SUPPRESS)
    p.add_argument('--context', type=int)
    p.add_argument('--cpu-threads', type=lambda value:'auto' if value=='auto' else int(value))
    p.add_argument('--cpu-quota')
    p.add_argument('--port', type=lambda value:'auto' if value=='auto' else int(value))
    p.add_argument('--download', choices=['yes','no'],help=argparse.SUPPRESS)
    p.add_argument('--start', choices=['yes','no'],help=argparse.SUPPRESS)
    p.add_argument('--api-test', choices=['yes','no'],help=argparse.SUPPRESS)
    p.add_argument('--yes', '-y', action='store_true')
    p.add_argument('--non-interactive', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    if args.executable and args.action not in ('configure','serve','model-select','legacy-plan','legacy-import','gguf-select'):
        p.error('--executable applies only to configure, model-select, serve or legacy settings migration')
    if args.model_alias and (args.backend not in ('llamacpp','vllm') or args.action not in ('configure','model-select','legacy-plan','legacy-import','serve','gguf-select')):
        p.error('--model-alias applies only to service configuration or legacy settings migration')
    if any(x is not None for x in (args.dtype,args.kv_cache_gib,args.tool_parser)) and (args.backend!='vllm' or args.action not in ('configure','model-select','legacy-plan','legacy-import','serve')):
        p.error('vLLM runtime settings apply only to explicit configuration, serving or legacy settings migration')
    if args.kv_cache_gib is not None and not 1<=args.kv_cache_gib<=64:p.error('CPU KV cache must be 1–64 GiB')
    if args.cpu_quota is not None and args.cpu_quota!='auto' and not re.fullmatch(r'(?:[1-9][0-9]{0,3}|10000)%',args.cpu_quota):p.error('CPU quota must be auto or 1%–10000%')
    if args.legacy_unit and args.action not in ('legacy-plan','legacy-import'):
        p.error('--legacy-unit applies only to legacy-plan/legacy-import')
    if args.ignore_legacy_preload and (args.backend!='vllm' or args.action not in ('legacy-plan','legacy-import')):
        p.error('--ignore-legacy-preload applies only to reviewed vLLM legacy migration')
    if args.ignore_legacy_state and (args.backend!='llamacpp' or not args.legacy_root or args.action not in ('gguf-legacy-list','gguf-legacy-import','gguf-select')):
        p.error('--ignore-legacy-state requires --legacy-root and explicit GGUF inventory/import/selection recovery')
    for value,lo,hi in ((args.context,128,1048576),(args.cpu_threads,1,4096),(args.port,1024,65535)):
        if value is not None and value!='auto' and not lo<=value<=hi: p.error('AI numeric settings out of bounds')
    if sum(bool(getattr(args, k)) for k in ('check','repair','uninstall','status','test_api','list_models')) > 1:
        p.error('Choose one AI action flag')
    for key, action in (('check','check'),('repair','repair'),('uninstall','uninstall'),('status','status'),('test_api','test-api'),('list_models','models')):
        if getattr(args,key): args.action = action
    if args.backend == 'hardware':
        from ai_health import print_hardware
        return print_hardware(as_json=args.json)
    if args.backend == 'list':
        print('CPU:', platform.processor() or platform.machine())
        try:
            print('Memory:', next(line.strip() for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))
        except (OSError, StopIteration): pass
        print('GPU tools:', {k: bool(shutil.which(k)) for k in ('nvidia-smi','rocminfo','vulkaninfo')})
        for name, script in BACKENDS.items():
            print(f'{name}: {script}')
        print('All distributions use the same portable dispatcher. Existing legacy units are not adopted.')
        print('No backend installed/changed. Example: bash setup.sh ai llamacpp check')
        return 0
    if args.action=='resources':
        import resources,json
        print(json.dumps(resources.apply(args),indent=2));return 0
    if args.action in ('legacy-plan','legacy-import'):
        import legacy
        return legacy.main(args)
    if args.action in ('gguf-download','gguf-list','gguf-legacy-list','gguf-legacy-import','gguf-resolve','gguf-select','gguf-remove'):
        import gguf
        return gguf.main(args)
    if args.action in ('cache-list','snapshot-import','snapshot-remove'):
        if args.backend not in ('vllm','llamacpp'):p.error('Snapshot/cache operations support llama.cpp and vLLM only')
        import snapshots,json,portable
        if args.action=='cache-list':
            if not args.cache_root:p.error('cache-list requires an explicit --cache-root')
            print(json.dumps(snapshots.inventory(args.cache_root),indent=2));return 0
        root=args.root or portable.ROOT/'snapshots'
        if args.action=='snapshot-remove':
            return snapshots.remove_snapshot(root,args.model,args.revision,yes=args.yes,dry_run=args.dry_run)
        if not args.manifest:p.error('snapshot-import requires an independently reviewed --manifest')
        value=snapshots.manifest(args.manifest)
        if args.model and args.model!=value['repository'] or args.revision and args.revision!=value['revision']:
            p.error('CLI repository/revision conflicts with the snapshot manifest')
        return snapshots.import_snapshot(root,value,cache=args.cache_root,source=args.source_dir,yes=args.yes,dry_run=args.dry_run)
    if args.action in ('configure','start','stop','restart','service-status','logs','autostart','uninstall'):
        import services
        return services.main(args)
    if args.action=='model-select':
        import services
        args.action='configure'
        return services.main(args)
    if args.action=='serve':
        import resources
        requested_quota=args.cpu_quota;requested_threads=args.cpu_threads
        resources.apply(args)
        # Foreground quota enforcement is not implemented; do not imply that
        # planning a quota constrains a non-managed process.
        if requested_quota is None:args.cpu_quota=None
        if args.backend=='ollama' and requested_threads is None:args.cpu_threads=None
    if args.backend=='llamacpp' and args.action in ('install','repair','update') and args.cpu_threads in (None,'auto'):
        import resources,copy
        planned=copy.copy(args);resources.apply(planned)
        args.cpu_threads=planned.cpu_threads
    if args.action=='model-search':
        if args.backend not in ('llamacpp','vllm'):p.error('Publisher model discovery supports llama.cpp/vLLM; Ollama uses its own catalogue')
        if not args.query:p.error('model-search requires --query')
        import models,json
        print(json.dumps(models.search(args.query,backend=args.backend,limit=args.limit,rank=args.rank,scope=args.scope,offset=args.offset),indent=2));return 0
    if args.action=='model-files':
        import models,json
        print(json.dumps(models.model_files(args.model,args.revision,backend=args.backend,quant=args.quant),indent=2));return 0
    if args.action=='api-config':
        import auth
        return auth.menu(args)
    if args.action in ('key-generate','key-use','key-import','key-status','key-rotate','key-revoke','key-copy','test-auth'):
        import auth
        return auth.main(args)
    if args.action in ('model-download', 'model-remove'):
        if args.backend != 'llamacpp': p.error('Receipt-based GGUF operations support llama.cpp only')
        import models
        import portable
        root = args.root or portable.ROOT/'models'
        if args.action == 'model-remove':
            return models.remove(root, args.model, yes=args.yes, dry_run=args.dry_run)
        return models.download(root, args.model, args.url or '', args.sha256, args.size_bytes,
                               yes=args.yes, dry_run=args.dry_run)
    if args.action not in SUPPORTED:
        p.error(f'Unsupported action {args.action} for {args.backend}')
    for value, lo, hi in ((args.context, 128, 1048576),(args.cpu_threads,1,4096),(args.port,1024,65535)):
        if value is not None and not lo <= value <= hi:
            p.error('AI numeric settings out of bounds')
    sys.path.insert(0, str(ROOT/'lib'))
    if args.action == 'smoke':
        from ai_health import smoke_inference
        if not args.model: p.error('smoke requires --model=MODEL')
        if args.dry_run:
            print('Dry run: would send a bounded inference request to the local endpoint; no request sent.')
            return 0
        return smoke_inference(args.backend,args.model,args.host,args.port,key_file=args.key_file)
    if any((args.models, args.download, args.start, args.api_test, args.cpu_quota)):
        p.error('Legacy bulk/service options are unsupported by the unified manager; use models, pull, serve or smoke explicitly')
    if args.root and args.action not in ('models', 'status', 'check', 'doctor'):
        p.error('--root is a read-only model inventory directory; managed installation paths are fixed')
    if args.action in ('install','repair','update') and args.yes and not args.dry_run:
        if args.backend=='vllm':
            print('vLLM installation requires an independently reviewed hardware-specific environment; no files changed.')
            return 3
        from automation import config_file,validate_settings
        validate_settings(config_file(ROOT/'.env'))
    if args.backend in ('llamacpp','ollama') and args.action in ('install','repair','update') and not (args.backend=='ollama' and args.action=='install' and shutil.which('ollama')):
        mode='check' if args.dry_run or not args.yes else 'install'
        flags=['--runtime-only','--with-ai-build' if args.backend=='llamacpp' else '--with-ollama','--without-ui']
        if args.yes:flags.append('--yes')
        if args.dry_run:flags.append('--dry-run')
        result=subprocess.run(['bash',str(ROOT/'scripts/prerequisites.sh'),mode,*flags],timeout=900).returncode
        if result:return result
    import portable
    result=portable.main(args)
    if result==0 and args.action in ('install','repair','update') and args.yes and not args.dry_run:
        from automation import config_file,validate_settings
        import configuration
        configuration.ensure(ROOT,config_file,validate_settings)
    return result

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print('AI error:', type(exc).__name__, file=sys.stderr)
        sys.exit(2)
    except (KeyboardInterrupt,EOFError):
        sys.exit(130)
