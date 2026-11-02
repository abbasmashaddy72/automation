"""Explicit Ubuntu production provisioning; separate from local Lerd integration."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import time
from . import common as p

SUPPORTED={'22.04':'jammy','24.04':'noble','26.04':'resolute'}


def ubuntu(path=Path('/etc/os-release')):
    data={}
    for line in path.read_text().splitlines():
        if re.fullmatch(r'[A-Z_]+=(?:[^\n]*)',line):
            key,value=line.split('=',1);data[key]=value.strip('"\'')
    if data.get('ID')!='ubuntu' or data.get('VERSION_ID') not in SUPPORTED:raise ValueError('Production provisioning supports Ubuntu 22.04, 24.04 or 26.04 only')
    if os.uname().machine not in ('x86_64','aarch64'):raise ValueError('Production provisioning supports amd64/arm64 only')
    return data


def available(package,command=p.run):
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]{0,95}',package):raise ValueError('Invalid exact package name')
    output=command(['apt-cache','policy',package],label='Exact package availability')
    match=re.search(r'^\s*Candidate:\s*(\S+)',output,re.M)
    return bool(match and match[1]!='(none)')


def installed(package):
    result=subprocess.run(['dpkg-query','-W','-f=${Status}',package],capture_output=True,text=True,timeout=15)
    return result.returncode==0 and result.stdout.strip()=='install ok installed'


def apt(arguments,command=p.run):
    # APT's native lock timeout waits for locks, without replaying a partly
    # completed transaction or treating an arbitrary failure as transient.
    return command(['apt-get','-o','DPkg::Lock::Timeout=120',*arguments],env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'},label='APT transaction',timeout=1800)


def repository_manifest(path,codename):
    value=p.read_json(path,16384)
    required={'schema','name','uri','suite','component','key_url','key_sha256'}
    if not isinstance(value,dict) or set(value)!=required or value['schema']!=1:raise ValueError('Invalid repository manifest')
    if not re.fullmatch('[a-z][a-z0-9-]{0,40}',value['name']) or value['suite']!=codename or value['component']!='main':raise ValueError('Repository name/suite/component mismatch')
    for key in ('uri','key_url'):p.https_url(value[key])
    if not re.fullmatch('[a-f0-9]{64}',value['key_sha256']):raise ValueError('Repository signing key requires an independent SHA-256')
    return value


def packages(args,version):
    database={'none':[],'mariadb':['mariadb-server'],'postgresql':['postgresql']}[args.database]
    cache={'none':[],'redis':['redis-server'],'valkey':['valkey']}[args.cache]
    extensions=['cli','fpm','mbstring','xml','curl','zip','bcmath','intl','gd','sqlite3']
    if args.database=='mariadb':extensions.append('mysql')
    if args.database=='postgresql':extensions.append('pgsql')
    result=['ca-certificates','curl','git','unzip','sudo','nginx','composer','nodejs','npm','logrotate',*database,*cache]
    result+=['php'+version+'-'+name for name in extensions]
    if args.firewall:result.append('ufw')
    if args.harden_ssh:result.append('openssh-server')
    if args.tls_email:result.append('certbot')
    return result


def templates(args,version,root):
    from .templates import render
    identity=p.digest(args.domain.encode())[:12];prefix='automation-laravel-'+identity
    values={'PREFIX':prefix,'DOMAIN':args.domain,'SITE_ROOT':str(root),'PHP_VERSION':version,
        'DEPLOY_USER':args.deploy_user,'SOCKET':'/run/php/'+prefix+'.sock',
        'QUEUE_PERMISSION':(', /usr/bin/systemctl start '+prefix+'-queue.service') if args.queue!='none' else ''}
    files={Path('/etc/nginx/conf.d')/(prefix+'.conf'):(render('nginx.conf.tpl',values),0o644),
        Path('/etc/php')/version/'fpm/pool.d'/(prefix+'.conf'):(render('php-fpm.conf.tpl',values),0o644),
        Path('/etc/logrotate.d')/prefix:(render('logrotate.conf.tpl',values),0o644),
        Path('/etc/sudoers.d')/prefix:(render('sudoers.conf.tpl',values),0o440)}
    if args.scheduler:
        files[Path('/etc/systemd/system')/(prefix+'-schedule.service')]=(render('application.service.tpl',{**values,'COMMAND':'schedule:run --no-interaction','SERVICE_OPTIONS':'Type=oneshot'}),0o644)
        files[Path('/etc/systemd/system')/(prefix+'-schedule.timer')]=(render('scheduler.timer.tpl',values),0o644)
    if args.queue!='none':
        command='horizon' if args.queue=='horizon' else 'queue:work --sleep=3 --tries=3 --timeout=90'
        options='Restart=always\nRestartSec=5\nTimeoutStopSec=120\nKillSignal=SIGTERM\n[Install]\nWantedBy=multi-user.target'
        files[Path('/etc/systemd/system')/(prefix+'-queue.service')]=(render('application.service.tpl',{**values,'COMMAND':command,'SERVICE_OPTIONS':options}),0o644)
    return files,prefix


def tls_configuration(data,domain,root):
    secure=data.decode().replace('listen 80;','listen 443 ssl;\n    ssl_certificate /etc/letsencrypt/live/'+domain+'/fullchain.pem;\n    ssl_certificate_key /etc/letsencrypt/live/'+domain+'/privkey.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;',1)
    redirect=f'\nserver {{\n listen 80;\n server_name {domain};\n location ^~ /.well-known/acme-challenge/ {{ root {root}/acme; }}\n location / {{ return 301 https://$host$request_uri; }}\n}}\n'
    return (secure+redirect).encode()


def check_site_conflict(text,domain,owned_path):
    origin=None
    for line in text.splitlines():
        match=re.fullmatch(r'# configuration file (.+):',line.strip())
        if match:origin=Path(match[1]).resolve();continue
        match=re.search(r'\bserver_name\s+([^;]+);',line.split('#',1)[0])
        if match and domain in match[1].split() and origin!=owned_path.resolve():
            raise ValueError('Another Nginx configuration already serves this domain; no existing website was adopted')


def provision(args, *, command=p.run, os_path=Path('/etc/os-release'), system=Path('/')):
    info=ubuntu(os_path)
    if args.provision_url:
        p.https_url(args.provision_url)
        if not args.sha256 or not re.fullmatch('[a-f0-9]{64}',args.sha256):raise ValueError('External provisioning requires an independent --sha256')
        if args.dry_run:print('Plan: verify one pinned HTTPS shell script; no download/execution');return 0
        body=p.verified_script(args.provision_url,args.sha256)
        print('External script verified:',args.sha256,'bytes:',len(body))
        if args.check:return 0
        if not args.yes:print('Approval required; use --yes to save the verified script for private review');return 4
        state=p.checked(system/'var/lib/automation-toolkit/laravel/external')
        if os.geteuid()!=0:raise ValueError('Approved production provisioning requires root')
        state.mkdir(mode=0o700,parents=True,exist_ok=True);p.private(state,directory=True)
        with p.lock(state/'provision.lock'):
            status=state/(args.sha256+'.json');script=state/(args.sha256+'.sh')
            existing=p.read_json(status) if status.exists() else None
            if existing and existing.get('status')=='complete':print('This exact external script already completed; skipped');return 0
            if existing and existing.get('status') in ('running','failed') and not args.retry_external:raise ValueError('Inspect previous external failure before explicit --retry-external')
            if script.exists() and script.read_bytes()!=body:raise ValueError('Previously reviewed script changed; refusing overwrite')
            if not script.exists():p.atomic(script,body)
            if not args.allow_external_code:
                p.save(status,{'schema':1,'sha256':args.sha256,'status':'verified-awaiting-review'})
                print('Saved privately for review:',script,'; rerun with --allow-external-code only after inspection');return 4
            if not args.approve_service_changes:raise ValueError('External root execution requires --approve-service-changes as well as --allow-external-code')
            p.save(status,{'schema':1,'sha256':args.sha256,'status':'running'})
            try:command(['bash',str(script)],label='Approved external provisioning',timeout=3600)
            except BaseException:p.save(status,{'schema':1,'sha256':args.sha256,'status':'failed'});raise
            p.save(status,{'schema':1,'sha256':args.sha256,'status':'complete'})
        print('Pinned external provisioner completed; its application-specific idempotency requires independent review');return 0
    p.domain(args.domain);p.username(args.deploy_user)
    root=p.site_path(args.site_root or '/var/www/'+args.domain)
    version=args.php_version or {'22.04':'8.1','24.04':'8.3','26.04':'8.5'}[info['VERSION_ID']]
    if not re.fullmatch(r'8\.[0-9]{1,2}',version):raise ValueError('Invalid PHP version')
    if args.php_repository:repository_manifest(args.php_repository,SUPPORTED[info['VERSION_ID']])
    if args.database_name and (args.database=='none' or not re.fullmatch('[a-z][a-z0-9_]{0,62}',args.database_name)):raise ValueError('Invalid database selection/name')
    if args.tls_email and (not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',args.tls_email) or not args.approve_tls):raise ValueError('TLS requires a valid --tls-email and explicit --approve-tls acceptance')
    if args.harden_ssh and (not args.admin_user or not args.confirmed_admin_key_access):raise ValueError('SSH hardening requires an existing --admin-user and --confirmed-admin-key-access')
    plan=packages(args,version)
    print(json.dumps({'platform':info['VERSION_ID'],'php_version':version,'packages':plan,'site':str(root),
        'database':args.database,'cache':args.cache,'existing_data':'preserved','external_repository':bool(args.php_repository),
        'firewall':args.firewall,'ssh_hardening':args.harden_ssh,'tls':bool(args.tls_email),'create_database':args.database_name},indent=2))
    if args.check or args.dry_run:
        missing=[name for name in plan if not available(name,command)] if shutil.which('apt-cache') else plan
        print(json.dumps({'unverified_or_unavailable':missing,'mutation':False},indent=2));return 0
    if not args.yes:print('Provisioning requires --yes after reviewing --dry-run');return 4
    if os.geteuid()!=0:raise ValueError('Provisioning needs root; deployment must run separately as the deployment user')
    if not args.approve_service_changes:raise ValueError('Explicit --approve-service-changes is required before package/service/configuration changes')
    if args.php_repository and not args.approve_repository:raise ValueError('External repository changes require --approve-repository before provisioning')
    if args.ssh_port is not None and not 1<=args.ssh_port<=65535:raise ValueError('Invalid reviewed SSH port')
    state=p.checked(system/'var/lib/automation-toolkit/laravel'/args.domain)
    state.mkdir(mode=0o700,parents=True,exist_ok=True);p.private(state,directory=True)
    with p.lock(state/'provision.lock'):
        p.save(state/'status.json',{'schema':1,'status':'running','packages':plan})
        apt(['update'],command)
        if args.php_repository:
            if not args.approve_repository:raise ValueError('An external PHP repository requires --approve-repository')
            value=repository_manifest(args.php_repository,SUPPORTED[info['VERSION_ID']])
            key=p.fetch(value['key_url'],1048576)
            if p.digest(key)!=value['key_sha256']:raise ValueError('Repository signing-key checksum mismatch')
            key_path=Path('/etc/apt/keyrings')/('automation-'+value['name']+'.asc')
            if not key.startswith(b'-----BEGIN PGP PUBLIC KEY BLOCK-----'):raise ValueError('Expected an ASCII-armored public signing key')
            source=f'Types: deb\nURIs: {value["uri"]}\nSuites: {value["suite"]}\nComponents: main\nSigned-By: {key_path}\n'
            pin=f'Package: *\nPin: origin "{p.https_url(value["uri"])[1]}"\nPin-Priority: -1\n\nPackage: php*\nPin: origin "{p.https_url(value["uri"])[1]}"\nPin-Priority: 500\n'
            repo_files={system/key_path.relative_to('/'):(key,0o644),
                system/'etc/apt/sources.list.d'/('automation-'+value['name']+'.sources'):(source.encode(),0o644),
                system/'etc/apt/preferences.d'/('automation-'+value['name']):(pin.encode(),0o644)}
            p.ManagedFiles(state).apply(repo_files,lambda:apt(['update'],command))
        unavailable=[name for name in plan if not installed(name) and not available(name,command)]
        if unavailable:
            p.save(state/'status.json',{'schema':1,'status':'unavailable','packages':unavailable})
            print('Exact packages unavailable; no package substitutions:',', '.join(unavailable));return 5
        missing=[name for name in plan if not installed(name)]
        if missing:apt(['install','--yes','--no-install-recommends',*missing],command)
        if any(not installed(name) for name in plan):raise ValueError('Post-install package verification failed')
        if args.upgrade_packages:apt(['upgrade','--yes'],command)
        try:user=pwd.getpwnam(args.deploy_user)
        except KeyError:
            command(['useradd','--create-home','--shell','/bin/bash',args.deploy_user],label='Deployment user creation')
            user=pwd.getpwnam(args.deploy_user)
        if user.pw_uid==0:raise ValueError('Deployment account must not be root')
        import grp
        group=grp.getgrnam('www-data').gr_gid
        paths=[root,root/'releases',root/'shared',root/'shared/storage',root/'shared/storage/app',root/'shared/storage/app/public',
            root/'shared/storage/framework',root/'shared/storage/framework/cache',root/'shared/storage/framework/sessions',
            root/'shared/storage/framework/views',root/'shared/storage/logs',root/'acme']
        if not root.parent.exists():root.parent.mkdir(parents=True,mode=0o755)
        for path in paths:
            p.checked(path)
            if path.exists():
                if not path.is_dir() or path.stat().st_uid!=user.pw_uid:raise ValueError('Existing site path has unrelated ownership; nothing is adopted')
            else:path.mkdir(mode=0o750);os.chown(path,user.pw_uid,group)
        files,prefix=templates(args,version,root)
        files={system/path.relative_to('/'):(data,mode) for path,(data,mode) in files.items()}
        if args.harden_ssh:
            admin=pwd.getpwnam(p.username(args.admin_user));authorized=p.checked(Path(admin.pw_dir)/'.ssh/authorized_keys')
            if not authorized.is_file() or authorized.stat().st_uid!=admin.pw_uid or authorized.stat().st_mode&0o077:raise ValueError('Admin authorized_keys must already exist privately')
            command(['ssh-keygen','-l','-f',str(authorized)],label='Existing admin public-key validation')
            from .templates import render
            ssh=render('sshd.conf.tpl',{})
            files[system/'etc/ssh/sshd_config.d/00-automation-laravel.conf']=(ssh,0o600)
        def validate():
            command(['nginx','-t'],label='Nginx configuration validation')
            command(['php-fpm'+version,'-tt'],label='FPM configuration validation')
            command(['visudo','-c'],label='Scoped service-permission validation')
            if args.harden_ssh:
                command(['sshd','-t'],label='SSH configuration validation')
                effective=command(['sshd','-T'],label='Effective SSH policy verification')
                if not re.search(r'^passwordauthentication no$',effective,re.M) or not re.search(r'^kbdinteractiveauthentication no$',effective,re.M):
                    raise ValueError('Existing SSH precedence prevents the reviewed policy; configuration restored')
        nginx_path=system/'etc/nginx/conf.d'/(prefix+'.conf')
        check_site_conflict(command(['nginx','-T'],label='Existing website collision check'),args.domain,nginx_path)
        # Preserve a previously owned TLS site on every repair/repeat run,
        # including when certificate issuance was not requested again.
        if nginx_path.exists() and ('ssl_certificate /etc/letsencrypt/live/'+args.domain+'/fullchain.pem;') in nginx_path.read_text():
            certificate=system/'etc/letsencrypt/live'/args.domain/'fullchain.pem'
            key=certificate.with_name('privkey.pem')
            if not certificate.is_file() or not key.is_file() or key.stat().st_mode&0o077:raise ValueError('Existing TLS assets need administrator repair; refusing HTTP downgrade')
            files[nginx_path]=(tls_configuration(files[nginx_path][0],args.domain,root),0o644)
        p.ManagedFiles(state).apply(files,validate)
        if args.firewall:
            active=subprocess.run(['systemctl','is-active','--quiet','firewalld'],capture_output=True,timeout=15)
            if active.returncode==0:raise ValueError('firewalld is active; refusing to mix firewall managers')
            ports={args.ssh_port} if args.ssh_port else set()
            if shutil.which('sshd'):
                text=command(['sshd','-T'],label='Read existing SSH listener configuration')
                ports.update(int(match[1]) for match in re.finditer(r'^port ([0-9]+)$',text,re.M))
            if not ports or any(not 1<=port<=65535 for port in ports):raise ValueError('Cannot establish SSH ports safely; provide a reviewed --ssh-port or a working sshd configuration')
            for port in sorted(ports|{80,443}):command(['ufw','allow',str(port)+'/tcp'],label='Approved additive firewall rule')
            command(['ufw','--force','enable'],label='Approved firewall enable')
        command(['systemctl','daemon-reload'],label='System unit reload')
        services=['php'+version+'-fpm','nginx']
        services+= {'none':[],'mariadb':['mariadb'],'postgresql':['postgresql']}[args.database]
        services+= {'none':[],'redis':['redis-server'],'valkey':['valkey']}[args.cache]
        if args.scheduler:services.append(prefix+'-schedule.timer')
        for service in services:
            command(['systemctl','enable','--now',service],label='Approved service startup')
            command(['systemctl','is-active','--quiet',service],label='Service startup verification')
        command(['systemctl','reload','php'+version+'-fpm'],label='Approved FPM reload')
        command(['systemctl','reload','nginx'],label='Approved Nginx reload')
        if args.harden_ssh:command(['systemctl','reload','ssh'],label='Approved SSH reload; existing session remains open')
        if args.database_name:
            if args.database=='mariadb':
                command(['mariadb','--protocol=socket','--batch'],data=('CREATE DATABASE IF NOT EXISTS `'+args.database_name+'`;\n').encode(),label='Selected database creation')
            else:
                exists=command(['runuser','-u','postgres','--','psql','-Atqc',"SELECT 1 FROM pg_database WHERE datname='"+args.database_name+"'"],label='Database existence check').strip()
                if exists!='1':command(['runuser','-u','postgres','--','createdb',args.database_name],label='Selected database creation')
        if args.tls_email:
            command(['certbot','certonly','--webroot','--webroot-path',str(root/'acme'),'--domain',args.domain,'--email',args.tls_email,
                '--agree-tos','--non-interactive','--keep-until-expiring',
                '--deploy-hook','/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx'],label='Approved ACME certificate issuance',timeout=900)
            certificate=system/'etc/letsencrypt/live'/args.domain/'fullchain.pem'
            key=certificate.with_name('privkey.pem')
            if not certificate.is_file() or not key.is_file() or key.stat().st_mode&0o077:raise ValueError('ACME certificate/key were not observed with private key permissions')
            nginx_path=system/'etc/nginx/conf.d'/(prefix+'.conf')
            source=templates(args,version,root)[0][Path('/etc/nginx/conf.d')/(prefix+'.conf')][0]
            p.ManagedFiles(state).apply({nginx_path:(tls_configuration(source,args.domain,root),0o644)},lambda:command(['nginx','-t'],label='TLS configuration validation'))
            command(['systemctl','reload','nginx'],label='Approved TLS activation')
            command(['systemctl','enable','--now','certbot.timer'],label='ACME renewal timer')
        if args.queue!='none':
            command(['systemctl','enable',prefix+'-queue.service'],label='Queue autostart enable')
            if (root/'current/artisan').is_file():
                command(['systemctl','start',prefix+'-queue.service'],label='Queue start')
                command(['systemctl','is-active','--quiet',prefix+'-queue.service'],label='Queue verification')
        p.save(state/'status.json',{'schema':1,'status':'complete','packages':plan,'php_version':version,'domain':args.domain})
        print('Infrastructure verified. Supply an existing private production shared/.env before deploying. Database credentials and existing data were not rewritten.')
    return 0


def main(argv=None):
    from . import config
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain');parser.add_argument('--site-root');parser.add_argument('--deploy-user',default='deploy')
    parser.add_argument('--php-version');parser.add_argument('--php-repository',type=Path);parser.add_argument('--approve-repository',action='store_true')
    parser.add_argument('--database',choices=['none','mariadb','postgresql'],default='none');parser.add_argument('--database-name')
    parser.add_argument('--cache',choices=['none','redis','valkey'],default='none')
    parser.add_argument('--queue',choices=['none','queue','horizon'],default='none');parser.add_argument('--scheduler',action='store_true')
    parser.add_argument('--firewall',action='store_true');parser.add_argument('--harden-ssh',action='store_true')
    parser.add_argument('--admin-user');parser.add_argument('--confirmed-admin-key-access',action='store_true')
    parser.add_argument('--ssh-port',type=int,help='Reviewed SSH listener port when sshd discovery is unavailable')
    parser.add_argument('--tls-email');parser.add_argument('--approve-tls',action='store_true')
    parser.add_argument('--upgrade-packages',action='store_true');parser.add_argument('--approve-service-changes',action='store_true')
    parser.add_argument('--provision-url');parser.add_argument('--sha256');parser.add_argument('--allow-external-code',action='store_true');parser.add_argument('--retry-external',action='store_true')
    parser.add_argument('--yes',action='store_true');parser.add_argument('--dry-run',action='store_true');parser.add_argument('--check',action='store_true')
    parser.add_argument('--init-config',action='store_true',help='Merge missing toolkit defaults into the private bundled .env; no server changes')
    parser.add_argument('--no-auto-prerequisites',action='store_true')
    args=parser.parse_args(argv)
    if args.init_config:
        print(json.dumps(config.init(yes=args.yes,dry_run=args.dry_run or args.check),indent=2));return 0
    values=config.load()
    # argparse defaults become configuration defaults; explicit CLI always wins.
    mapping={'domain': 'LARAVEL_DOMAIN', 'site_root': 'LARAVEL_SITE_ROOT', 'deploy_user': 'LARAVEL_DEPLOY_USER', 'php_version': 'LARAVEL_PHP_VERSION', 'queue': 'LARAVEL_QUEUE', 'database': 'LARAVEL_DATABASE', 'database_name': 'LARAVEL_DATABASE_NAME', 'cache': 'LARAVEL_CACHE', 'scheduler': 'LARAVEL_SCHEDULER', 'php_repository': 'LARAVEL_PHP_REPOSITORY'}
    supplied=set((item.split('=',1)[0] for item in (__import__('sys').argv[1:] if argv is None else argv)))
    for option,key in mapping.items():
        if '--'+option.replace('_','-') not in supplied:
            value=values[key]
            setattr(args,option, int(value) if option=='retain' else value=='true' if option=='scheduler' else config.optional(value))
    for option in ('php_repository','migration_manifest'):
        if hasattr(args,option) and getattr(args,option):setattr(args,option,config.relative_file(getattr(args,option)))
    args.auto_prerequisites=values['LARAVEL_AUTO_PREREQUISITES']=='true' and not args.no_auto_prerequisites
    return provision(args)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (KeyboardInterrupt,EOFError):print('Provisioning interrupted; inspect receipts before retrying',file=__import__('sys').stderr);raise SystemExit(130)
    except ValueError as exc:print('Provisioning error:',str(exc),file=__import__('sys').stderr);raise SystemExit(2)
    except (OSError,subprocess.SubprocessError):print('Provisioning IO/process failure; inspect private receipts; no credential output retained.',file=__import__('sys').stderr);raise SystemExit(2)
