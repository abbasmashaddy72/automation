"""Exact legacy shell-block migration and explicit, conflict-safe backup import."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import developer

AGENT_BLOCK='''# Auto-start ssh-agent
if [ -z "$SSH_AUTH_SOCK" ]; then
    eval "$(ssh-agent -s)" >/dev/null
    ssh-add ~/.ssh/id_ed25519 >/dev/null 2>&1
fi'''
LABELS=('FETCH TOOL ON TERMINAL START','CUSTOM DEV SHELL SETUP','PHPV PATH SETUP','FISH GREETING DISABLE')


def migrate(text,shell):
    if shell not in developer.SHELLS:raise ValueError('Choose an explicit supported shell')
    pairs={'# === BEGIN '+label+' ===':'# === END '+label+' ===' for label in LABELS}
    ends=set(pairs.values());result=[];expected=None
    for line in text.splitlines(keepends=True):
        marker=line.rstrip('\r\n')
        if marker in pairs:
            if expected is not None:raise ValueError('Nested legacy shell markers; review manually')
            expected=pairs[marker];continue
        if marker in ends:
            if marker!=expected:raise ValueError('Unmatched legacy shell markers; review manually')
            expected=None;continue
        if expected is not None and re.fullmatch(r'# === (?:BEGIN|END) .+ ===',marker):raise ValueError('Unknown nested shell marker; review manually')
        if expected is None:result.append(line)
    if expected is not None:raise ValueError('Incomplete legacy shell block; review manually')
    result=''.join(result)
    for label in LABELS:
        if '# === '+label+' ===' in result:raise ValueError('Unmarked legacy shell section is ambiguous; review manually')
    if '# Auto-start ssh-agent' in result:
        pattern=r'(?m)^'+r'\r?\n'.join(re.escape(line) for line in AGENT_BLOCK.splitlines())+r'(?=\r?$)'
        result,count=re.subn(pattern,'',result)
        if count==0 or '# Auto-start ssh-agent' in result:raise ValueError('Edited legacy agent block; review manually')
    return result


def check_syntax(data,shell):
    if shell not in developer.SHELLS:raise ValueError('Choose bash, zsh or fish')
    executable=shutil.which(shell)
    if not executable:raise ValueError('Install the selected shell explicitly with packages install --select '+shell+' before configuring it')
    with tempfile.TemporaryDirectory(prefix='automation-shell-check-') as directory:
        path=Path(directory)/'startup';path.write_bytes(data);path.chmod(0o600)
        env=os.environ.copy()
        for name in ('BASH_ENV','ENV','SHELLOPTS','BASHOPTS','PROMPT_COMMAND','CDPATH'):env.pop(name,None)
        env.update(HOME=directory,XDG_CONFIG_HOME=directory,ZDOTDIR=directory)
        flags={'bash':['--noprofile','--norc','-n'],'zsh':['-d','-f','-n'],'fish':['--no-config','-n']}[shell]
        result=subprocess.run([executable,*flags,str(path)],capture_output=True,env=env,timeout=10)
        if result.returncode:raise ValueError('Shell syntax validation failed; no file changed and no configuration contents logged')


def import_backup(args,approve):
    if args.shell not in developer.SHELLS:raise ValueError('import-shell-backup requires --shell bash, zsh or fish')
    if not args.value:raise ValueError('Select one explicit absolute shell backup path')
    source=Path(args.value).expanduser()
    if not source.is_absolute() or any(p.is_symlink() for p in (source,*source.parents)):raise ValueError('Symlink/relative shell backup paths are forbidden')
    st=source.stat()
    if not source.is_file() or st.st_uid not in (0,os.getuid()) or st.st_nlink!=1 or st.st_mode&0o022 or st.st_size>1048576:
        raise ValueError('Shell backup must be a bounded regular file not writable by others')
    path=developer.target(args.shell);current=path.read_bytes() if path.exists() else b''
    if not isinstance(args.current_sha256,str) or not re.fullmatch('[a-f0-9]{64}',args.current_sha256) or developer.sha(current)!=args.current_sha256:
        raise ValueError('Provide --current-sha256 matching the current shell configuration')
    with source.open('rb') as stream:before=stream.read(1048577)
    if len(before)>1048576:raise ValueError('Shell backup grew beyond its size bound')
    check_syntax(before,args.shell)
    if args.dry_run:print('Dry run: would import a private shell restore receipt; no shell or original backup changed.');return 0
    if not approve(args,'Import the selected shell backup as a private conflict-safe restore receipt?'):return 4
    if (path.read_bytes() if path.exists() else b'')!=current:raise ValueError('Shell configuration changed during review')
    name=developer.save_backup(args.shell,before,current,True,getattr(args,'developer_state',''))
    print('Imported private shell backup:',name,'; restore it explicitly with developer restore.');return 0
