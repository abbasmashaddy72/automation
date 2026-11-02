"""Observed setup checks, shared safe setup actions and private manual progress."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import shutil
import stat
import developer
import journal

TASKS = (
 ('theme','Apply theme','Quick Settings',"Select a theme in your desktop settings"),
 ('touchpad','Set touchpad speed','Mouse & Touchpad','Review pointer speed'),
 ('notification-volume','Set notification volume','Sound','Review notification volume'),
 ('maximum-volume','Enable raise max volume','Sound','Review maximum volume preference'),
 ('night-light','Enable night light','Colors & Theme','Review Night Light schedule'),
 ('browser','Set default browser','Default Applications','Choose your default browser'),
 ('task-switcher','Set task switcher','Window Management','Choose your task switcher'),
 ('animation','Set animation speed','General Behaviour','Review animation speed'),
 ('recent-files','Disable recent files','Recent Files','Review history preference; clearing history is a separate manual choice'),
 ('spellcheck','Enable spell check','Spell Check','Review automatic spell checking'),
 ('session','Set session restore','Session','Review session restoration'),
 ('drivers','Setting hardware drivers','Hardware','Review official driver documentation for your hardware; no automatic driver changes'),
 ('file-manager','Configure Dolphin','File Manager','Review hidden files and view layout'),
 ('data','Copy data from HDD','Data Transfer','Review backups before copying personal data'),
 ('keepassxc','Enable KeepassXC Connect DB','KeepassXC','Connect your own database and browser integration manually'),
 ('ferdium','Login to Ferdium','Ferdium','Sign in manually'),
 ('virtual-machine','Install Windows in VBox','Virtualization','Review licensing and create a VM manually'),
 ('remmina','Add AIM RDP in Remmina','Remmina','Configure your own remote connection manually'),
 ('dbeaver','Add Local/Prod DB in DBeaver','DBeaver','Configure your own database connections manually'),
 ('email','Add company email in Thunderbird','Thunderbird','Configure your own account manually'),
 ('chrome','Login to Chrome','Chrome','Sign in manually'),
 ('firefox','Set Firefox/Dev session restore','Firefox','Review restore-tabs preferences'),
 ('vscode','VS Code login with GitHub','VS Code','Sign in and review settings sync manually'),
 ('ollama-client','Void connect the OLLAMA','AI client','Review your local Ollama endpoint in the client'),
 ('postman','Postman login with Google','Postman','Sign in manually'),
)
IDS={row[0] for row in TASKS}
STATES={'pending','done','skipped'}
# Compatibility is limited to preserving acknowledgements from the old list.
# These capabilities already have maintained implementations; never prompt twice.
REPLACED={
    'identity':{'command':['bash','setup.sh','developer','git'],
                'note':'Supply your explicit --name and --email; existing configuration is preserved.'},
    'software':{'command':['bash','setup.sh','packages','plan'],
                'note':'Select packages explicitly; installation uses packages install after review. Desktop update/tray preferences remain personal settings.'},
}
AUTOMATED=('configuration','projects')


def configuration_check(root):
    import automation
    try:
        wanted=automation.validate_settings(automation.config_file(root/'config/defaults.env'))
        path=root/'.env'
        existing=automation.validate_settings(automation.config_file(path))
        private=False
        if path.exists():
            st=path.stat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:
                raise ValueError('Unsafe configuration ownership/type')
            private=stat.S_IMODE(st.st_mode)==0o600
        missing=len(set(wanted)-set(existing))
        return {'id':'configuration','status':'ready' if path.exists() and private and not missing else 'pending',
                'missing_settings':missing,'private':private,
                'command':['bash','setup.sh','config','init','--yes']}
    except (OSError,ValueError,UnicodeError):
        return {'id':'configuration','status':'blocked','reason':'invalid_or_unsafe_configuration'}


def project_check(settings):
    import bootstrap
    target=settings.get('AUTOMATION_PROJECT_SITES_DIR') or str(Path.home()/'Documents/Project-Sites')
    try:
        plan=bootstrap.layout(target,dry_run=True)
        return {'id':'projects','status':'pending' if plan['missing'] else 'ready',
                'target':plan['target'],'missing_directories':len(plan['missing']),
                'command':['bash','setup.sh','projects','layout',plan['target'],'--yes']}
    except (OSError,ValueError,RuntimeError):
        return {'id':'projects','status':'blocked','reason':'invalid_or_conflicting_project_path'}


def setup_checks(root,settings,selected=AUTOMATED):
    return [configuration_check(root) if name=='configuration' else project_check(settings) for name in selected]


def automate(args,approve,root,settings):
    import automation
    import bootstrap
    import configuration
    raw=getattr(args,'select',None) or []
    selected=[part.strip() for item in raw for part in item.split(',')]
    if (not selected or len(set(selected))!=len(selected)
            or any(name not in AUTOMATED for name in selected) or getattr(args,'value',None)):
        raise ValueError('checklist automate --select configuration,projects [--dry-run|--yes]; select exact unique setup IDs')
    checks=setup_checks(root,settings,selected)
    print(json.dumps({'checks':checks,'dry_run':args.dry_run},indent=2))
    # Validate the entire selection before making any change or asking approval.
    if any(row['status']=='blocked' for row in checks):return 3
    pending=[row for row in checks if row['status']=='pending']
    if args.dry_run or not pending:return 0
    if not approve(args,'Apply selected missing setup steps: '+', '.join(row['id'] for row in pending)+'?'):return 4
    for row in pending:
        if row['id']=='configuration':configuration.ensure(root,automation.config_file,automation.validate_settings)
        else:bootstrap.layout(row['target'])
    verified=setup_checks(root,settings,selected)
    print(json.dumps({'checks':verified,'note':'Observed filesystem/configuration results; manual acknowledgements unchanged.'},indent=2))
    return 0 if all(row['status']=='ready' for row in verified) else 3


def state_path(state='', *, create=False):
    path=journal.state_dir(state,create=create)/'checklist.json'
    if path.is_symlink():raise ValueError('Symlink checklist state is forbidden')
    return path


def read(path):
    if not path.exists():return {}
    st=path.stat()
    if not path.is_file() or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_nlink!=1 or st.st_size>16384:
        raise ValueError('Checklist state must be a bounded private regular file')
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or set(data)!={'schema','tasks'} or data['schema']!=1 or not isinstance(data['tasks'],dict):
        raise ValueError('Invalid checklist schema')
    if set(data['tasks'])-(IDS|set(REPLACED)) or any(not isinstance(v,str) or v not in STATES for v in data['tasks'].values()):
        raise ValueError('Unknown checklist task or state')
    return data['tasks']


def main(args,approve, *, state='',root=None,settings=None):
    action=args.action or 'list'
    if action not in ('list','check','automate','review',*STATES):raise ValueError('checklist list|check|automate --select configuration,projects|review|done TASK|pending TASK|skipped TASK')
    if root is None:root=Path(__file__).resolve().parents[1]
    settings=settings or {}
    if action=='automate':return automate(args,approve,root,settings)
    if action=='check':
        import desktop
        print(json.dumps({'dependencies':{name:bool(shutil.which(name)) for name in ('git','ssh','bash','fish','zsh','lerd','podman')},
            'desktop':desktop.detect(),'git_config_file_present':developer.target('git').is_file(),
            'checks':setup_checks(root,settings),'maintained_workflows':REPLACED,
            'note':'Read-only observations only. Presence is not login, configuration completion, acceleration or service readiness; manual acknowledgements are unchanged.'},indent=2));return 0
    if action in STATES and args.value in REPLACED:
        raise ValueError('Task replaced by maintained workflow: '+' '.join(REPLACED[args.value]['command']))
    if action in STATES and args.value not in IDS:raise ValueError('Select an exact task ID from checklist list')
    path=state_path(state);tasks=read(path)
    before=path.read_bytes() if path.exists() else None
    if action=='list':
        print(json.dumps({'tasks':[{'id':id,'title':title,'category':category,'action':detail,'status':tasks.get(id,'pending')}
            for id,title,category,detail in TASKS],
            'maintained_workflows':REPLACED,
            'archived_progress':{key:value for key,value in tasks.items() if key in REPLACED},
            'note':'Manual acknowledgements only; done does not certify that a setting was applied.'},indent=2))
        return 0
    if args.dry_run:print('Dry run: would update manual checklist progress only.');return 0
    if action=='review' and not sys.stdin.isatty():raise ValueError('Checklist review requires an interactive terminal')
    if not approve(args,'Save private manual checklist progress (no settings are applied)?'):return 4
    if action=='review':
        for id,title,category,detail in TASKS:
            if tasks.get(id) in ('done','skipped'):continue
            print(title+' — '+category+': '+detail)
            answer=input('done / pending / skipped [Enter keeps '+tasks.get(id,'pending')+']: ').strip()
            if answer and answer not in STATES:raise ValueError('Invalid answer; no checklist changes saved')
            if answer:tasks[id]=answer
    else:tasks[args.value]=action
    state_path(state,create=True)
    if (path.read_bytes() if path.exists() else None)!=before:raise ValueError('Checklist changed during review; retry')
    developer.replace(path,(json.dumps({'schema':1,'tasks':tasks},sort_keys=True)+'\n').encode())
    print('Manual checklist progress saved.');return 0
