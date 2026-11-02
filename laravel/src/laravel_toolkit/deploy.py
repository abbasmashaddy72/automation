"""Release deployment independent of provisioning method and external control planes."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from . import common as p

RELEASE=re.compile(r'[0-9]{14}-[a-f0-9]{12}-[a-f0-9]{8}\Z')


from .vcs import repository,environment


def validate_health_url(url):
    if not isinstance(url,str) or any(ord(c)<33 for c in url) or '\\' in url:raise ValueError('Health URL must be a literal loopback URL without whitespace')
    parsed=urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('http','https') or parsed.hostname not in ('127.0.0.1','::1')
            or parsed.username or parsed.password or parsed.fragment or (parsed.port is not None and not 1<=parsed.port<=65535)):
        raise ValueError('Health URL must use literal loopback and a valid port without credentials or fragments')
    return parsed


def health(url,domain, *, attempts=5):
    validate_health_url(url)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    for attempt in range(attempts):
        try:
            with opener.open(urllib.request.Request(url,headers={'Host':domain}),timeout=5) as response:
                if response.status==200 and len(response.read(65537))<=65536:return
        except (OSError,urllib.error.HTTPError) as exc:
            if isinstance(exc,urllib.error.HTTPError):exc.close()
        if attempt+1<attempts:time.sleep(1)
    raise ValueError('Application health check failed')


def shared_environment(root):
    path=p.private(root/'shared/.env')
    if path.stat().st_size>1048576:raise ValueError('Application environment too large')
    values={}
    for line in path.read_text().splitlines():
        match=re.fullmatch(r'\s*(APP_ENV|APP_DEBUG|APP_KEY)\s*=\s*(.*?)\s*',line)
        if match:
            if match[1] in values:raise ValueError('Duplicate production environment setting')
            values[match[1]]=match[2].strip('"\'')
    if values.get('APP_ENV')!='production' or values.get('APP_DEBUG','').lower() not in ('false','0') or not values.get('APP_KEY'):
        raise ValueError('Shared .env must explicitly set APP_ENV=production, APP_DEBUG=false and an existing APP_KEY')


def current(root):
    path=root/'current'
    if not path.exists() and not path.is_symlink():return None
    if not path.is_symlink():raise ValueError('Current must be a release symlink, never a live checkout directory')
    target=path.resolve()
    if target.parent!=root/'releases' or not RELEASE.fullmatch(target.name):raise ValueError('Current points outside the managed release directory')
    receipt=p.read_json(target/'.automation-release.json',limit=64*1024*1024)
    if receipt.get('schema')!=1 or receipt.get('release')!=target.name or receipt.get('status')!='ready':raise ValueError('Current release is not a verified ready release')
    return target.name


def switch(root,release,expected):
    if current(root)!=expected:raise ValueError('Active release changed during deployment; refusing overwrite')
    if release is None:
        if (root/'current').is_symlink():(root/'current').unlink()
        return
    temporary=root/('.current-'+uuid.uuid4().hex)
    temporary.symlink_to('releases/'+release)
    try:os.replace(temporary,root/'current')
    finally:
        if temporary.is_symlink():temporary.unlink()
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def tree(root):
    result={}
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in [*dirs,*files]:
            path=Path(directory)/name;relative=path.relative_to(root).as_posix()
            if relative=='.automation-release.json':continue
            if path.is_symlink():
                target=path.resolve()
                allowed={'.env':root.parent.parent/'shared/.env','storage':root.parent.parent/'shared/storage',
                         'public/storage':root.parent.parent/'shared/storage/app/public'}
                if target!=allowed.get(relative) and root not in target.parents:raise ValueError('Release contains an escaping symlink')
                result[relative]=['link',os.readlink(path)]
            elif path.is_file():
                if path.stat().st_nlink!=1:raise ValueError('Release contains an external hardlink')
                result[relative]=['file',p.file_digest(path),path.stat().st_mode&0o777]
            elif path.is_dir():result[relative]=['dir',path.stat().st_mode&0o777]
            else:raise ValueError('Release contains an unsupported filesystem entry')
            if len(result)>200000:raise ValueError('Release has too many entries for safe retention receipts')
    return result


def reload_services(args,release):
    if args.fpm_service:
        if not args.approve_service_changes:raise ValueError('FPM reload requires --approve-service-changes')
        p.run(['sudo','-n','systemctl','reload',args.fpm_service],label='PHP-FPM reload')
    if args.queue!='none':
        command='horizon:terminate' if args.queue=='horizon' else 'queue:restart'
        php='php'+args.php_version if args.php_version else 'php'
        p.run([php,'artisan',command,'--no-interaction'],cwd=release,env=environment(),label='Graceful queue reload')
        if args.queue_service:
            if not args.approve_service_changes:raise ValueError('Queue service startup requires explicit approval')
            p.run(['sudo','-n','systemctl','start',args.queue_service],label='Approved queue monitor startup')


def prune(root,retain,protected):
    owned=[]
    for path in (root/'releases').iterdir():
        if path.is_symlink() or not path.is_dir() or not RELEASE.fullmatch(path.name):continue
        marker=path/'.automation-release.json'
        if not marker.is_file():continue
        try:
            p.private(marker)
            value=p.read_json(marker,limit=64*1024*1024)
            if value.get('schema')==1 and value.get('release')==path.name and value.get('status')=='ready':owned.append((value.get('created_ns',marker.stat().st_mtime_ns),path))
        except (ValueError,OSError,AttributeError):continue
    for _,path in sorted(owned,reverse=True)[retain:]:
        if path.name in protected:continue
        value=p.read_json(path/'.automation-release.json',limit=64*1024*1024)
        if value.get('tree')!=tree(path):
            print('Preserved subsequently edited release:',path.name);continue
        shutil.rmtree(path)  # fresh toolkit-owned artifact only; shared links are not followed


def deploy(args, *, command=p.run, health_check=health):
    root=p.site_path(args.site_root or ('/var/www/'+args.domain if args.domain else Path.cwd()))
    if args.domain:p.domain(args.domain)
    if args.fpm_service and not re.fullmatch(r'php[7-9]\.[0-9]{1,2}-fpm(?:\.service)?',args.fpm_service):raise ValueError('Select an exact PHP-FPM unit')
    if args.php_version and not re.fullmatch(r'8\.[0-9]{1,2}',args.php_version):raise ValueError('Invalid PHP CLI version')
    if args.queue_service and (args.queue=='none' or not re.fullmatch(r'automation-laravel-[a-f0-9]{12}-queue\.service',args.queue_service)):
        raise ValueError('Select an exact toolkit queue unit with an explicit queue mode')
    if args.migrations!='none' and (not args.approve_migrations or not args.backward_compatible or not args.migration_manifest):
        raise ValueError('Migrations require a reviewed --migration-manifest and explicit compatibility/approval flags')
    if not 2<=args.retain<=100:raise ValueError('Retention must be 2–100 releases')
    if not args.rollback and not args.recover:
        repository(args.repository,args.allow_local_repository)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}',args.branch) or '..' in args.branch or args.branch.endswith('/'):
            raise ValueError('Invalid Git branch')
    if args.health_url:validate_health_url(args.health_url)
    if args.check or args.dry_run:
        print(json.dumps({'operation':'rollback' if args.rollback else 'recover' if args.recover else 'deploy',
            'site':str(root),'migration_policy':args.migrations,'retention':args.retain,'mutation':False},indent=2));return 0
    if not args.yes:print('Deployment requires --yes after reviewing --dry-run');return 4
    if (args.fpm_service or args.queue_service) and not args.approve_service_changes:raise ValueError('Selected service operations require --approve-service-changes before deployment')
    if os.geteuid()==0:raise ValueError('Run deployment as the dedicated deployment user, not root')
    if args.deploy_user and pwd.getpwnam(p.username(args.deploy_user)).pw_uid!=os.geteuid():raise ValueError('Deployment user does not match the executing user')
    if not root.is_dir() or root.stat().st_uid!=os.geteuid():raise ValueError('Site root must already exist and be owned by the deployment user')
    for folder in ('releases','shared','shared/storage'):
        path=p.checked(root/folder)
        if not path.is_dir() or path.stat().st_uid!=os.geteuid():raise ValueError('Expected owned site layout is missing')
    from .prerequisites import ensure
    ensure(args)
    shared_environment(root)
    state_path=root/'.automation-deploy.json';pending=root/'.automation-deploy.pending.json'
    with p.lock(root/'.automation-deploy.lock'):
        state=p.read_json(p.private(state_path)) if state_path.exists() else None
        if state is not None and (not isinstance(state,dict) or set(state)!={'schema','domain','health_url','active','previous'} or state['schema']!=1 or any(value is not None and (not isinstance(value,str) or not RELEASE.fullmatch(value)) for value in (state['active'],state['previous']))):raise ValueError('Invalid deployment state receipt')
        domain=args.domain or (state or {}).get('domain')
        p.domain(domain)
        url=args.health_url or (state or {}).get('health_url')
        if not url:raise ValueError('Provide --health-url on first deployment; do not assume a route')
        validate_health_url(url)
        before=current(root)
        if args.recover:
            if not pending.exists():raise ValueError('No interrupted deployment receipt exists')
            intent=p.read_json(pending)
            if set(intent)!={'schema','before','after'} or intent['schema']!=1:raise ValueError('Invalid interrupted activation receipt')
            if before==intent['before'] or (state and state.get('active')==before==intent['after']):
                if before:health_check(url,domain)
                pending.unlink();print('Interrupted receipt reconciled with the observed active release');return 0
            if before!=intent['after']:raise ValueError('Active release differs from interrupted receipt')
            destination=intent['before']
            if destination is not None and (not RELEASE.fullmatch(destination) or not (root/'releases'/destination/'.automation-release.json').is_file()):raise ValueError('Previous release is unavailable')
            switch(root,destination,before)
            if destination:
                reload_services(args,root/'releases'/destination);health_check(url,domain)
            if state:p.save(state_path,{**state,'active':destination,'previous':None})
            pending.unlink();print('Interrupted activation recovered; database schema was not reversed');return 0
        if pending.exists():raise ValueError('An interrupted deployment needs explicit --recover before proceeding')
        if args.rollback:
            if not state or state.get('active')!=before or not state.get('previous'):raise ValueError('No previous valid release recorded for this active application')
            target=state['previous']
            if not RELEASE.fullmatch(target):raise ValueError('Invalid previous release identity')
            receipt=p.read_json(root/'releases'/target/'.automation-release.json',limit=64*1024*1024)
            if receipt.get('status')!='ready' or receipt.get('release')!=target:raise ValueError('Previous release is not ready')
            if receipt.get('tree')!=tree(root/'releases'/target):raise ValueError('Previous release has later edits; inspect before rollback')
        else:
            env=environment();repo=repository(args.repository,args.allow_local_repository)
            command(['git','check-ref-format','--branch',args.branch],env=env,label='Git branch validation')
            remote=command(['git','ls-remote','--exit-code','--heads',repo,'refs/heads/'+args.branch],env=env,label='Repository authentication')
            rows=remote.splitlines()
            if len(rows)!=1 or not re.fullmatch('[a-f0-9]{40}',rows[0].split()[0]):raise ValueError('Branch did not resolve to one exact commit')
            commit=rows[0].split()[0]
            target=time.strftime('%Y%m%d%H%M%S',time.gmtime())+'-'+commit[:12]+'-'+uuid.uuid4().hex[:8]
            release=root/'releases'/target
            command(['git','clone','--no-hardlinks','--no-checkout','--single-branch','--branch',args.branch,'--',repo,str(release)],env=env,label='Git checkout')
            command(['git','checkout','--detach',commit],cwd=release,env=env,label='Pinned checkout')
            for name in ('artisan','bootstrap/app.php','composer.json','composer.lock'):
                if not (release/name).is_file():raise ValueError('Candidate is missing a required Laravel file or Composer lock')
            for name in ('.env','storage'):
                path=release/name
                if path.is_symlink():raise ValueError('Repository supplied a conflicting shared-data link')
                if path.is_dir():shutil.rmtree(path)
                elif path.exists():path.unlink()
                path.symlink_to(root/'shared'/name)
            public=release/'public'
            if not public.is_dir() or public.is_symlink():raise ValueError('Laravel public directory missing')
            storage=public/'storage'
            if storage.exists() or storage.is_symlink():
                if not storage.is_symlink() or storage.resolve()!=root/'shared/storage/app/public':raise ValueError('Repository supplied conflicting public/storage; review it instead of deleting it')
            else:storage.symlink_to(root/'shared/storage/app/public')
            cache_directory=p.checked(release/'bootstrap/cache')
            cache_directory.mkdir(mode=0o700,exist_ok=True)
            cache_directory.chmod(0o700)
            php='php'+args.php_version if args.php_version else 'php'
            composer=[php,shutil.which('composer') or 'composer'] if args.php_version else ['composer']
            command([*composer,'install','--no-dev','--prefer-dist','--no-interaction','--optimize-autoloader'],cwd=release,env=env,label='Production Composer install')
            command([*composer,'check-platform-reqs','--no-dev'],cwd=release,env=env,label='Composer platform requirements')
            if args.frontend!='none' and (release/'package.json').exists():
                package=p.read_json(release/'package.json');scripts=package.get('scripts',{})
                script=args.build_script or ('build' if 'build' in scripts else None)
                if not script or not re.fullmatch(r'[A-Za-z0-9:_-]{1,64}',script) or script not in scripts:raise ValueError('Select an actual package.json build script with --build-script')
                locks=[name for name in ('package-lock.json','npm-shrinkwrap.json','pnpm-lock.yaml','yarn.lock') if (release/name).is_file()]
                if len(locks)!=1:raise ValueError('Require exactly one reviewed project lockfile')
                if locks[0] in ('package-lock.json','npm-shrinkwrap.json'):
                    install=['npm','ci','--no-audit','--no-fund'];build=['npm','run',script]
                else:
                    manager=package.get('packageManager','')
                    match=re.fullmatch(r'(pnpm|yarn)@([0-9]+)\.[0-9]+\.[0-9]+(?:\+sha(?:224|256|384|512)\.[a-f0-9]+)?',manager)
                    expected='pnpm' if locks[0]=='pnpm-lock.yaml' else 'yarn'
                    if not match or match[1]!=expected:raise ValueError('Pin the matching packageManager version before using Corepack')
                    install=['corepack',expected,'install','--frozen-lockfile' if expected=='pnpm' or int(match[2])==1 else '--immutable']
                    build=['corepack',expected,'run',script]
                command(install,cwd=release,env=env,label='Locked Node installation')
                command(build,cwd=release,env=env,label='Frontend build')
            available=json.loads(command([php,'artisan','list','--format=json'],cwd=release,env=env,label='Laravel command discovery'))
            commands={entry['name'] for entry in available.get('commands',[]) if isinstance(entry,dict) and isinstance(entry.get('name'),str)}
            for name in ('config:cache','route:cache','event:cache','view:cache'):
                if name in commands:command([php,'artisan',name,'--no-interaction'],cwd=release,env=env,label='Laravel '+name)
            command([php,'-r','require "vendor/autoload.php"; $app=require "bootstrap/app.php"; $app->make("Illuminate\\\\Contracts\\\\Console\\\\Kernel")->bootstrap(); exit(config("app.env")==="production" && !config("app.debug") && config("app.key") ? 0 : 1);'],cwd=release,env=env,label='Production Laravel configuration')
            # Config cache contains application secrets; only the deployment/FPM user may read it.
            for cache_file in (release/'bootstrap/cache').glob('*.php'):
                p.checked(cache_file)
                if not cache_file.is_file() or cache_file.stat().st_nlink!=1:raise ValueError('Unsafe generated Laravel cache file')
                cache_file.chmod(0o600)
            if args.migrations!='none':
                review=p.read_json(args.migration_manifest)
                migration_files={str(path.relative_to(release/'database/migrations')):p.digest(path.read_bytes())
                    for path in (release/'database/migrations').rglob('*.php') if path.is_file() and not path.is_symlink()}
                if (not isinstance(review,dict) or set(review)!={'schema','backward_compatible','files'} or review['schema']!=1
                        or review['backward_compatible'] is not True or review['files']!=migration_files):
                    raise ValueError('Migration files differ from the independently reviewed compatibility manifest')
                if 'migrate' not in commands:raise ValueError('Application has no migrate command')
                # Classification of arbitrary PHP migrations cannot be proven by
                # regex. The operator attests backward compatibility; destructive
                # migrations require a separate maintenance workflow.
                command([php,'artisan','migrate','--force','--isolated=75','--no-interaction'],cwd=release,env=env,label='Reviewed isolated migrations')
            marker={'schema':1,'release':target,'commit':commit,'created_ns':time.time_ns(),'status':'ready','tree':tree(release)}
            if len(json.dumps(marker,indent=2).encode())>64*1024*1024:raise ValueError('Release ownership receipt would exceed the safe size limit')
            p.save(release/'.automation-release.json',marker)
        if args.fpm_service and not args.approve_service_changes:raise ValueError('Service reload approval is required before activation')
        p.save(pending,{'schema':1,'before':before,'after':target})
        switch(root,target,before)
        try:
            reload_services(args,root/'releases'/target)
            health_check(url,domain)
        except BaseException:
            switch(root,before,target)
            if before:
                reload_services(args,root/'releases'/before)
                health_check(url,domain)
            pending.unlink()
            raise
        p.save(state_path,{'schema':1,'domain':domain,'health_url':url,'active':target,'previous':before})
        pending.unlink()
        if not args.rollback:prune(root,args.retain,{target,before})
        print('Rollback verified' if args.rollback else 'Release activated and healthy',target,'; shared data preserved; schema rollback is never automatic')
        return 0


def main(argv=None):
    from . import config
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository');parser.add_argument('--branch',default='main')
    parser.add_argument('--domain');parser.add_argument('--site-root');parser.add_argument('--deploy-user')
    parser.add_argument('--health-url');parser.add_argument('--build-script')
    parser.add_argument('--php-version');parser.add_argument('--frontend',choices=['auto','none'],default='auto')
    parser.add_argument('--migrations',choices=['none','compatible'],default='none')
    parser.add_argument('--approve-migrations',action='store_true');parser.add_argument('--backward-compatible',action='store_true')
    parser.add_argument('--migration-manifest',type=Path)
    parser.add_argument('--fpm-service');parser.add_argument('--approve-service-changes',action='store_true')
    parser.add_argument('--queue',choices=['none','queue','horizon'],default='none')
    parser.add_argument('--queue-service')
    parser.add_argument('--retain',type=int,default=5);parser.add_argument('--allow-local-repository',action='store_true')
    group=parser.add_mutually_exclusive_group();group.add_argument('--rollback',action='store_true');group.add_argument('--recover',action='store_true')
    parser.add_argument('--yes',action='store_true');parser.add_argument('--dry-run',action='store_true');parser.add_argument('--check',action='store_true')
    parser.add_argument('--init-config',action='store_true',help='Merge missing toolkit defaults into the private bundled .env; no server changes')
    parser.add_argument('--no-auto-prerequisites',action='store_true')
    args=parser.parse_args(argv)
    if args.init_config:
        print(json.dumps(config.init(yes=args.yes,dry_run=args.dry_run or args.check),indent=2));return 0
    values=config.load()
    # argparse defaults become configuration defaults; explicit CLI always wins.
    mapping={'domain': 'LARAVEL_DOMAIN', 'site_root': 'LARAVEL_SITE_ROOT', 'deploy_user': 'LARAVEL_DEPLOY_USER', 'php_version': 'LARAVEL_PHP_VERSION', 'queue': 'LARAVEL_QUEUE', 'repository': 'LARAVEL_REPOSITORY', 'branch': 'LARAVEL_BRANCH', 'health_url': 'LARAVEL_HEALTH_URL', 'build_script': 'LARAVEL_BUILD_SCRIPT', 'frontend': 'LARAVEL_FRONTEND', 'retain': 'LARAVEL_RETAIN', 'fpm_service': 'LARAVEL_FPM_SERVICE', 'queue_service': 'LARAVEL_QUEUE_SERVICE', 'migration_manifest': 'LARAVEL_MIGRATION_MANIFEST'}
    supplied=set((item.split('=',1)[0] for item in (__import__('sys').argv[1:] if argv is None else argv)))
    for option,key in mapping.items():
        if '--'+option.replace('_','-') not in supplied:
            value=values[key]
            setattr(args,option, int(value) if option=='retain' else value=='true' if option=='scheduler' else config.optional(value))
    for option in ('php_repository','migration_manifest'):
        if hasattr(args,option) and getattr(args,option):setattr(args,option,config.relative_file(getattr(args,option)))
    args.auto_prerequisites=values['LARAVEL_AUTO_PREREQUISITES']=='true' and not args.no_auto_prerequisites
    previous_umask=os.umask(0o022)
    try:return deploy(args)
    finally:os.umask(previous_umask)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (KeyboardInterrupt,EOFError):print('Interrupted; inspect the preserved release/activation receipt before retrying',file=__import__('sys').stderr);raise SystemExit(130)
    except ValueError as exc:print('Deployment error:',str(exc),file=__import__('sys').stderr);raise SystemExit(2)
    except (OSError,subprocess.SubprocessError):print('Deployment IO/process failure; inspect the preserved candidate and activation receipt privately.',file=__import__('sys').stderr);raise SystemExit(2)
