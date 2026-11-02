#!/usr/bin/env python3
"""Unified, non-root Linux automation controller. Python >=3.9, stdlib only.

Mutations require an explicit command and user approval. Production Laravel workflows have separate explicit entrypoints; removed
installers are never dispatched.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import catalog
import discovery
import journal
import lerd_ops
import providers
import wizard
import workflows
import extensions
import bootstrap
import sources
import progress
import cache
import configuration

ROOT = Path(__file__).resolve().parents[1]
PKG_FILE = ROOT / 'config/packages/default.json'
FAMILIES = {
    'arch': ('arch', 'archlinux', 'manjaro', 'cachyos', 'endeavouros', 'garuda', 'artix'),
    'debian': ('debian', 'ubuntu', 'linuxmint', 'pop', 'kali', 'elementary', 'zorin', 'raspbian'),
    'fedora': ('fedora', 'nobara'),
    'rhel': ('rhel', 'centos', 'rocky', 'almalinux', 'ol'),
    'opensuse': ('opensuse', 'opensuse-tumbleweed', 'opensuse-leap', 'suse', 'sles'),
    'alpine': ('alpine',),
}
MANAGERS = {'arch': 'pacman', 'debian': 'apt-get', 'fedora': 'dnf', 'rhel': 'dnf',
            'opensuse': 'zypper', 'alpine': 'apk'}
FLATPAK_IDS = {'firefox': 'org.mozilla.firefox', 'keepassxc': 'org.keepassxc.KeePassXC',
               'vlc': 'org.videolan.VLC', 'dbeaver': 'io.dbeaver.DBeaverCommunity'}
ALIASES = {'python3': {'arch': 'python'}, 'shfmt': {'debian': 'shfmt'},
           'nodejs': {'arch': 'nodejs'}, 'git': {}, 'curl': {}}
TRUE = ('true', 'yes', 'on', '1')
KEYS = {'AUTOMATION_PROFILE', 'AUTOMATION_NONINTERACTIVE', 'AUTOMATION_LERD',
        'AUTOMATION_PREFER_FLATPAK', 'AUTOMATION_ENABLE_AUR', 'AUTOMATION_PREFER_SHELLY',
        'AUTOMATION_AUTO_SEARCH', 'AUTOMATION_SEARCH_LIMIT',
        'AUTOMATION_PACKAGE_TIMEOUT', 'AUTOMATION_RETRIES', 'AUTOMATION_BACKUP_DIR',
        'AUTOMATION_STATE_DIR', 'AUTOMATION_SELECTED_PACKAGES', 'AUTOMATION_EXCLUDED_PACKAGES', 'AUTOMATION_AI_BACKEND', 'AUTOMATION_AI_CONTEXT',
        'AUTOMATION_AI_THREADS', 'AUTOMATION_AI_QUOTA', 'AUTOMATION_AI_PORT','AUTOMATION_PROJECT_SITES_DIR'}


def os_release(path='/etc/os-release'):
    result = {}
    try:
        for line in Path(path).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if re.fullmatch(r'[A-Z_]+', key):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                result[key] = value
    except OSError:
        pass
    return result


def get_family(data):
    ids = [data.get('ID', '').lower(), *data.get('ID_LIKE', '').lower().split()]
    # Specific distribution ID takes priority over generic parent ID_LIKE.
    for item in ids:
        for family, names in FAMILIES.items():
            if item in names:
                return family
    return 'unknown'


def platform_info(data=None):
    release = os_release() if data is None else data
    family = get_family(release)
    wsl = bool(os.environ.get('WSL_DISTRO_NAME'))
    try:
        wsl = wsl or 'microsoft' in Path('/proc/version').read_text().lower()
    except OSError:
        pass
    container = Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()
    try:
        container = container or any(x in Path('/proc/1/cgroup').read_text() for x in ('docker', 'lxc', 'kubepods'))
    except OSError:
        pass
    init = 'systemd' if Path('/run/systemd/system').is_dir() else 'other'
    user_systemd = False
    if init == 'systemd' and shutil.which('systemctl'):
        try:
            user_systemd = subprocess.run(['systemctl', '--user', 'show-environment'], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            user_systemd = False
    desktop = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    version = release.get('VERSION_ID') or ('rolling' if family == 'arch' else release.get('BUILD_ID','unknown'))
    return {'id': release.get('ID', 'unknown'), 'version': version,
            'family': family, 'manager': MANAGERS.get(family), 'arch': platform.machine(),
            'wsl': wsl, 'container': container, 'init': init, 'user_systemd': user_systemd,
            'desktop': desktop,
            'immutable': release.get('VARIANT_ID','').lower() in providers.IMMUTABLE_VARIANTS
            or release.get('ID','').lower() in providers.IMMUTABLE_IDS or Path('/run/ostree-booted').exists()}


def lerd_compat(info):
    reasons = []
    if info['family'] == 'unknown' or info['family'] == 'alpine':
        reasons.append('Unverified distribution or non-systemd default; manual support check needed')
    if info['arch'] not in ('x86_64', 'aarch64', 'amd64', 'arm64'):
        reasons.append('Lerd release binaries require amd64 or arm64')
    if info['init'] != 'systemd' or not info['user_systemd']:
        reasons.append('Active systemd user session is required')
    if info['container']:
        reasons.append('Containers do not provide the supported host Podman/systemd workflow')
    if info['wsl']:
        reasons.append('WSL2 support is beta; manual setup required')
    if shutil.which('podman'):
        try:
            p = subprocess.run(['podman', '--version'], text=True, capture_output=True, timeout=5)
            match = re.search(r'(\d+)\.(\d+)', p.stdout)
            if match and tuple(map(int, match.groups())) < (4, 5):
                reasons.append('Podman 4.5+ required')
        except (OSError, subprocess.TimeoutExpired):
            reasons.append('Podman executable could not be checked')
    return reasons


def config_file(path):
    values = {}
    if path.is_symlink(): raise ValueError('Symlink configuration files are forbidden')
    if not path.exists():
        return values
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Config file is too large')
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z_]+)=(.*)', line)
        if not match or match[1] not in KEYS:
            raise ValueError(f'Invalid configuration line {n} in {path}')
        if match[1] in values: raise ValueError(f'Duplicate configuration key at line {n}')
        val = match[2].strip()
        if val.startswith(('"', "'")):
            if len(val)<2 or val[-1]!=val[0]: raise ValueError(f'Unbalanced configuration quotes at line {n}')
            val=val[1:-1]
        if '$(' in val or '`' in val or '${' in val or '\n' in val:
            raise ValueError(f'Unsafe configuration value at line {n}')
        values[match[1]] = val
    return values


def validate_settings(settings):
    """Reject invalid settings before any mutation; do not execute .env as shell."""
    bool_keys = {'AUTOMATION_NONINTERACTIVE','AUTOMATION_LERD','AUTOMATION_PREFER_FLATPAK',
                 'AUTOMATION_ENABLE_AUR','AUTOMATION_PREFER_SHELLY','AUTOMATION_AUTO_SEARCH'}
    for key,value in settings.items():
        if key not in KEYS:
            raise ValueError('Unknown configuration setting: '+key)
        if not isinstance(value,str): raise ValueError('Non-string configuration: '+key)
        if key in bool_keys and value.lower() not in ('true','false','yes','no','on','off','1','0'):
            raise ValueError(f'{key} must be true/false')
    numeric={'AUTOMATION_SEARCH_LIMIT':(1,10),'AUTOMATION_PACKAGE_TIMEOUT':(30,14400),
             'AUTOMATION_RETRIES':(0,10),'AUTOMATION_AI_PORT':(1,65535),
             'AUTOMATION_AI_THREADS':(1,512),'AUTOMATION_AI_CONTEXT':(128,1048576)}
    for key,(lower,upper) in numeric.items():
        if key in settings:
            value=settings[key]
            if key in ('AUTOMATION_AI_PORT','AUTOMATION_AI_THREADS') and value=='auto':continue
            if not value.isascii() or not value.isdecimal() or not lower<=int(value)<=upper:
                raise ValueError(f'{key} must be an integer between {lower} and {upper}')
    quota=settings.get('AUTOMATION_AI_QUOTA','300%')
    if quota!='auto' and (not re.fullmatch(r'(?:[1-9][0-9]{0,3}|10000)%', quota) or not 1<=int(quota[:-1])<=10000):
        raise ValueError('AUTOMATION_AI_QUOTA must be 1%–10000%')
    if settings.get('AUTOMATION_PROFILE','default') not in ('default','minimal','developer'):
        raise ValueError('Invalid profile')
    if settings.get('AUTOMATION_AI_BACKEND','llamacpp') not in ('llamacpp','ollama','vllm'):
        raise ValueError('Invalid AI backend')
    for key in ('AUTOMATION_SELECTED_PACKAGES','AUTOMATION_EXCLUDED_PACKAGES'):
        if settings.get(key):
            for term in settings[key].split(','):
                discovery.validate_term(term.strip())
    for key in ('AUTOMATION_BACKUP_DIR','AUTOMATION_STATE_DIR','AUTOMATION_PROJECT_SITES_DIR'):
        if settings.get(key):
            path=Path(settings[key]).expanduser()
            if not path.is_absolute() or path == Path('/') or ROOT==path or ROOT in path.parents:
                raise ValueError(f'{key} must be an absolute directory outside the toolkit')
            if path.is_symlink(): raise ValueError(f'{key} cannot be a symlink')
    return settings


def config(args):
    # Saved profiles supply defaults, never override local .env or CLI flags.
    settings = dict(config_file(ROOT / 'config/defaults.env'))
    local = config_file(ROOT / '.env')
    if getattr(args, 'saved_profile', None):
        state = os.environ.get('AUTOMATION_STATE_DIR', local.get('AUTOMATION_STATE_DIR', ''))
        settings.update(workflows.saved_profile(args.saved_profile, state, validate_settings))
    settings.update(local)
    for key in KEYS:
        if key in os.environ:
            settings[key] = os.environ[key]
    if args.non_interactive:
        settings['AUTOMATION_NONINTERACTIVE'] = 'true'
    if args.no_lerd: settings['AUTOMATION_LERD'] = 'false'
    if args.enable_aur: settings['AUTOMATION_ENABLE_AUR'] = 'true'
    if args.prefer_flatpak: settings['AUTOMATION_PREFER_FLATPAK'] = 'true'
    if args.prefer_shelly: settings['AUTOMATION_PREFER_SHELLY'] = 'true'
    if args.no_auto_search: settings['AUTOMATION_AUTO_SEARCH'] = 'false'
    if args.profile: settings['AUTOMATION_PROFILE'] = args.profile
    return validate_settings(settings)


def run(cmd, *, mutate=False, args=None, timeout=900, retries=0):
    print('$', ' '.join(map(str, cmd)), flush=True)
    if mutate and args is not None and args.dry_run:
        return 0
    try:
        if retries:
            for attempt in range(retries+1):
                with progress.waiting('Native package transaction (attempt '+str(attempt+1)+')'):
                    completed=subprocess.run(cmd,timeout=timeout,text=True,capture_output=True)
                output=(completed.stdout or '')+'\n'+(completed.stderr or '')
                print(output.strip(),flush=True)
                locked=any(pattern in output.lower() for pattern in (
                    'could not get lock','unable to lock database','failed to init transaction (unable to lock database)',
                    'system management is locked','another app is currently holding','waiting for process with pid',
                    'failed to obtain rpm transaction lock','cannot obtain a lock on the package database'))
                if completed.returncode==0 or not locked or attempt==retries:return completed.returncode
                print('Native package manager is busy; retrying the same approved transaction.',flush=True)
                time.sleep(min(5,attempt+1))
        return subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f'Timed out after {timeout}s', file=sys.stderr)
        return 124
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 127


def approved(args, message):
    if args.dry_run:
        return True
    if args.yes:
        return True
    if args.non_interactive or not sys.stdin.isatty():
        print('Refusing mutation without --yes in non-interactive mode', file=sys.stderr)
        return False
    if shutil.which('gum'):
        return subprocess.run(['gum', 'confirm', message]).returncode == 0
    return input(f'{message} [y/N]: ').strip().lower() in ('y', 'yes')


def package_catalog(info):
    """Include unavailable entries for honest interactive status reporting."""
    return json.loads(PKG_FILE.read_text())['packages']


def package_native_name(name, family, info=None):
    if info is not None:
        candidates=providers.candidates(name, info)
        return candidates[0] if candidates else None
    return catalog.native_name(name, family)


def _query(cmd, *, timeout=12):
    if not shutil.which(cmd[0]):
        return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,env={**os.environ,'LC_ALL':'C'})
    except (OSError, subprocess.TimeoutExpired):
        return None


def installed(name, family):
    if name=='curl' and family in ('fedora','rhel') and shutil.which('curl'):
        # Minimal RPM base images ship an installed curl-minimal provider.
        # Trust observed RPM file ownership, never a fuzzy package-name match;
        # preserve it instead of attempting a conflicting full-curl replacement.
        provider=_query(['rpm','-q','--qf','%{NAME}\n','--whatprovides','/usr/bin/curl'],timeout=6)
        if provider is not None and provider.returncode==0 and provider.stdout.strip() in ('curl','curl-minimal'):
            return True
    if name == 'lerd':
        return bool(shutil.which('lerd') or (Path.home()/'.local/bin/lerd').is_file())
    if name.startswith('ai-'):
        return bool(shutil.which({'ai-ollama':'ollama','ai-llamacpp':'llama-server','ai-vllm':'vllm'}.get(name, '__missing__')))
    p = package_native_name(name, family)
    if not p:
        try: p = discovery.validate_term(name)
        except ValueError: return False
    queries = {'arch': ['pacman', '-Q', p], 'debian': ['dpkg-query', '-W', '-f=${Status}', p],
               'fedora': ['rpm', '-q', p], 'rhel': ['rpm', '-q', p],
               'opensuse': ['rpm', '-q', p], 'alpine': ['apk', 'info', '-e', p]}
    cmd = queries.get(family)
    if not cmd:
        return False
    proc = _query(cmd, timeout=6)
    return proc is not None and proc.returncode == 0 and (family != 'debian' or 'install ok installed' in proc.stdout)


def aur_helper(info):
    if info['family'] != 'arch':
        return None
    return next((x for x in ('paru', 'yay', 'pamac') if shutil.which(x)), None)


def aur_available(name, info):
    # Legacy boolean API remains available, but discovers through ALL installed
    # providers. No static AUR allowlist. Only exact metadata is accepted.
    return bool(sources.search_exact(name, info))


def flatpak_installed(name):
    app_id = catalog.FLATPAKS.get(name)
    if not app_id or not shutil.which('flatpak'):
        return False
    for scope in ('--user', '--system'):
        proc = _query(['flatpak','info',scope,app_id], timeout=6)
        if proc is not None and proc.returncode == 0:
            return True
    return False


def flatpak_scope(name):
    """Return a configured, accessible Flathub scope, without adding remotes."""
    if name not in catalog.FLATPAKS or not shutil.which('flatpak'):
        return None
    for scope in ('--user','--system'):
        proc=_query(['flatpak','remote-info',scope,'flathub',catalog.FLATPAKS[name]],timeout=8)
        if proc is not None and proc.returncode==0:return scope
    return None


def flatpak_available(name):
    return flatpak_scope(name) is not None


def available(name, info):
    family=info['family']
    if name=='lerd': return not lerd_compat(info)
    if name.startswith('ai-'):
        if name=='ai-ollama':
            return family in catalog.FAMILIES and info.get('arch') in ('x86_64','aarch64','amd64','arm64') and not info.get('container',False)
        return family=='arch' and name in ('ai-llamacpp','ai-vllm')
    # Query only distribution-configured native repositories, requiring an
    # *exact* matching package name rather than successful command exit alone.
    return bool(providers.choose_native(name,info))


def native_install_cmd(names, info):
    """Execute only verified, explicit native package names as an argv array."""
    family = info['family']
    if family not in MANAGERS or not names:
        raise ValueError('Unsupported package manager or empty package list')
    for name in names: discovery.validate_term(name)
    prefix = [] if os.geteuid() == 0 else ['sudo']
    commands = {'arch':['pacman','-S','--needed','--noconfirm'],
                'debian':['apt-get','install','-y'],
                'fedora':['dnf','install','-y'], 'rhel':['dnf','install','-y'],
                'opensuse':['zypper','--non-interactive','install'],
                'alpine':['apk','add']}
    return [*prefix,*commands[family],*names]


def install_cmd(name, info):
    mapped = package_native_name(name, info['family'])
    if not mapped: raise ValueError(f'No curated native package mapping for {name} on {info["family"]}')
    return native_install_cmd([mapped],info)


def install_batch_cmd(packages, info):
    names = [package_native_name(p,info['family']) for p in packages]
    if any(not x for x in names): raise ValueError('No curated package mapping for one or more packages')
    return native_install_cmd(names,info)


def native_exact_available(name, info):
    """Verify explicit substitutions against enabled native repositories."""
    return providers.exact_available(name,info,runner=providers._run)


def package_resolution(name, info, settings):
    """Installed wins over preference. Never substitute unconfigured repositories."""
    if name == 'lerd':
        return ('installed' if installed(name, info['family']) else 'available' if available(name,info) else 'unavailable', 'lerd')
    if name.startswith('ai-'):
        return ('installed' if installed(name, info['family']) else 'available' if available(name,info) else 'unavailable', 'ai')
    if installed(name,info['family']):
        return ('installed',info.get('manager') or 'native')
    if info.get('desktop') and flatpak_installed(name):
        return ('installed','flatpak')
    prefer_flatpak = settings.get('AUTOMATION_PREFER_FLATPAK','false').lower() in TRUE
    if prefer_flatpak and info.get('desktop') and flatpak_available(name):
        return ('available','flatpak')
    if available(name,info):
        if settings.get('AUTOMATION_PREFER_SHELLY','false').lower() in TRUE and info['family']=='arch' and shutil.which('shelly') and name!='shelly':
            return ('available','shelly-native')
        return ('available',info['manager'])
    if settings.get('AUTOMATION_ENABLE_AUR','false').lower() in TRUE and info['family']=='arch':
        matches=sources.search_exact(name,info)
        if matches:return ('available',matches[0]['source'])
    if info.get('desktop') and flatpak_available(name):
        return ('available','flatpak')
    return ('unavailable','no-compatible-source')

def select_interactive(entries, info, settings=None, *, prompt_profile=False):
    """Category and package toggles. Cancelled UI never returns a mutation plan."""
    settings=settings or {}
    print('Setup wizard: review profile, development stack, categories, packages and final plan.')
    profile=settings.get('AUTOMATION_PROFILE','default')
    if sys.stdin.isatty() and (prompt_profile or not settings.get('AUTOMATION_PROFILE')):
        if shutil.which('gum'):
            choice=subprocess.run(['gum','choose','--header=Select installation profile',
                                   'default','developer','minimal','custom'],capture_output=True,text=True)
            if choice.returncode:raise KeyboardInterrupt('Profile selection cancelled')
            profile=choice.stdout.strip()
        else:
            print('Profiles: 1) Default  2) Developer  3) Minimal  4) Custom (no defaults)')
            answer=input('Profile [1]: ').strip()
            profile={'':'default','1':'default','2':'developer','3':'minimal','4':'custom'}.get(answer)
            if not profile:raise ValueError('Invalid profile selection')
        if profile not in ('default','developer','minimal','custom'):raise ValueError('Invalid profile selection')
    # Ask for the development stack before package checkboxes. Showing PHP,
    # MariaDB and web-server choices when Lerd is selected is misleading.
    can_lerd=any(x['id']=='lerd' for x in entries) and not lerd_compat(info) and info.get('desktop') and settings.get('AUTOMATION_LERD','true').lower() in TRUE
    use_lerd=False
    if can_lerd and sys.stdin.isatty():
        if shutil.which('gum'):
            result=subprocess.run(['gum','choose','--header=Local development stack','Lerd-managed (recommended)','Standalone services (manual selection)'],capture_output=True,text=True)
            if result.returncode: raise KeyboardInterrupt('Local development selection cancelled')
            use_lerd=result.stdout.strip()=='Lerd-managed (recommended)'
        else:
            use_lerd=input('Use Lerd-managed local development stack instead of standalone PHP/DB/web servers? [Y/n]: ').strip().lower() not in ('n','no')
    if use_lerd:
        print('Using Lerd: standalone PHP, databases, cache, Composer, and web servers are hidden.', flush=True)
        entries=[x for x in entries if x['id'] not in catalog.LERD_MANAGED and x['id']!='lerd']
    else:
        entries=[x for x in entries if x['id']!='lerd']
    all_names = [x['id'] for x in entries]
    default = [x['id'] for x in entries if x.get('default') and (
        profile=='default' or
        profile=='minimal' and x['id'] in ('curl','git','wget','unzip','python3') or
        profile=='developer' and x['category'] in ('Developer Tools','Essential System Utilities','Git and Version Control','Containers and Virtualization'))]
    if use_lerd:default.append('lerd')
    if not shutil.which('gum') and sys.stdin.isatty():
        print('Tip: install Gum once using `bash setup.sh prerequisites install --with-ui`; text menus remain available.', flush=True)
    if not sys.stdin.isatty():
        return profile,default
    categories = list(dict.fromkeys(x['category'] for x in entries))
    if shutil.which('gum'):
        cats = subprocess.run(['gum', 'choose', '--no-limit', '--height=15',
                               '--header=Choose categories (Space toggles, Enter continues)',
                               '--selected='+','.join(categories), *categories],
                              capture_output=True, text=True)
        if cats.returncode: raise KeyboardInterrupt('Category selection cancelled')
        selected_cats = set(cats.stdout.splitlines())
        choices = [e for e in entries if e['category'] in selected_cats]
        if not choices: return profile,[]
        # Use descriptions that show actual installed/missing/availability and source.
        display = {}
        print('Checking installed package status for checklist...',flush=True)
        for ci,row in enumerate(choices,1):
            progress.step(ci,len(choices),row['id'])
            name = row['id']
            status = 'installed' if installed(name,info['family']) else 'check during plan'
            display[f'{name}  [{status}]'] = name
        selected_display = ','.join(label for label,name in display.items() if name in default)
        result = subprocess.run(['gum','choose','--no-limit','--height=18',
                                 '--header=Choose packages (Space toggles, Enter continues)',
                                 '--selected='+selected_display, *display],
                                capture_output=True,text=True)
        if result.returncode: raise KeyboardInterrupt('Selection cancelled')
        return profile,[display[x] for x in result.stdout.splitlines() if x in display] + (['lerd'] if use_lerd else [])
    chosen = set(default)
    print('Category selections ("cat N" toggles all entries in that category):')
    for idx, category in enumerate(categories,1):
        print(f'  {idx:2}. {category}')
    print('Default packages are selected. Toggle with package numbers; all/none/done are supported.')
    print('Checking installed package status for checklist...',flush=True)
    for idx,row in enumerate(entries,1):
        progress.step(idx,len(entries),row['id'])
        status = 'installed' if installed(row['id'],info['family']) else 'check in plan'
        print(f'{idx:2}. [{"x" if row["id"] in chosen else " "}] {row["id"]:30} {status:17} {row["category"]}')
    while True:
        answer = input('Selection > ').strip().lower()
        if answer in ('','done'): break
        if answer == 'all': chosen.update(all_names); continue
        if answer == 'none': chosen.clear(); continue
        if answer.startswith('cat '):
            try:
                idx = int(answer.split()[1])-1
                category = categories[idx] if idx >= 0 else None
                if category is None: raise ValueError
                names={e['id'] for e in entries if e['category']==category}
                if names <= chosen: chosen -= names
                else: chosen |= names
            except (IndexError,ValueError): print('Invalid category number')
            continue
        try:
            for token in re.split(r'[,\s]+', answer):
                index = int(token)
                if not 1 <= index <= len(entries): raise ValueError
                name = entries[index-1]['id']
                if name in chosen: chosen.remove(name)
                else: chosen.add(name)
        except ValueError:
            print('Use package numbers, cat N, all, none, or done')
    return profile,[name for name in all_names if name in chosen] + (['lerd'] if use_lerd else [])


def conflicts():
    result = {}
    for port in (80, 443, 5300, 3306, 6379):
        s = socket.socket()
        try:
            result[port] = s.connect_ex(('127.0.0.1', port)) == 0
        except OSError:
            result[port] = False
        finally:
            s.close()
    return result


def lerd_action(args, info):
    action = args.action or 'status'
    cmd = shutil.which('lerd') or str(Path.home()/'.local/bin/lerd')
    exists = Path(cmd).is_file() or shutil.which('lerd') is not None
    reasons = lerd_compat(info)
    if action in ('status', 'check', 'doctor'):
        print('Lerd installed:', exists)
        print('Lerd compatible:', not reasons)
        for reason in reasons: print(' -', reason)
        print('Ports (TCP listeners, not proof of conflict):', conflicts())
        if exists:
            # The official doctor command is more comprehensive than `status`.
            return run([cmd, 'doctor' if action in ('doctor','check') else 'status'], timeout=120)
        return 0
    if action in ('desktop-status','desktop-install','desktop-update'):
        if not shutil.which('flatpak'):
            print('Lerd Desktop requires Flatpak installed on the desktop host.', file=sys.stderr)
            return 3
        if action=='desktop-install':
            if not info['desktop'] or info['container']:
                print('Lerd Desktop requires a local graphical host session.', file=sys.stderr)
                return 3
            if not approved(args,'Install official Lerd Desktop from lerd.sh?'):return 4
            return run(['flatpak','install','--user',lerd_ops.FLATPAK_REF],mutate=True,args=args,timeout=900)
        # Do not infer an ID from the string "Lerd" or update every Flatpak.
        try:
            application_id=lerd_ops.official_desktop_id()
        except (ValueError, OSError, TimeoutError) as exc:
            print('Could not verify official Lerd Desktop Flatpak identity:',str(exc),file=sys.stderr)
            return 3
        is_installed=lerd_ops.desktop_installed(application_id)
        print('Official Lerd Desktop app ID:',application_id)
        print('Installed for current user:',is_installed)
        if action=='desktop-status': return 0
        if not is_installed:
            print('Desktop app is not installed for this user.',file=sys.stderr)
            return 3
        if not info['desktop'] or info['container']:
            print('Desktop update requires a graphical host session.',file=sys.stderr)
            return 3
        if not approved(args,'Update only the verified Lerd Desktop Flatpak?'):return 4
        return run(['flatpak','update','--user',application_id],mutate=True,args=args,timeout=900)
    if action == 'migrate':
        print('Existing runtime commands:', {p: shutil.which(p) for p in ('php','mariadb','mysqld','nginx','apache2','redis-server','composer')})
        print('TCP listeners:', conflicts())
        print('Migration is assessment-only. No services stopped, data moved or deleted.')
        return 0
    if action == 'install':
        if exists:
            print('Lerd already installed; use lerd update or repair.')
            return 0
        if reasons:
            print('Lerd installation blocked:', '; '.join(reasons), file=sys.stderr)
            return 3
        if os.geteuid() == 0:
            print('Run Lerd as the desktop user, not root.', file=sys.stderr)
            return 3
        if not approved(args, 'Download and run Lerd official installer from lerd.sh?'):
            return 4
        print('Official installer: https://lerd.sh/install.sh (TLS transport, no local pinned signature).')
        if args.dry_run: return 0
        # Keep the downloaded installer outside source and execute only after consent.
        with tempfile.TemporaryDirectory(prefix='automation-lerd-') as td:
            dest = Path(td)/'install.sh'
            req = urllib.request.Request('https://lerd.sh/install.sh', headers={'User-Agent': 'LinuxAutomationToolkit/1'})
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.url != 'https://lerd.sh/install.sh':
                    raise ValueError('Unexpected installer redirect; refusing execution')
                content = response.read(2_000_001)
            if len(content) > 2_000_000 or not content.startswith(b'#!'):
                raise ValueError('Unexpected installer content')
            dest.write_bytes(content); dest.chmod(0o700)
            return run(['bash', str(dest)], mutate=True, args=args, timeout=1800)
    if not exists:
        print('Lerd not installed. Use: bash setup.sh lerd install', file=sys.stderr)
        return 3
    if action == 'uninstall':
        print('Warning: the official Lerd uninstaller removes its services and binary. Back up configuration first.')
        return run([cmd,'uninstall'],mutate=True,args=args,timeout=600) if approved(args,'Run official lerd uninstall?') else 4
    if action in ('update','repair'):
        return run([cmd, 'update' if action == 'update' else 'install'], mutate=True, args=args, timeout=1800) if approved(args, f'Run lerd {action}?') else 4
    if action in ('start','stop','restart'):
        if not approved(args, f'Run official lerd {action}?'): return 4
        return run([cmd, action], mutate=True, args=args,timeout=180)
    if action in ('php:rebuild','php:update'):
        if args.value and not re.fullmatch(r'(?:[5-9]\.[0-9]{1,2})',args.value):
            print('PHP version must be a major.minor string such as 8.5',file=sys.stderr)
            return 2
        if not approved(args,f'Run official lerd {action}?'):return 4
        return run([cmd, action, *([args.value] if args.value else [])],mutate=True,args=args,timeout=3600)
    if action in ('site:doctor',):
        return run([cmd,action],timeout=120)
    if action in ('dashboard','php:list','logs'):
        return run([cmd, action], timeout=90)
    if action in ('use','park','link','isolate','service'):
        if action in ('use','isolate') and (not args.value or not re.fullmatch(r'\d+\.\d+', args.value)):
            return 2
        if action == 'service':
            if args.value not in ('list','status','start','stop','restart','preset'):
                print('Supported service actions: list, status, start, stop, restart, preset')
                return 2
            service = getattr(args,'service_name',None)
            if args.value in ('status','start','stop','restart'):
                if not service or not re.fullmatch(r'[a-zA-Z0-9_-]+',service):
                    print('Provide a safe service name, e.g. lerd service status redis',file=sys.stderr)
                    return 2
            if args.value == 'preset' and service and not re.fullmatch(r'[a-zA-Z0-9_-]+',service):
                return 2
            mutation=args.value in ('start','stop','restart') or (args.value=='preset' and bool(service))
            if mutation and not approved(args,f'Run lerd service {args.value} {service}?'):return 4
            return run([cmd,'service',args.value,*([service] if service else [])],mutate=mutation,args=args,timeout=1200 if mutation else 90)
        if action in ('park','link','isolate','use') and not approved(args, f'Run lerd {action}?'): return 4
        return run([cmd, action, *([args.value] if args.value else [])], mutate=action not in ('service',), args=args)
    print('Unsupported Lerd action; see lerd --help', file=sys.stderr)
    return 2


def _replacements(args):
    overrides = {}
    for value in getattr(args,'replace',None) or []:
        if '=' not in value: raise ValueError('Replacement must be REQUESTED=NATIVE_PACKAGE')
        requested, replacement = value.split('=',1)
        discovery.validate_term(requested)
        discovery.validate_term(replacement)
        if requested in overrides: raise ValueError('Duplicate replacement: '+requested)
        overrides[requested] = replacement
    return overrides


def _source_overrides(args):
    result={}
    for value in getattr(args,'source',None) or []:
        if '=' not in value:raise ValueError('--source must be REQUESTED=HELPER')
        name,helper=value.split('=',1)
        discovery.validate_term(name)
        if helper not in sources.HELPERS:raise ValueError('Invalid AUR helper: '+helper)
        if name in result:raise ValueError('Duplicate AUR source: '+name)
        result[name]=helper
    return result


def _recommend(name, info, settings):
    if settings.get('AUTOMATION_AUTO_SEARCH','true').lower() not in TRUE: return []
    limit = max(1,min(10,int(settings.get('AUTOMATION_SEARCH_LIMIT','5'))))
    return discovery.suggest(name,info,limit=limit,
                             enable_aur=settings.get('AUTOMATION_ENABLE_AUR','false').lower() in TRUE)


def packages_action(args, info, settings):
    if getattr(args, 'output', None) and args.action in ('install', 'repair'):
        raise ValueError('--output is only valid for read-only package plans')
    entries = package_catalog(info)
    profile = settings.get('AUTOMATION_PROFILE', 'default')
    if profile not in ('default','minimal','developer'): raise ValueError('Unknown package profile: '+profile)
    selected = [x['id'] for x in entries if x.get('default', False) and (
        profile == 'default' or (profile == 'minimal' and x['id'] in ('curl','git','wget','unzip','python3')) or
        (profile == 'developer' and x['category'] in ('Developer Tools','Essential System Utilities','Git and Version Control','Lerd.sh Development Environment','Containers and Virtualization')))]
    selected_override = args.select or ([settings['AUTOMATION_SELECTED_PACKAGES']] if settings.get('AUTOMATION_SELECTED_PACKAGES') else None)
    if selected_override:
        selected = [x.strip() for raw in selected_override for x in raw.split(',') if x.strip()]
    elif args.interactive or (args.command == 'packages' and args.action == 'install' and not args.yes and sys.stdin.isatty()):
        profile,selected = select_interactive(entries, info, settings,prompt_profile=getattr(args,'choose_profile',False))
    exclude = {x.strip() for raw in (([settings['AUTOMATION_EXCLUDED_PACKAGES']] if settings.get('AUTOMATION_EXCLUDED_PACKAGES') else []) + (args.exclude or [])) for x in raw.split(',')}
    selected = list(dict.fromkeys(x for x in selected if x not in exclude))
    # A supported, selected Lerd installation owns the local PHP/DB/cache/web
    # services. Do not provision a parallel host stack by default; user data and
    # preexisting services are never touched. Non-overlapping apps stay selected.
    lerd_selected = 'lerd' in selected and settings.get('AUTOMATION_LERD','true').lower() in TRUE
    lerd_supported = lerd_selected and (installed('lerd',info['family']) or not lerd_compat(info))
    overlapping = [name for name in selected if name in catalog.LERD_MANAGED]
    if lerd_supported and overlapping and not getattr(args,'allow_standalone_dev',False):
        selected = [name for name in selected if name not in catalog.LERD_MANAGED]
        print('Managed by Lerd — standalone installation suppressed:', ', '.join(overlapping))
        print('Lerd service versions can be configured independently using its supported CLI.')
    elif lerd_supported and overlapping:
        print('WARNING: explicit standalone-dev override may conflict with Lerd ports and services.')
    elif lerd_selected and overlapping:
        print('Lerd is incompatible here; retaining separately selected development services.')
    known = {x['id'] for x in entries}
    unknown = set(selected) - known
    if unknown:
        if not selected_override or any(x.startswith('ai-') for x in unknown):
            print('Unrecognized packages in profile:',sorted(unknown),file=sys.stderr)
            return 2
        try:
            for name in unknown: discovery.validate_term(name)
        except ValueError as exc:
            print('Invalid custom package:',exc,file=sys.stderr)
            return 2
        print('Custom packages will be checked against enabled native repositories:',', '.join(sorted(unknown)))
    if not selected_override and 'lerd' in selected and (not info.get('desktop') or lerd_compat(info)):
        selected = [x for x in selected if x != 'lerd']
        print('Lerd excluded from defaults: desktop/systemd/host compatibility not verified.')
    replacements = _replacements(args)
    source_overrides = _source_overrides(args)
    if set(source_overrides)-set(selected):
        raise ValueError('Source override specified for unselected package')
    if set(replacements)-set(selected):
        raise ValueError('Replacement specified for unselected package')
    results = []
    print(f'Checking {len(selected)} selected components across compatible sources...', flush=True)
    for check_index, name in enumerate(selected, 1):
        progress.step(check_index,len(selected),name)
        if name == 'lerd' and settings.get('AUTOMATION_LERD','true').lower() not in TRUE: continue
        present = installed(name,info['family'])
        source = info.get('manager') or 'unsupported'
        # A local installed-state check never needs a remote repository query.
        if present:
            actual = name
        else:
            with progress.waiting(f'Checking configured native repository for {name}'):
                actual = package_native_name(name,info['family'],info)
        state = 'installed' if present else 'unavailable'
        if name in ('lerd',) or name.startswith('ai-'):
            source = 'lerd' if name=='lerd' else 'ai'
            actual = name
            state = 'installed' if present else ('managed' if name.startswith('ai-') and available(name,info) else 'available' if name == 'lerd' and available(name,info) else 'unavailable')
        elif present:
            state='installed'
            if info['family']=='arch':
                foreign=_query(['pacman','-Qm',name],timeout=5)
                if foreign is not None and foreign.returncode==0:source='foreign/AUR'
        elif info.get('desktop') and flatpak_installed(name):
            source='flatpak'; actual=catalog.FLATPAKS[name]; state='installed'
        elif name in replacements:
            actual=replacements[name]
            if not native_exact_available(actual,info):
                print(f'Replacement {name}={actual} is not verified in enabled native repositories.', file=sys.stderr)
                return 3
            source=info['manager'];state='installed' if installed(actual,info['family']) else 'available'
        else:
            # Never trust a positive availability result without a curated mapping.
            # A curated/dynamic candidate is NOT availability. Require an exact
            # match in configured native metadata (same invariant as Package execution).
            native_ok=(bool(actual) and available(name,info)) or (name in unknown and native_exact_available(name,info))
            if native_ok:
                verified_native=providers.choose_native(name,info)
                actual=verified_native or (name if name in unknown else actual)
            flatpak_ok=info.get('desktop') and flatpak_available(name)
            prefer_flatpak=settings.get('AUTOMATION_PREFER_FLATPAK','false').lower() in TRUE
            if prefer_flatpak and flatpak_ok:
                source='flatpak';actual=catalog.FLATPAKS[name];state='available'
                if name in catalog.COMMUNITY_FLATPAKS:
                    print('Note: VS Code Flatpak is an unofficial, unverified community repackaging.')
            elif native_ok:
                state='installed' if installed(actual,info['family']) else 'available'
                if (info['family']=='arch' and settings.get('AUTOMATION_PREFER_SHELLY','false').lower() in TRUE
                        and shutil.which('shelly') and name!='shelly'):
                    source='shelly-native'
            elif flatpak_ok and name not in catalog.COMMUNITY_FLATPAKS:
                source='flatpak';actual=catalog.FLATPAKS[name];state='available'
        # Search ALL installed Arch AUR frontends, including Shelly, regardless
        # of whether AUR installation has been authorized. Discovery is read-only.
        aur_matches=[]
        if state=='unavailable' and info['family']=='arch':
            with progress.waiting(f'Searching configured AUR frontends for {name}'):
                aur_matches=sources.search_exact(name,info)
            enabled=settings.get('AUTOMATION_ENABLE_AUR','false').lower() in TRUE or getattr(args,'enable_aur',False)
            preferred=source_overrides.get(name)
            if preferred and not any(m['source']==preferred for m in aur_matches):
                print(f'{name}: source {preferred} did not verify an exact match.',file=sys.stderr)
                return 3
            if aur_matches and enabled:
                choice=next((m for m in aur_matches if m['source']==preferred),aur_matches[0])
                source=choice['source'];actual=name;state='available'
            elif preferred:
                raise ValueError('AUR sources require --enable-aur and an explicit package selection')
        suggestion=[]
        if state=='unavailable' and name!='lerd' and not name.startswith('ai-'):
            suggestion=_recommend(name,info,settings)
        results.append({'name':name,'status':state,'source':source if state!='unavailable' else 'no-compatible-source',
                        'actual':actual,'suggestions':suggestion,'aur_matches':aur_matches})
    for row in results:
        print(f'{row["name"]:33} {row["status"]:12} {row["source"]}')
        if row['status']=='managed':
            print('  Managed separately: bash setup.sh ai BACKEND status|install')
        if row['status']=='unavailable':
            if row.get('aur_matches'):
                print('  Exact-name AUR candidates (community recipes; requires --enable-aur):')
                for candidate in row['aur_matches']:
                    print(f'    {candidate["package"]} via {candidate["source"]} — inspect PKGBUILD and publisher before installing')
            if row['suggestions']:
                print('  Recommended name-based suggestions (not confirmed equivalent applications):')
                for i,s in enumerate(row['suggestions'],1):
                    print(f'    {i}. {s["package"]:<32} {s["source"]:<12} {s["confidence"]:3}% name match [{s.get("identity","unverified")}] {s.get("description","")[:60]}')
                print(f'  To choose a verified native alternative: --replace {row["name"]}=PACKAGE')
            else:
                if not row.get('aur_matches'):
                    print('  No verified repository matches; check enabled sources, architecture and spelling.')
    if getattr(args,'output',None) and args.action not in ('install','repair'):
        if args.action == 'export' and not args.dry_run:
            output=workflows.write_json(Path(args.output),workflows.plan_data(info,results,profile=profile))
            print('Machine-readable plan exported:',output)
        else:
            print('Plan is read-only: no output file written. Use packages export --output FILE explicitly.')
    if args.action not in ('install','repair'):
        host=providers.capability(info)
        for warning in host['warnings']: print('Compatibility warning:',warning)
        print('Plan only; no packages changed. Use packages install --yes to execute.')
        return 0
    # A --yes confirmation covers requested packages, NOT fuzzy replacements.
    # On interactive terminals offer a second explicit choice; dry-run never prompts.
    if not args.dry_run and not args.non_interactive and not args.yes and sys.stdin.isatty():
        for row in results:
            candidates=[s for s in row['suggestions'] if s['source']=='native']
            if row['status']=='unavailable' and candidates:
                print(f'{row["name"]}: 0) skip (default)')
                for i,s in enumerate(candidates,1):
                    print(f'  {i}) {s["package"]} [{s.get("identity","identity unverified")}] — {s.get("description", "")[:50]}')
                answer=input('Choose native alternative by number (never automatic): ').strip()
                if answer and answer!='0':
                    if not answer.isdigit() or not 1<=int(answer)<=len(candidates):
                        print('Invalid replacement index; skipped.');continue
                    actual=candidates[int(answer)-1]['package']
                    if native_exact_available(actual,info) and approved(args,f'Use {actual} instead of {row["name"]}?'):
                        row.update(status='available',source=info['manager'],actual=actual)
    missing=[r for r in results if r['status']=='available']
    print('Installable missing:',len(missing),'Unavailable:',sum(r['status']=='unavailable' for r in results))
    counts=wizard.preview(results)
    print('Review: selected={total} installed={installed} missing={available} managed={managed} unavailable={unavailable}'.format(**counts))
    if not missing:
        return 5 if any(r['status']=='unavailable' for r in results) else 0
    host=providers.capability(info)
    if not host['host_install_allowed'] and not args.dry_run:
        print('Host package changes blocked: '+'; '.join(host['warnings']),file=sys.stderr)
        return 3
    if not approved(args,f'Install {len(missing)} missing components?'): return 4
    if not args.dry_run:
        for row in missing:
            if row['source'] in (info['manager'],'shelly-native') and not native_exact_available(row['actual'],info):
                print('Package no longer verified in configured native repositories:',row['actual'],file=sys.stderr)
                return 5
    if getattr(args, 'initialize_config', False) and not args.dry_run:
        configuration.ensure(ROOT, config_file, validate_settings)
    session = None if args.dry_run else journal.new_session()
    journal_dir=settings.get('AUTOMATION_STATE_DIR','')
    if session:
        journal.write('started',directory=journal_dir,session=session,packages=[r['name'] for r in missing])
    failures=0
    native=[]
    native_rows=[]
    # Package manager transactions are batched and never run concurrently.
    for row in missing:
        name,source,actual=row['name'],row['source'],row['actual']
        if source==info.get('manager'):
            native.append(actual);native_rows.append(row);continue
        if name=='lerd':
            rc=lerd_action(arg_copy(args,action='install'),info)
            if session: journal.write('action',directory=journal_dir,session=session,packages=[name],source='lerd',result=rc)
            if session and not rc and installed('lerd',info['family']):
                journal.record_ownership(name,'lerd','lerd',directory=journal_dir,verified=True)
            if rc: failures+=1
            continue
        if source=='ai':
            print(f'AI {name}: use `bash setup.sh ai` to configure backend explicitly; not auto-installed.')
            continue
        if source=='flatpak':
            cmd=['flatpak','install',flatpak_scope(name) or '--user','--noninteractive','flathub',actual]
        elif source=='shelly-native':
            if info['family']!='arch':raise ValueError('Shelly native installs require Arch')
            cmd=['shelly','install',actual]
        elif source in sources.HELPERS:
            if info['family']!='arch' or os.geteuid()==0:
                print('AUR helpers require an unprivileged Arch-family user',file=sys.stderr);failures+=1;continue
            print(f'AUR security notice: review the {actual} build recipe, sources, and maintainer using {source}.', flush=True)
            cmd=sources.helper_install_cmd(source,actual)
        else:
            print('Unsupported source for:',name,file=sys.stderr);failures+=1;continue
        rc=run(cmd,mutate=True,args=args,timeout=int(settings.get('AUTOMATION_PACKAGE_TIMEOUT','900')))
        if session: journal.write('action',directory=journal_dir,session=session,packages=[name],source=source,result=rc)
        if session and not rc and (flatpak_installed(name) if source=='flatpak' else installed(actual,info['family'])):
            journal.record_ownership(name,actual,source,directory=journal_dir,verified=True)
        elif session and not rc:
            print('WARNING: installation completed but post-install ownership not verified:',name)
        if rc:failures+=1
    if native:
        rc=run(native_install_cmd(native,info),mutate=True,args=args,
               timeout=int(settings.get('AUTOMATION_PACKAGE_TIMEOUT','900')),retries=int(settings.get('AUTOMATION_RETRIES','2')))
        # A successful batch return code is not proof every package was
        # installed. Confirm each package individually before claiming it.
        for row in native_rows:
            name,actual=row['name'],row['actual']
            verified=installed(actual,info['family'])
            if session:
                journal.write('action',directory=journal_dir,session=session,packages=[name],source=info['manager'],result=0 if verified else (rc or 1))
                if verified:journal.record_ownership(name,actual,info['manager'],directory=journal_dir,verified=True)
                elif not rc:print('WARNING: post-install verification incomplete:',name)
        if rc:failures+=len(native)
        elif session and any(not installed(r['actual'],info['family']) for r in native_rows):
            failures+=sum(not installed(r['actual'],info['family']) for r in native_rows)
    unavailable=sum(r['status']=='unavailable' for r in results)
    print(f'Summary: selected={len(results)} missing={len(missing)} unavailable={unavailable} failed={failures}')
    if session:
        journal.write('failed' if failures else 'partial' if unavailable else 'finished',
                      directory=journal_dir,session=session,result=1 if failures else 5 if unavailable else 0)
    return 1 if failures else 5 if unavailable else 0


def arg_copy(args, **changes):
    data = vars(args).copy(); data.update(changes)
    return argparse.Namespace(**data)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0]=='laravel':
        if len(argv)<2 or argv[1] not in ('provision','deploy'):raise ValueError('laravel provision|deploy [options]')
        return subprocess.run(['bash',str(ROOT/'laravel'/('laravel-'+argv[1]+'.sh')),*argv[2:]]).returncode
    if argv and argv[0] in ('configuration', 'webui'):
        if argv[0] == 'configuration':
            import recipes
            return recipes.main(argv[1:])
        import webui
        return webui.main(argv[1:])
    p = argparse.ArgumentParser(description='Linux Automation Toolkit. Mutating commands require confirmation or --yes.')
    p.add_argument('--auto-prereqs', action='store_true', help='setup.sh only: check/bootstrap prerequisites before installation')
    p.add_argument('--check', action='store_true', help='read-only doctor check')
    p.add_argument('--dry-run', action='store_true', help='print proposed commands, do not install')
    p.add_argument('--install', action='store_true', help='install selected default profile')
    p.add_argument('--update', action='store_true', help='update Lerd only (not system-wide upgrade)')
    p.add_argument('--repair', action='store_true', help='repair Lerd only')
    p.add_argument('--uninstall', action='store_true', help='report removal options, never remove packages implicitly')
    p.add_argument('--profile', choices=['default', 'minimal', 'developer'], help='package selection profile')
    p.add_argument('--saved-profile', metavar='NAME', help='load validated profile from private state directory')
    p.add_argument('--output', metavar='FILE', help='write plan, offline manifest, or other requested output')
    p.add_argument('--cache-dir', metavar='DIRECTORY', help='read-only offline artifact directory')
    p.add_argument('--artifact', action='append', metavar='PACKAGE=FILENAME', help='explicit local artifact for offline manifest')
    p.add_argument('--no-lerd', action='store_true')
    p.add_argument('--allow-standalone-dev', action='store_true', help='explicitly permit overlapping PHP/DB/web services alongside Lerd')
    p.add_argument('--enable-aur', action='store_true', help='explicitly allow reviewed AUR build recipes on Arch')
    p.add_argument('--source', action='append', metavar='REQUESTED=HELPER', help='select a verified AUR source: shelly, paru, yay, pamac')
    p.add_argument('--refresh-cache', action='store_true', help='discard short-lived repository metadata cache')
    p.add_argument('--prefer-flatpak', action='store_true')
    p.add_argument('--prefer-shelly', action='store_true', help='Arch only, use installed Shelly CLI for native packages')
    p.add_argument('--no-auto-search', action='store_true', help='skip read-only candidate discovery')
    p.add_argument('--replace', action='append', metavar='REQUESTED=PACKAGE', help='explicit, repository-verified native replacement')
    p.add_argument('--yes', '-y', action='store_true', help='approve selected installation actions')
    p.add_argument('--non-interactive', action='store_true')
    p.add_argument('--interactive', action='store_true')
    p.add_argument('--name',help='Explicit developer Git display name')
    p.add_argument('--email',help='Explicit developer Git email')
    p.add_argument('--shell',choices=['bash','zsh','fish'],help='Explicit shell for developer integration')
    p.add_argument('--identity-file',help='Existing private SSH identity; never generated implicitly')
    p.add_argument('--destination',help='New directory for an explicitly requested repository clone')
    p.add_argument('--ssh-provider',choices=['github','gitlab'],default='github',help='Explicit public SSH authentication test target')
    p.add_argument('--ssh-host',help='Exact SSH connection alias for a separate toolkit config')
    p.add_argument('--hostname',help='Exact SSH server hostname')
    p.add_argument('--ssh-user',help='Explicit SSH login user')
    p.add_argument('--current-sha256',help='Expected current Git configuration SHA-256 for legacy backup import')
    p.add_argument('--banner',choices=['none','fastfetch','neofetch'],default='none',help='Optional interactive shell banner; never installs a tool')
    p.add_argument('--transport',choices=['ssh','https'],help='Explicit GitHub transport rewrite choice')
    p.add_argument('--use-toolkit-agent',action='store_true',help='Connect new shells to the existing toolkit socket only when no agent is selected')
    p.add_argument('--fish-greeting',choices=['keep','off'],default='keep')
    p.add_argument('--migrate-legacy',action='store_true',help='Replace exact known legacy shell blocks after backup; ambiguous content is refused')
    p.add_argument('--select', action='append', metavar='ID[,ID]', help='explicit package IDs, or configuration/projects for checklist automate')
    p.add_argument('--exclude', action='append', metavar='PKG[,PKG]', help='exclude from default selection')
    p.add_argument('command', nargs='?', choices=['packages','wizard','lerd','ai','services','doctor','config','recovery','inventory','profiles','offline','projects','providers','dashboard','desktop','developer','checklist','configuration','webui','laravel'])
    p.add_argument('action', nargs='?', help='install|status|repair|...')
    p.add_argument('value', nargs='?')
    args, extras = p.parse_known_args(argv)
    if args.action in ('plan','search','status','check','list') and any((args.install,args.repair,args.update,args.uninstall)):
        p.error('Read-only subcommands cannot be combined with mutating action flags')
    # A global check always wins over any mutating subcommand, including exports.
    if args.check:
        args.command, args.action, args.value = 'doctor', None, None
        args.refresh_cache = False
        extras = []
    if args.command in ('configuration', 'webui','laravel'):
        p.error('Place '+args.command+' first, followed by its action/options; no package action was run')
    if args.command == 'ai':
        return subprocess.run([sys.executable, str(ROOT/'ai/manager.py'), *( [args.action] if args.action else [] ),
                               *( [args.value] if args.value else [] ), *extras,
                               *(['--yes'] if args.yes else []), *(['--dry-run'] if args.dry_run else [])]).returncode
    if extras:
        if args.command == 'lerd' and args.action == 'service' and len(extras) == 1:
            args.service_name = extras[0]
        elif args.command == 'projects' and args.action == 'init' and len(extras) == 1:
            args.project_target = extras[0]
        else:
            p.error('unknown arguments: ' + ' '.join(extras))
    settings = config(args)
    args.initialize_config = True
    cache.PERSIST = False
    if args.dry_run and (args.command in ('profiles','offline','dashboard','recovery') or args.output):
        print('Dry run: no configuration, export, recovery or output files written.')
        return 0
    if args.refresh_cache and not args.dry_run and args.command == 'packages' and args.action == 'install' and args.yes:
        print('Cleared cached repository metadata:',cache.clear(),flush=True)
        discovery.native_search.cache_clear()
    if settings.get('AUTOMATION_NONINTERACTIVE','false').lower() in TRUE: args.non_interactive = True
    info = platform_info()
    if args.command=='checklist':
        import checklist
        return checklist.main(args,approved,state=settings.get('AUTOMATION_STATE_DIR',''),root=ROOT,settings=settings)
    if args.command == 'desktop':
        import desktop
        return desktop.main(args, approved)
    if args.command=='developer':
        import developer
        args.developer_state=settings.get('AUTOMATION_STATE_DIR','')
        return developer.main(args,approved)
    if args.command == 'profiles':
        action=args.action or 'list'
        state=settings.get('AUTOMATION_STATE_DIR','')
        if action=='list':
            print(json.dumps({'saved_profiles':workflows.list_profiles(state)},indent=2))
        elif action=='export':
            if not args.value: p.error('profiles export FILE')
            exported=workflows.profile_data(settings)
            if args.select: exported['settings']['AUTOMATION_SELECTED_PACKAGES']=','.join(args.select)
            if args.exclude: exported['settings']['AUTOMATION_EXCLUDED_PACKAGES']=','.join(args.exclude)
            workflows.validate_profile(exported,validate_settings)
            print('Exported:',workflows.write_json(Path(args.value),exported,private=True))
        elif action=='import':
            if not args.value: p.error('profiles import FILE')
            print('Imported:',workflows.import_profile(args.value,state,validate_settings))
        elif action=='show':
            if not args.value: p.error('profiles show NAME')
            print(json.dumps(workflows.profile_data(workflows.saved_profile(args.value,state,validate_settings)),indent=2))
        else: p.error('profiles list|export FILE|import FILE|show NAME')
        return 0
    if args.command == 'offline':
        if args.action=='prepare':
            if not args.value or not args.output or not args.cache_dir:
                p.error('offline prepare PLAN.json --cache-dir DIRECTORY --output MANIFEST.json [--artifact PACKAGE=FILENAME]')
            value=workflows.prepare_offline(args.value,args.cache_dir,args.output,args.artifact or [])
            print('Offline manifest created:',args.output,'verified artifacts:',sum(x['status']=='verified-local' for x in value['artifacts']))
            return 0
        if args.action=='verify':
            if not args.value or not args.cache_dir: p.error('offline verify MANIFEST.json --cache-dir DIRECTORY')
            result=workflows.verify_offline(args.value,args.cache_dir)
            print(json.dumps(result,indent=2))
            return 0 if result['ok'] else 5
        p.error('offline prepare|verify')
    if args.command == 'projects':
        if args.action == 'layout':
            target=args.value or settings.get('AUTOMATION_PROJECT_SITES_DIR') or str(Path.home()/'Documents/Project-Sites')
            result = bootstrap.layout(target, dry_run=True)
            print(json.dumps(result, indent=2))
            if not approved(args, 'Create the listed missing project directories?'): return 4
            if not args.dry_run: print(json.dumps(bootstrap.layout(target), indent=2))
            return 0
        if args.action!='init' or not args.value or not getattr(args,'project_target',None):
            p.error('projects init python|node DIRECTORY or projects layout DIRECTORY [--yes|--dry-run]')
        if not approved(args,'Create new project files at '+args.project_target+'?'): return 4
        result=bootstrap.create(args.value,args.project_target,dry_run=args.dry_run)
        print(json.dumps(result,indent=2))
        return 0
    if args.command == 'providers':
        if args.action not in ('validate','plan','install') or not args.value:
            p.error('providers validate|plan|install MANIFEST.json [--select name[,name]]')
        provider=extensions.read_provider(args.value)
        if args.action=='validate':
            print('Valid declarative provider:',provider['id'],'packages:',', '.join(sorted(provider['packages'])))
            return 0
        if not args.select: p.error('Provider plan/install needs explicit --select logical package names')
        names=[n.strip() for group in args.select for n in group.split(',') if n.strip()]
        native=extensions.resolve(provider,names,info['family'])
        print('Provider name mapping:',', '.join(f'{a} => {b}' for a,b in zip(names,native)))
        print('Native repository verification is required; this provider cannot add repos or execute commands.')
        return packages_action(arg_copy(args,command='packages',action=args.action,select=[','.join(native)]),info,settings)
    if args.command == 'dashboard':
        if args.action!='export' or not args.value: p.error('dashboard export REPORT.html')
        print('Created read-only local HTML report:',workflows.export_dashboard(args.value,settings.get('AUTOMATION_STATE_DIR','')))
        return 0
    if args.command == 'packages' and args.action == 'search':
        if not args.value: p.error('Usage: setup.sh packages search PACKAGE')
        discovery.validate_term(args.value)
        print(f'Package search: {args.value} on {info["family"]}; read-only, no changes',flush=True)
        with progress.waiting('Checking native repository and optional sources'):
            native=providers.choose_native(args.value,info)
            aur=sources.search_exact(args.value,info) if info['family']=='arch' else []
            flatpak=flatpak_scope(args.value) if info.get('desktop') else None
            suggestions=discovery.suggest(args.value,info,enable_aur=False)
        if native:print(f'  [verified exact native] {native} via {info["manager"]}')
        for match in aur:
            print(f'  [exact AUR name; community recipe] {match["package"]} via {match["source"]} (installation requires --enable-aur)')
        if flatpak:print(f'  [configured Flatpak app] {catalog.FLATPAKS[args.value]} ({flatpak}); verify publisher')
        for i,row in enumerate(suggestions,1):
            print(f'  [similar name {i}] {row["package"]:24} {row["source"]:12} {row["confidence"]}% — NOT verified equivalent')
        if not (native or aur or flatpak or suggestions):print('No verified matches or safe suggestions in configured sources.')
        return 0
    if args.command == 'inventory':
        print(json.dumps({'observed_toolkit_installs':journal.owned(directory=settings.get('AUTOMATION_STATE_DIR','')),
                          'note':'Inventory is observational; it does not authorize uninstallation.'},indent=2))
        return 0
    if args.command == 'recovery' and (args.action or 'status') == 'pending':
        print(json.dumps({'pending':journal.pending(directory=settings.get('AUTOMATION_STATE_DIR','')),
                          'note':'Review and manually rerun selected packages; no automatic replay.'},indent=2))
        return 0
    if args.command == 'recovery':
        if (args.action or 'status') != 'status':
            print('Recovery currently supports status only; rerun the original command after inspection.',file=sys.stderr)
            return 3
        print(json.dumps(journal.status(directory=settings.get('AUTOMATION_STATE_DIR','')),indent=2))
        return 0
    if args.command == 'config':
        if args.action == 'init':
            if not approved(args, 'Create/merge safe .env defaults, preserving existing values?'): return 4
            if args.dry_run:
                print('Dry run: would create/merge .env with safe defaults.')
                return 0
            print('Configuration ready:', configuration.ensure(ROOT, config_file, validate_settings))
            return 0
        if args.action not in (None, 'show'): p.error('config show|init')
        print(json.dumps({k: ('***' if any(s in k for s in ('PASSWORD','TOKEN','SECRET')) else v)
                          for k,v in settings.items()}, indent=2))
        return 0
    if args.uninstall:
        print('No automatic uninstallation. Existing software, services, models and data are preserved.')
        print('For Lerd, review `lerd uninstall` documentation; separate installer-owned AI units can be removed explicitly.')
        return 0
    if args.check or args.command == 'doctor' or args.command == 'services':
        print('[1/4] Detecting Linux distribution and session...', flush=True)
        print(json.dumps(info, indent=2))
        print('[2/4] Checking Lerd prerequisites...', flush=True)
        with progress.waiting('Lerd compatibility'):
            print('Lerd compatibility:', lerd_compat(info) or 'eligible; dependencies checked by official installer',flush=True)
        print('[3/4] Checking native package provider and available Arch frontends...',flush=True)
        print('Native package provider:',providers.capability(info),flush=True)
        if info['family']=='arch':print('Arch package frontends:', ['pacman',*sources.arch_sources(info)],flush=True)
        print('Optional UI:', 'Gum installed' if shutil.which('gum') else 'Gum missing; install with prerequisites --with-ui',flush=True)
        print('[4/4] Checking TCP listeners (80, 443, 5300, 3306, 6379)...',flush=True)
        with progress.waiting('TCP listener probe'):
            print('Relevant TCP listeners:', conflicts(),flush=True)
        if args.command == 'services': print('Use `bash setup.sh lerd status` for Lerd-managed services.')
        return 0
    if args.command == 'lerd' or args.update or args.repair:
        action = ('update' if args.update else 'repair' if args.repair else args.action)
        return lerd_action(arg_copy(args, action=action), info)
    if args.command == 'wizard':
        if not sys.stdin.isatty():
            print('Wizard requires interactive terminal; use packages plan/install --select for automation.',file=sys.stderr)
            return 3
        args.interactive=True
        args.choose_profile=not args.profile and not args.saved_profile
        args.command='packages'
        args.action='install'
    if args.install:
        args.action = 'install'
    elif args.command is None:
        if sys.stdin.isatty():
            args.action = 'install'
            args.interactive = True
            args.choose_profile=not args.profile and not args.saved_profile
        else:
            args.action = 'plan'
    return packages_action(args, info, settings)


if __name__ == '__main__':
    try:
        # Rootless shared lock prevents simultaneous setup processes.
        wants_write = any(x in sys.argv[1:] for x in ('--install','--repair','--update','install','repair','update'))
        if wants_write and not any(x in sys.argv[1:] for x in ('--dry-run','--check','--help','-h','doctor','status','check','plan','search','list','models','hardware')):
            lock_dir = journal.state_dir()
            lock_file = lock_dir/'setup.lock'
            fd=os.open(lock_file,os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'a+') as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sys.exit(main())
        sys.exit(main())
    except (KeyboardInterrupt,EOFError):
        print('Cancelled; no further actions will run.',file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(2)
