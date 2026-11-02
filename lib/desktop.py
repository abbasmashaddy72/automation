"""Session-aware desktop favorites with explicit review and conflict-safe restore."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


def detect():
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', os.environ.get('DESKTOP_SESSION','')).lower()
    name = next((name for name, tokens in (
        ('kde', ('kde','plasma')), ('gnome', ('gnome','ubuntu')), ('xfce', ('xfce',)),
        ('cinnamon', ('cinnamon',)), ('mate', ('mate',))) if any(token in desktop for token in tokens)), 'unknown')
    session = 'wayland' if os.environ.get('WAYLAND_DISPLAY') else 'x11' if os.environ.get('DISPLAY') else 'headless'
    return {'desktop':name, 'session':session, 'favorites_adapter':name if name in ('gnome','kde','xfce','cinnamon') and session != 'headless' else None}


def checked(path):
    path = Path(path).expanduser()
    if not path.is_absolute(): raise ValueError('Desktop paths must be absolute')
    if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError('Symlink desktop paths are forbidden')
    return path


def applications(names):
    if not names or len(names) > 100: raise ValueError('Select 1–100 exact .desktop IDs')
    bases = [Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'applications']
    bases += [Path(p)/'applications' for p in os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':') if p.startswith('/')]
    result=[]
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.desktop', name):
            raise ValueError('Favorites require exact .desktop IDs, without paths')
        if not any((p/name).is_file() for p in bases): raise ValueError('Desktop application not found: '+name)
        if name not in result: result.append(name)
    return result


def gsettings(*args):
    cp = subprocess.run(['gsettings', *args], capture_output=True, text=True, timeout=10)
    if cp.returncode: raise ValueError('GNOME settings operation failed')
    return cp.stdout.strip()


def kde_path():
    return checked(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'plasma-org.kde.plasma.desktop-appletsrc')


def kde_update(text, names):
    # Locate the actual Task Manager plugin rather than any General/launchers row.
    headers = list(re.finditer(r'^((?:\[[^\]\n]+\])+)[ \t]*$', text, re.M))
    sections = {m[1]: (m.end(), headers[i+1].start() if i+1 < len(headers) else len(text)) for i,m in enumerate(headers)}
    plugins = []
    for header, (start,end) in sections.items():
        if re.search(r'^plugin=org\.kde\.plasma\.(?:icontasks|taskmanager)\s*$', text[start:end], re.M):
            plugins.append(header + '[Configuration][General]')
    if len(plugins) != 1: raise ValueError('Exactly one KDE Task Manager is required; review multiple panels manually')
    header = plugins[0]
    existing=[]
    if header in sections:
        start,end=sections[header]
        match=re.search(r'^launchers=(.*)$',text[start:end],re.M)
        if match:existing=[item for item in match[1].split(',') if item]
    row = 'launchers=' + ','.join(dict.fromkeys([*existing,*('applications:'+name for name in names)])) + '\n'
    if header not in sections: return text.rstrip() + '\n\n' + header + '\n' + row
    start,end = sections[header]
    body = text[start:end].lstrip('\n')
    if re.search(r'^launchers=.*$', body, re.M): body = re.sub(r'^launchers=.*\n?', row, body, count=1, flags=re.M)
    else: body = row + body
    return text[:start] + '\n' + body + text[end:]


def snapshot(adapter):
    if adapter in ('xfce','cinnamon'):
        import panels
        return panels.snapshot(adapter)
    if adapter == 'gnome':
        value = gsettings('get','org.gnome.shell','favorite-apps')
        value = value.removeprefix('@as ')
        names = ast.literal_eval(value)
        if not isinstance(names,list) or any(not isinstance(x,str) for x in names): raise ValueError('Invalid GNOME favorites')
        return names
    path = kde_path()
    if not path.is_file() or path.stat().st_size > 4*1024*1024: raise ValueError('KDE settings file missing or too large')
    return path.read_text()


def write(adapter, value):
    if adapter in ('xfce','cinnamon'):
        import panels
        return panels.write(value)
    if adapter == 'gnome':
        gsettings('set','org.gnome.shell','favorite-apps',str(value)); return
    import tempfile
    path = kde_path()
    fd, stage = tempfile.mkstemp(prefix='.plasma-', dir=path.parent)
    try:
        os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd,'w') as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        if os.path.exists(stage): os.unlink(stage)


def backup_root():
    return checked(Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state'))) / 'automation-toolkit/desktop')


def save_receipt(root, name, record):
    import tempfile
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077: raise ValueError('Desktop backup directory must be private (0700)')
    fd, stage = tempfile.mkstemp(prefix='.backup-',dir=root)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(record,stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(stage,root/name)
    finally:
        if os.path.exists(stage): os.unlink(stage)


def main(args, approved):
    info = detect(); action = args.action or 'status'
    if action == 'status': print(json.dumps(info,indent=2)); return 0
    if action not in ('plan','apply','restore'): raise ValueError('desktop status|plan|apply|restore BACKUP.json')
    adapter = info['favorites_adapter']
    if not adapter:
        print('Favorites are unsupported in this session. No desktop settings changed.'); return 3
    if adapter == 'gnome' and not shutil.which('gsettings'):
        print('GNOME gsettings unavailable.'); return 3
    if adapter=='xfce' and not shutil.which('xfconf-query'):print('XFCE xfconf-query unavailable.');return 3
    if adapter=='cinnamon' and not shutil.which('gsettings'):print('Cinnamon gsettings unavailable.');return 3
    before = snapshot(adapter)
    if action == 'restore':
        if not args.value or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}\.json', args.value): raise ValueError('Select an exact desktop backup filename')
        path = checked(backup_root()/args.value)
        if path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077 or path.stat().st_nlink!=1:raise ValueError('Desktop backup must be private and owned')
        if path.stat().st_size > 8*1024*1024: raise ValueError('Desktop backup too large')
        record = json.loads(path.read_text())
        if record.get('format') != 1 or record.get('adapter') != adapter or before != record.get('after'):
            raise ValueError('Desktop changed since apply; automatic restore refused')
        after = record['before']
    else:
        names = applications([name for group in (args.select or []) for name in group.split(',')])
        if adapter=='gnome':after=list(dict.fromkeys([*before,*names]))
        elif adapter=='kde':after=kde_update(before,names)
        else:
            import panels
            after=panels.update(before,names)
        print('Reviewed favorites:',', '.join(names))
    if action == 'plan' or args.dry_run:
        print('Plan only; desktop settings unchanged.'); return 0
    if before == after: print('Desktop settings already match.'); return 0
    if not approved(args,'Back up and change only the reviewed desktop favorites?'): return 4
    if snapshot(adapter) != before: raise ValueError('Desktop changed during review; retry')
    name = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json'
    record = {'format':1, 'adapter':adapter, 'before':before, 'after':after}
    if len(json.dumps(record).encode())>8*1024*1024:raise ValueError('Desktop backup would exceed the supported size')
    save_receipt(backup_root(),name,record)
    try:
        write(adapter,after)
        if snapshot(adapter) != after: raise ValueError('Desktop verification failed')
    except (OSError, ValueError, subprocess.SubprocessError):
        if snapshot(adapter)==after:write(adapter,before)
        raise
    print('Desktop settings updated; backup:',name)
    if adapter == 'kde': print('Log out and back in to reload Plasma. No session processes were restarted.')
    return 0
