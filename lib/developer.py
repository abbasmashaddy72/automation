"""User-only Git identity and shell integration, with private conflict-safe backups."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import journal

BEGIN='# BEGIN AUTOMATION TOOLKIT'
END='# END AUTOMATION TOOLKIT'
POSIX_BLOCK='''for _automation_toolkit_dir in "$HOME/.local/bin" "$HOME/bin" "$HOME/.config/composer/vendor/bin" "$HOME/.composer/vendor/bin"; do
    case ":$PATH:" in
        *":$_automation_toolkit_dir:"*) ;;
        *) PATH="$_automation_toolkit_dir:$PATH" ;;
    esac
done
export PATH
unset _automation_toolkit_dir
if ! alias artisan >/dev/null 2>&1 && ! command -v artisan >/dev/null 2>&1; then alias artisan="php artisan"; fi
if ! alias vbin >/dev/null 2>&1 && ! command -v vbin >/dev/null 2>&1; then
    vbin() {
        if [ "$#" -eq 0 ]; then printf '%s\\n' 'Usage: vbin TOOL [ARGS...]' >&2; return 2; fi
        case "$1" in ''|*/*) printf '%s\\n' 'Select one vendor/bin tool name' >&2; return 2 ;; esac
        local _automation_toolkit_bin="./vendor/bin/$1"
        shift
        if [ ! -x "$_automation_toolkit_bin" ]; then printf '%s\\n' 'Vendor tool missing or not executable' >&2; return 127; fi
        "$_automation_toolkit_bin" "$@"
    }
fi
for _automation_toolkit_tool in pint sail fixer pest phpunit; do
    if ! alias "$_automation_toolkit_tool" >/dev/null 2>&1 && ! command -v "$_automation_toolkit_tool" >/dev/null 2>&1; then
        case "$_automation_toolkit_tool" in
            fixer) alias fixer='vbin php-cs-fixer' ;;
            *) alias "$_automation_toolkit_tool=vbin $_automation_toolkit_tool" ;;
        esac
    fi
done
unset _automation_toolkit_tool
'''
SHELLS={
 'bash':POSIX_BLOCK,
 'zsh':POSIX_BLOCK,
 'fish':'''fish_add_path --path "$HOME/.local/bin" "$HOME/bin" "$HOME/.config/composer/vendor/bin" "$HOME/.composer/vendor/bin"
if not type -q artisan; alias artisan "php artisan"; end
if not type -q vbin
    function vbin
        if test (count $argv) -eq 0; echo 'Usage: vbin TOOL [ARGS...]' >&2; return 2; end
        if string match -q '*/*' -- $argv[1]; return 2; end
        set -l bin ./vendor/bin/$argv[1]
        set -e argv[1]
        if not test -x "$bin"; echo 'Vendor tool missing or not executable' >&2; return 127; end
        "$bin" $argv
    end
end
begin
set -l _automation_toolkit_tool
for _automation_toolkit_tool in pint sail pest phpunit
    if not type -q $_automation_toolkit_tool; alias $_automation_toolkit_tool "vbin $_automation_toolkit_tool"; end
end
end
if not type -q fixer; alias fixer 'vbin php-cs-fixer'; end
''',
}


def target(kind):
    home=Path.home()
    paths={'git':home/'.gitconfig','bash':home/'.bashrc','zsh':home/'.zshrc',
        'fish':Path(os.environ.get('XDG_CONFIG_HOME',str(home/'.config')))/'fish/config.fish',
        'ssh':home/'.ssh/automation-toolkit.conf',
        'ssh-agent':Path(os.environ.get('XDG_CONFIG_HOME',str(home/'.config')))/'systemd/user/automation-ssh-agent.service'}
    if kind not in paths:raise ValueError('Unknown developer configuration kind')
    path=paths[kind]
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlink developer configuration paths are forbidden')
    if path.exists() and (not path.is_file() or path.stat().st_uid!=os.getuid() or path.stat().st_nlink!=1 or path.stat().st_size>1048576):
        raise ValueError('Developer configuration must be an owned, bounded, regular file')
    return path


def shell_content(original,shell,banner='none', *, use_agent=False,greeting='keep',migrate=False):
    if shell not in SHELLS:raise ValueError('Choose bash, zsh or fish')
    text=original.decode('utf-8')
    if migrate:
        import shell_migration
        text=shell_migration.migrate(text,shell)
    if text.count(BEGIN)!=text.count(END) or text.count(BEGIN)>1:
        raise ValueError('Ambiguous existing managed shell blocks; review manually')
    if banner not in ('none','fastfetch','neofetch'):raise ValueError('Unknown shell banner')
    content=SHELLS[shell]
    if greeting not in ('keep','off') or greeting=='off' and shell!='fish':raise ValueError('Fish greeting control applies only to fish')
    if greeting=='off':content+='set -g fish_greeting ""\n'
    if use_agent:
        if shell=='fish':
            content+='''if not set -q SSH_AUTH_SOCK; or test -z "$SSH_AUTH_SOCK"
    if set -q XDG_RUNTIME_DIR; and not test -L "$XDG_RUNTIME_DIR"; and not test -L "$XDG_RUNTIME_DIR/automation-ssh-agent"; and not test -L "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"; and test -S "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"
        set -gx SSH_AUTH_SOCK "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"
    end
end
'''
        else:
            content+='''if [ -z "${SSH_AUTH_SOCK:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ ! -L "$XDG_RUNTIME_DIR" ] && [ ! -L "$XDG_RUNTIME_DIR/automation-ssh-agent" ] && [ ! -L "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock" ] && [ -S "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock" ]; then
    export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"
fi
'''
    if banner!='none':
        content+=(f'if status is-interactive; and type -q {banner}; {banner}; end\n' if shell=='fish' else
                  f'if [[ $- == *i* ]] && command -v {banner} >/dev/null 2>&1; then {banner}; fi\n')
    block=BEGIN+'\n'+content+END
    if BEGIN in text:
        if text.index(END)<text.index(BEGIN):raise ValueError('Invalid shell marker order')
        return re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END),lambda _:block,text,flags=re.S).encode()
    return (text+('' if not text or text.endswith('\n') else '\n')+block+'\n').encode()


def validate_identity(name,email):
    if not name or not 1<=len(name)<=120 or any(ord(c)<32 for c in name):raise ValueError('Provide a literal Git display name')
    if not email or len(email)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+',email):raise ValueError('Provide a valid Git email address')


def identity(original,name,email):
    validate_identity(name,email)
    if not shutil.which('git'):raise ValueError('Git is required; install it with packages install --select git')
    with tempfile.TemporaryDirectory(prefix='automation-git-config-') as td:
        path=Path(td)/'gitconfig';path.write_bytes(original);path.chmod(0o600)
        for key,value in [('user.name',name),('user.email',email)]:
            cp=subprocess.run(['git','config','--file',str(path),'--replace-all',key,value],capture_output=True,timeout=10)
            if cp.returncode:raise ValueError('Existing Git configuration is invalid; no file changed')
        return path.read_bytes()


def transport(original,choice):
    if choice not in ('ssh','https'):raise ValueError('Choose --transport ssh or https for the exact GitHub prefix')
    if not shutil.which('git'):raise ValueError('Git is required')
    with tempfile.TemporaryDirectory(prefix='automation-git-transport-') as directory:
        path=Path(directory)/'gitconfig';path.write_bytes(original);path.chmod(0o600)
        command=['git','config','--no-includes','--file',str(path)]
        query=subprocess.run([*command,'--get-regexp',r'^url\..*\.insteadof$',r'^https://github\.com/$'],capture_output=True,text=True,timeout=10)
        if query.returncode not in (0,1):raise ValueError('Invalid Git configuration; nothing changed')
        key='url.git@github.com:.insteadof'
        if choice=='ssh' and any(line.split(' ',1)[0]!=key for line in query.stdout.splitlines()):
            raise ValueError('A different GitHub transport rewrite already exists; review it manually before adding another')
        args=['--replace-all',key,'https://github.com/',r'^https://github\.com/$'] if choice=='ssh' else ['--unset-all',key,r'^https://github\.com/$']
        result=subprocess.run([*command,*args],capture_output=True,timeout=10)
        if result.returncode and not (choice=='https' and result.returncode in (1,5)):
            raise ValueError('Git transport configuration failed; nothing changed')
        return path.read_bytes()


def replace(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,stage=tempfile.mkstemp(prefix='.developer-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(stage,path)
    finally:
        if os.path.exists(stage):os.unlink(stage)


def sha(data):return hashlib.sha256(data).hexdigest()


def save_backup(kind,before,after,existed,state=''):
    folder=journal.state_dir(state)/'developer'
    if folder.is_symlink():raise ValueError('Symlink developer backup directory')
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:raise ValueError('Developer backups must be private and owned')
    filename=uuid.uuid4().hex+'.json'
    record={'schema':1,'kind':kind,'before':base64.b64encode(before).decode(),'before_sha256':sha(before),'after_sha256':sha(after),'existed':existed}
    replace(folder/filename,(json.dumps(record,indent=2)+'\n').encode())
    return filename


def main(args,approve):
    action=args.action or 'status'
    if action=='ssh-agent':
        import ssh_agent
        return ssh_agent.main(args,approve)
    if action=='import-shell-backup':
        import shell_migration
        return shell_migration.import_backup(args,approve)
    if action in ('ssh','ssh-generate','ssh-add','ssh-status','ssh-copy','ssh-test','clone','import-git-backup'):
        import ssh_ops
        return ssh_ops.main(args,approve)
    if action=='status':
        print(json.dumps({'git':bool(shutil.which('git')),'shells':{k:bool(shutil.which(k)) for k in SHELLS},
            'note':'No keys, Git configuration values or shell files were read'},indent=2));return 0
    if action=='restore':
        if not args.value or not re.fullmatch('[a-f0-9]{32}\\.json',args.value):raise ValueError('Select an exact developer backup filename')
        folder=journal.state_dir(getattr(args,'developer_state',''),create=False)/'developer';backup=folder/args.value
        if any(p.is_symlink() for p in (backup,*backup.parents)) or not backup.is_file() or backup.stat().st_size>3*1048576 or backup.stat().st_mode&0o077 or backup.stat().st_uid!=os.getuid():
            raise ValueError('Unsafe developer backup')
        record=json.loads(backup.read_text())
        if not isinstance(record,dict) or record.get('schema')!=1 or type(record.get('existed')) is not bool:
            raise ValueError('Invalid developer backup schema')
        path=target(record['kind'])
        current=path.read_bytes() if path.exists() else b''
        if sha(current)!=record.get('after_sha256'):raise ValueError('Developer configuration changed since apply; restore refused')
        before=base64.b64decode(record['before'],validate=True)
        if sha(before)!=record.get('before_sha256'):raise ValueError('Corrupt developer backup')
        if record['kind'] in SHELLS:
            import shell_migration
            shell_migration.check_syntax(before,record['kind'])
        if args.dry_run:print('Dry run: would restore',path.name);return 0
        if record['kind']=='ssh-agent':
            import ssh_agent
            ssh_agent.require_editable()
        if not approve(args,'Restore developer configuration from its verified private backup?'):return 4
        path=target(record['kind'])
        if sha(path.read_bytes() if path.exists() else b'')!=record.get('after_sha256'):raise ValueError('Configuration changed during restore review; refusing overwrite')
        if record['kind']=='ssh-agent':ssh_agent.require_editable()
        if record['existed']:replace(path,before)
        else:path.unlink()
        print('Restored:',path.name)
        if record['kind']=='ssh-agent':print('Reload the reviewed unit state explicitly with developer ssh-agent reload --yes. No agent was started.')
        return 0
    if action not in ('git','git-transport','shell'):raise ValueError('developer status|git|git-transport|shell|ssh|ssh-agent|ssh-generate|ssh-add|import-git-backup|import-shell-backup|restore BACKUP.json')
    if action=='shell' and args.shell not in SHELLS:raise ValueError('developer shell requires --shell bash, zsh or fish')
    kind='git' if action in ('git','git-transport') else args.shell
    path=target(kind);existed=path.exists();before=path.read_bytes() if existed else b''
    if kind=='git':
        if action=='git':validate_identity(args.name,args.email)
        elif getattr(args,'transport',None) not in ('ssh','https'):raise ValueError('git-transport requires --transport ssh or https')
        if not shutil.which('git'):
            if args.dry_run:print('Dry run: Git prerequisite would be checked/installed before the reviewed identity change.');return 0
            if not approve(args,'Install the missing Git prerequisite from configured native repositories?'):return 4
            root=Path(__file__).resolve().parents[1]
            cp=subprocess.run(['bash',str(root/'scripts/prerequisites.sh'),'install','--runtime-only','--with-git','--without-ui','--yes'],timeout=900)
            if cp.returncode:return cp.returncode
    if action=='git':after=identity(before,args.name,args.email)
    elif action=='git-transport':after=transport(before,args.transport)
    else:
        if getattr(args,'migrate_legacy',False):
            import shell_migration
            migrated=shell_migration.migrate(before.decode('utf-8'),kind).encode()
            if migrated!=before and getattr(args,'current_sha256',None)!=sha(before):
                raise ValueError('Legacy block migration requires the reviewed current file --current-sha256')
        after=shell_content(before,kind,getattr(args,'banner','none'),use_agent=getattr(args,'use_toolkit_agent',False),
            greeting=getattr(args,'fish_greeting','keep'),migrate=getattr(args,'migrate_legacy',False))
        import shell_migration
        shell_migration.check_syntax(after,kind)
    if before==after:print('Developer configuration already matches.');return 0
    if args.dry_run:print('Dry run: would update',path.name,'after private backup; no credentials or file contents shown.');return 0
    if not approve(args,'Back up and update only '+path.name+'?'):return 4
    filename=save_backup(kind,before,after,existed,getattr(args,'developer_state',''))
    if path.exists()!=existed or path.exists() and path.read_bytes()!=before:raise ValueError('Configuration changed during review; retry')
    replace(path,after)
    print('Updated:',path.name,'; private backup:',filename)
    print('Existing SSH keys, credentials, login shells and services are unchanged.')
    return 0
