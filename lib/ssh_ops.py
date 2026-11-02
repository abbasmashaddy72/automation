"""Explicit SSH enrollment and legacy Git-backup import; never changes host trust."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import developer


def prerequisite(args,approve,command):
    if shutil.which(command):return 0
    if args.dry_run:print('Dry run: OpenSSH prerequisites would be checked before the selected operation.');return 0
    if not approve(args,'Install the missing OpenSSH client prerequisite from configured native repositories?'):return 4
    root=Path(__file__).resolve().parents[1]
    return subprocess.run(['bash',str(root/'scripts/prerequisites.sh'),'install','--runtime-only','--with-ssh','--without-ui','--yes'],timeout=900).returncode


def identity(value, *, existing=True):
    if not value:raise ValueError('Provide --identity-file; default SSH keys are never selected implicitly')
    path=Path(value).expanduser()
    source=Path(__file__).resolve().parents[1]
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)) or source in path.resolve().parents:
        raise ValueError('SSH identity must be an absolute non-symlink path outside the source tree')
    if any(c in str(path) for c in ('"','\\','%')) or any(ord(c)<32 for c in str(path)):
        raise ValueError('SSH identity path contains unsupported expansion or quoting characters')
    if path.parent.exists() and (path.parent.stat().st_uid!=os.getuid() or path.parent.stat().st_mode&0o077):
        raise ValueError('SSH identity directory must be private and owned (0700)')
    if existing:
        st=path.stat()
        if not path.is_file() or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_nlink!=1 or st.st_size>65536:
            raise ValueError('SSH identity must be a private owned regular file')
    return path


def configuration(args,key):
    for value,pattern in ((args.ssh_host,r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}'),
                          (args.hostname,r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}'),
                          (args.ssh_user,r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}')):
        if not isinstance(value,str) or not re.fullmatch(pattern,value):raise ValueError('Provide literal --ssh-host, --hostname and --ssh-user')
    return (f'# Automation Toolkit: explicitly selected identity\nHost {args.ssh_host}\n'
            f'    HostName {args.hostname}\n    User {args.ssh_user}\n    IdentityFile "{key}"\n'
            '    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n    ForwardAgent no\n').encode()


def import_backup(args,approve):
    # Old root-level receipts have no after-digest. Require explicit current
    # bytes instead of trusting a path from an old mutable state file.
    source=Path(args.value).expanduser() if args.value else None
    if source is None or not source.is_absolute() or any(p.is_symlink() for p in (source,*source.parents)):
        raise ValueError('Select one absolute legacy Git backup path without symlinks')
    st=source.stat()
    if not source.is_file() or st.st_size>1048576 or st.st_uid not in (0,os.getuid()) or st.st_mode&0o022 or st.st_nlink!=1:
        raise ValueError('Unsafe legacy Git backup')
    path=developer.target('git');current=path.read_bytes() if path.exists() else b''
    if not isinstance(args.current_sha256,str) or not re.fullmatch('[a-f0-9]{64}',args.current_sha256) or developer.sha(current)!=args.current_sha256:
        raise ValueError('Provide --current-sha256 matching the current Git configuration')
    before=source.read_bytes()
    if not shutil.which('git'):raise ValueError('Git is required to validate the legacy backup')
    with tempfile.TemporaryDirectory() as directory:
        copy=Path(directory)/'gitconfig';copy.write_bytes(before);copy.chmod(0o600)
        cp=subprocess.run(['git','config','--no-includes','--file',str(copy),'--list'],capture_output=True,timeout=10)
        if cp.returncode:raise ValueError('Invalid legacy Git configuration; nothing imported')
    if args.dry_run:print('Dry run: would import a private restore receipt; current Git configuration is unchanged.');return 0
    if not approve(args,'Import this legacy Git backup as a private restore receipt?'):return 4
    if (path.read_bytes() if path.exists() else b'')!=current:raise ValueError('Git configuration changed during review')
    filename=developer.save_backup('git',before,current,True,getattr(args,'developer_state',''))
    print('Imported private backup:',filename,'; restore explicitly with developer restore.');return 0


def main(args,approve):
    action=args.action
    if action=='import-git-backup':return import_backup(args,approve)
    if action=='clone':
        import vcs
        repo=vcs.repository(args.value)
        if not getattr(args,'destination',None):raise ValueError('Provide --destination for a new checkout')
        target=vcs.destination(args.destination)
        if target.exists() or not target.parent.is_dir() or target.parent.stat().st_uid!=os.getuid():raise ValueError('Clone destination must be new under an owned existing parent')
        if args.dry_run:print('Dry run: would authenticate and clone into a new directory; no network request sent');return 0
        if not approve(args,'Authenticate with the selected repository and clone a new checkout?'):return 4
        if not shutil.which('git'):
            root=Path(__file__).resolve().parents[1]
            result=subprocess.run(['bash',str(root/'setup.sh'),'packages','install','--select','git','--yes'],timeout=900)
            if result.returncode:return result.returncode
        vcs.clone(repo,target)
        print('Repository cloned; existing checkouts and credentials preserved');return 0
    if action=='ssh-status':
        folder=Path.home()/'.ssh'
        count=0
        if folder.is_dir() and not folder.is_symlink():
            for public in list(folder.glob('*.pub'))[:100]:
                if public.is_file() and not public.is_symlink() and public.stat().st_size<=16384:count+=1
        import json
        print(json.dumps({'public_key_files':count,'existing_agent_selected':bool(os.environ.get('SSH_AUTH_SOCK')),'note':'No key values or private Git configuration read'}));return 0
    key=identity(args.identity_file,existing=action!='ssh-generate')
    if action=='ssh-copy':
        public=key.with_name(key.name+'.pub')
        if public.is_symlink() or not public.is_file() or public.stat().st_uid!=os.getuid() or public.stat().st_size>16384 or public.stat().st_nlink!=1:raise ValueError('Select a regular owned public-key file paired with the identity')
        text=public.read_text().strip()
        if not re.match(r'(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+(?: .*)?\Z',text) or any(ord(c)<32 or ord(c)==127 for c in text):raise ValueError('Invalid public-key format')
        if args.dry_run:print('Dry run: would copy the selected public key only');return 0
        if not approve(args,'Copy only the selected public key through clipboard stdin or the controlling terminal?'):return 4
        result=prerequisite(args,approve,'ssh-keygen')
        if result:return result
        verified=subprocess.run(['ssh-keygen','-l','-f',str(public)],capture_output=True,timeout=10)
        if verified.returncode:raise ValueError('Native OpenSSH rejected the selected public key')
        target=['wl-copy'] if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-copy') else ['xclip','-selection','clipboard'] if os.environ.get('DISPLAY') and shutil.which('xclip') else None
        if target:
            result=subprocess.run(target,input=(text+'\n').encode(),timeout=10)
            if result.returncode:raise ValueError('Public-key clipboard operation failed')
        else:
            with open('/dev/tty','w') as terminal:terminal.write(text+'\n')
        print('Public key copied; private identity was not printed');return 0
    if action=='ssh-test':
        provider=getattr(args,'ssh_provider','github')
        if provider not in ('github','gitlab'):raise ValueError('Supported public SSH tests: github, gitlab')
        if args.dry_run:print('Dry run: would test selected identity against '+provider+'; host trust is unchanged');return 0
        result=prerequisite(args,approve,'ssh')
        if result:return result
        result=subprocess.run(['ssh','-T','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','git@'+provider+'.com'],
            capture_output=True,text=True,timeout=20)
        output=(result.stdout+'\n'+result.stderr)[:16384]
        verified=(provider=='github' and result.returncode==1 and 'successfully authenticated' in output and 'does not provide shell access' in output) or (provider=='gitlab' and result.returncode==0 and 'Welcome to GitLab' in output)
        print('SSH authentication verified' if verified else 'SSH authentication unverified; check the selected identity, existing agent and independently trusted host key')
        return 0 if verified else 3
    if action=='ssh-generate':
        public_target=key.with_name(key.name+'.pub')
        if key.exists() or public_target.exists() or public_target.is_symlink():
            raise ValueError('SSH identity/public key already exists; generation never overwrites keys')
        if args.dry_run:print('Dry run: would generate a passphrase-prompted SSH identity at the selected path.');return 0
        if not sys.stdin.isatty():raise ValueError('SSH generation requires an interactive terminal for native passphrase prompts')
        if not approve(args,'Generate a new SSH identity at the explicit path, preserving existing keys?'):return 4
        result=prerequisite(args,approve,'ssh-keygen')
        if result:return result
        key.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        identity(key,existing=False)
        with tempfile.TemporaryDirectory(prefix='.automation-ssh-',dir=key.parent) as folder:
            temporary=Path(folder)/'identity'
            cp=subprocess.run(['ssh-keygen','-t','ed25519','-a','64','-f',str(temporary)],check=False)
            if cp.returncode:return cp.returncode
            identity(temporary)
            public=temporary.with_name('identity.pub')
            if public.is_symlink() or not public.is_file() or public.stat().st_size>16384:raise ValueError('Invalid generated public key')
            os.link(temporary,key)
            try:os.link(public,public_target)
            except BaseException:
                if key.exists() and key.stat().st_ino==temporary.stat().st_ino:key.unlink()
                raise
        print('SSH identity created; enroll its public key with your provider manually.');return 0
    if action=='ssh-add':
        if not os.environ.get('SSH_AUTH_SOCK'):raise ValueError('An existing SSH agent is required; no agent is started automatically')
        if args.dry_run:print('Dry run: would add the selected identity to the existing SSH agent.');return 0
        if not approve(args,'Load the selected identity into the existing SSH agent?'):return 4
        result=prerequisite(args,approve,'ssh-add')
        if result:return result
        return subprocess.run(['ssh-add',str(key)],check=False).returncode
    if action!='ssh':raise ValueError('Unknown SSH action')
    after=configuration(args,key)
    path=developer.target('ssh')
    if path.parent.exists() and (path.parent.stat().st_uid!=os.getuid() or path.parent.stat().st_mode&0o077):raise ValueError('SSH configuration directory must be private and owned')
    existed=path.exists();before=path.read_bytes() if existed else b''
    if before==after:print('SSH configuration already matches.');return 0
    # This separate config is exclusively generated; refuse unrelated edits.
    if existed and (not before.startswith(b'# Automation Toolkit: explicitly selected identity\n') or
                    getattr(args,'current_sha256',None)!=developer.sha(before)):
        raise ValueError('Existing SSH config differs; review it and supply its --current-sha256 before replacement')
    if args.dry_run:print('Dry run: would write a separate SSH config after private backup.');return 0
    if not approve(args,'Back up and write ~/.ssh/automation-toolkit.conf for the explicit identity?'):return 4
    filename=developer.save_backup('ssh',before,after,existed,getattr(args,'developer_state',''))
    if path.exists()!=existed or path.exists() and path.read_bytes()!=before:raise ValueError('SSH configuration changed during review')
    developer.replace(path,after)
    print('SSH config ready; private backup:',filename)
    print('Use ssh -F ~/.ssh/automation-toolkit.conf '+args.ssh_host+'. Enroll the public key manually; existing config, agents and known_hosts are preserved.')
    return 0
