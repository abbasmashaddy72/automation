"""Exact enabled-repository prerequisite installation; no remote bootstraps."""
import os
import shutil
from . import common
from . import provision


def ensure(args):
    tools={}
    full_deploy=not getattr(args,'rollback',False) and not getattr(args,'recover',False)
    if full_deploy:tools.update(git='git',composer='composer')
    if full_deploy or getattr(args,'queue','none')!='none':tools['php'+(args.php_version or '')]='php'+(args.php_version+'-cli' if args.php_version else '-cli')
    if full_deploy and args.frontend!='none':tools.update(node='nodejs',npm='npm')
    if getattr(args,'fpm_service',None) or getattr(args,'queue_service',None):tools['sudo']='sudo'
    missing=sorted({package for tool,package in tools.items() if not shutil.which(tool)})
    if not missing:return
    if args.check or args.dry_run:raise ValueError('Missing prerequisites: '+', '.join(missing))
    if not args.yes or not getattr(args,'auto_prerequisites',True):raise ValueError('Missing prerequisites; authorize automatic installation or ask an administrator: '+', '.join(missing))
    provision.ubuntu()
    prefix=[] if os.geteuid()==0 else ['sudo','-n']
    if prefix and not shutil.which('sudo'):raise ValueError('An administrator must install missing prerequisites: '+', '.join(missing))
    def run(argv,**kwargs):return common.run([*prefix,*argv],**kwargs)
    provision.apt(['update'],run)
    if any(not provision.available(package,run) for package in missing):raise ValueError('An exact prerequisite is unavailable; no repositories were added')
    provision.apt(['install','--yes','--no-install-recommends',*missing],run)
    if any(not shutil.which(tool) for tool in tools):raise ValueError('Prerequisite verification failed')
