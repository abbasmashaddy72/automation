"""One exact toolkit-owned user agent; never adopts or stops another SSH agent."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import developer

NAME='automation-ssh-agent.service'
MARKER='# Managed by automation-toolkit SSH agent v1'


def checked(path):
    path=Path(path).expanduser()
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Agent paths must be absolute without symlinks')
    return path


def executable(path, *, assets=True):
    path=checked(path)
    if any(ord(c)<32 for c in str(path)):raise ValueError('Control character in agent executable path')
    if assets:
        st=path.stat()
        if not path.is_file() or not os.access(path,os.X_OK) or st.st_uid not in (0,os.getuid()) or st.st_mode&0o022:
            raise ValueError('Agent executable must be reviewed, executable and not writable by others')
    return str(path)


def quote(value):
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def unit_text(binary):
    binary=executable(binary,assets=False)
    return '\n'.join([MARKER,'# Executable-JSON: '+json.dumps(binary),'[Unit]','Description=Automation Toolkit private SSH agent',
        '[Service]','Type=simple','ExecStart='+quote(binary)+' -D -a "%t/automation-ssh-agent/agent.sock"',
        'RuntimeDirectory=automation-ssh-agent','RuntimeDirectoryMode=0700','UMask=0077','NoNewPrivileges=yes',
        'Restart=no','KillMode=control-group','[Install]','WantedBy=default.target',''])


def owned():
    path=developer.target('ssh-agent')
    if not path.exists():raise ValueError('Configure the toolkit-owned SSH agent first')
    if path.stat().st_mode&0o077 or path.stat().st_size>16384:raise ValueError('Unsafe agent unit')
    text=path.read_text(encoding='utf-8');lines=text.splitlines()
    if len(lines)<2 or lines[0]!=MARKER or not lines[1].startswith('# Executable-JSON: '):raise ValueError('Existing agent unit is unrelated; refusing adoption')
    binary=json.loads(lines[1][len('# Executable-JSON: '):])
    if not isinstance(binary,str) or text!=unit_text(binary):raise ValueError('Agent unit was edited; refusing lifecycle changes')
    return path,binary


def control(*args):
    return subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=15)


def require_editable():
    result=control('show',NAME,'--property=ActiveState','--property=UnitFileState')
    if result.returncode or len(result.stdout)>4096:raise ValueError('Cannot establish private agent state; no configuration changed')
    values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if values.get('ActiveState') not in ('inactive','failed') or values.get('UnitFileState') not in ('disabled',''):
        raise ValueError('Stop and disable the toolkit agent explicitly before restoring/removing its unit')


def socket_path():
    root=os.environ.get('XDG_RUNTIME_DIR')
    if not root:raise ValueError('A private XDG_RUNTIME_DIR is required')
    root=checked(root);folder=root/'automation-ssh-agent';path=checked(folder/'agent.sock')
    for directory in (root,folder):
        if directory.exists() and (not directory.is_dir() or directory.stat().st_uid!=os.getuid() or directory.stat().st_mode&0o077):
            raise ValueError('Agent runtime directory must be private and owned')
    if path.exists():
        st=path.stat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('Unsafe private agent socket')
    return path


def environment():
    env=os.environ.copy();env['SSH_AUTH_SOCK']=str(socket_path());env.pop('SSH_AGENT_PID',None);env['LC_ALL']='C'
    return env


def check_runtime_contents():
    path=socket_path();folder=path.parent
    if folder.exists():
        with os.scandir(folder) as entries:
            if any(entry.name!='agent.sock' for entry in entries):raise ValueError('Reserved agent runtime contains later user files; preserve them before lifecycle changes')


def probe():
    path=socket_path()
    if not path.exists():return 'missing'
    binary=shutil.which('ssh-add')
    if not binary:return 'unverified'
    try:result=subprocess.run([binary,'-l'],capture_output=True,env=environment(),timeout=5)
    except (OSError,subprocess.TimeoutExpired):return 'unverified'
    # Only native exit codes are reported; fingerprints/identity comments are
    # captured in memory and never copied into ordinary logs or status output.
    if result.returncode==0:return 'ready-with-keys'
    if result.returncode==1 and (result.stdout+result.stderr).strip()==b'The agent has no identities.':return 'ready-empty'
    return 'unverified'


def main(args,approve):
    action=args.value or 'status';path=developer.target('ssh-agent')
    allowed={'status','configure','start','stop','enable','disable','uninstall','reload','add'}
    if action not in allowed:raise ValueError('ssh-agent status|configure|start|stop|enable|disable|uninstall|reload|add')
    if action=='status':
        if not path.exists():print('No toolkit-owned SSH agent configured.');return 0
        owned()
        try:state=probe()
        except ValueError:state='runtime-unavailable'
        print('Toolkit SSH agent:',state,'; no identity values displayed.');return 0
    if action=='configure':
        if path.exists():
            owned();print('Toolkit agent already configured; start/autostart remain explicit.');return 0
        # A live pre-existing socket at the reserved path is not ours to adopt.
        if os.environ.get('XDG_RUNTIME_DIR') and socket_path().parent.exists():raise ValueError('A pre-existing runtime directory occupies the toolkit path; no adoption')
        state=control('show',NAME,'--property=LoadState','--property=ActiveState')
        if state.returncode or len(state.stdout)>4096:raise ValueError('Cannot establish that the reserved agent unit is absent')
        fields=dict(line.split('=',1) for line in state.stdout.splitlines() if '=' in line)
        if fields.get('LoadState')!='not-found' or fields.get('ActiveState')!='inactive':raise ValueError('A loaded agent unit already occupies this name; no adoption')
        binary=shutil.which('ssh-agent')
        if not binary:
            if args.dry_run:print('Dry run: would check OpenSSH prerequisites and create the private agent unit.');return 0
            import ssh_ops
            result=ssh_ops.prerequisite(args,approve,'ssh-agent')
            if result:return result
            binary=shutil.which('ssh-agent')
        if not binary:raise ValueError('Native ssh-agent is still unavailable')
        text=unit_text(executable(str(Path(binary).resolve()))).encode()
        if args.dry_run:print('Dry run: would configure only '+NAME+'; no agent started.');return 0
        if not approve(args,'Create the toolkit SSH agent user unit without starting/enabling it?'):return 4
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.parent.stat().st_uid!=os.getuid() or path.parent.stat().st_mode&0o022:raise ValueError('Unsafe user unit directory')
        backup=developer.save_backup('ssh-agent',b'',text,False,getattr(args,'developer_state',''))
        if path.exists() or path.is_symlink():raise ValueError('Agent unit appeared during review; refusing overwrite')
        fd,stage=tempfile.mkstemp(prefix='.ssh-agent-',dir=path.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
            os.link(stage,path)  # create-only, including concurrent empty files
        finally:Path(stage).unlink(missing_ok=True)
        try:
            if control('daemon-reload').returncode:raise ValueError('User manager reload failed')
        except BaseException:
            developer.target('ssh-agent')
            if path.read_bytes()==text:path.unlink()
            else:raise ValueError('Agent unit changed during failed reload; preserved for manual review')
            raise
        print('Configured:',NAME,'; private backup:',backup,'; no keys loaded or agent started.');return 0
    observed=None
    if action!='reload':owned();observed=path.read_bytes()
    if action=='add':
        import ssh_ops
        key=ssh_ops.identity(args.identity_file)
        if socket_path().parent in key.parents:raise ValueError('Keep SSH identities outside the agent runtime directory')
        if probe() not in ('ready-empty','ready-with-keys'):raise ValueError('Private toolkit agent is not ready')
    if args.dry_run:print('Dry run:',action,NAME,'; no agent or identity changed.');return 0
    if not approve(args,'Apply '+action+' only to the toolkit-owned SSH agent?'):return 4
    if action=='reload':return control('daemon-reload').returncode
    owned()
    if path.read_bytes()!=observed:raise ValueError('Agent unit changed during review; no lifecycle action applied')
    if action=='uninstall':
        require_editable()
        before=path.read_bytes();backup=developer.save_backup('ssh-agent',before,b'',True,getattr(args,'developer_state',''))
        if path.read_bytes()!=before:raise ValueError('Agent unit changed during review')
        path.unlink();result=control('daemon-reload').returncode
        print('Removed private agent unit; keys, shell files and other agents preserved. Backup:',backup);return result
    if action=='add':
        result=control('show',NAME,'--property=ActiveState','--value')
        if result.returncode or result.stdout.strip()!='active':raise ValueError('Toolkit-owned service must be active before adding a selected key')
        binary=shutil.which('ssh-add')
        if not binary:raise ValueError('ssh-add is required')
        return subprocess.run([binary,str(key)],env=environment(),check=False).returncode
    if action=='start':
        _,binary=owned();executable(binary)
        state=control('show',NAME,'--property=ActiveState','--value')
        if not state.returncode and state.stdout.strip()=='active':
            return 0 if probe() in ('ready-empty','ready-with-keys') else 3
        if probe() not in ('missing',):raise ValueError('Toolkit socket already exists; inspect status without replacing it')
        check_runtime_contents()
    if action=='stop':check_runtime_contents()
    result=control(action,NAME)
    if result.returncode:return result.returncode
    if action=='start':
        # Process acceptance and socket readiness are distinct; do not mask a
        # failed startup or restart it automatically.
        print('Start accepted; verify socket readiness with developer ssh-agent status.')
        state=control('show',NAME,'--property=ActiveState','--value')
        return 0 if not state.returncode and state.stdout.strip()=='active' else 3
    return 0
