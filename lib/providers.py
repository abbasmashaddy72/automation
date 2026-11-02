"""Read-only release-aware native repository provider layer.

Only preconfigured, signed distro repositories are queried. This module never
adds repositories, refreshes package metadata, changes system configuration or
infers that related software is an equivalent product.
"""
from __future__ import annotations
import re
import os
import shutil
import subprocess
import catalog
import discovery
import cache

MANAGERS = {'arch':'pacman','debian':'apt-get','fedora':'dnf','rhel':'dnf',
            'opensuse':'zypper','alpine':'apk'}
IMMUTABLE_IDS = ('fedora-silverblue','silverblue','kinoite','sericea','onyx','aurora','bazzite','bluefin','ublue','nixos','microos','opensuse-microos','aeon','opensuse-aeon','kalpa','opensuse-kalpa','fedora-coreos','fedora-iot')
IMMUTABLE_VARIANTS = ('silverblue','kinoite','sericea','onyx','coreos','sway-atomic','cosmic-atomic','budgie-atomic')


def capability(info):
    family=info.get('family','unknown')
    distro=str(info.get('id','unknown')).lower()
    immutable=bool(info.get('immutable')) or distro in IMMUTABLE_IDS
    wsl=bool(info.get('wsl'))
    manager=MANAGERS.get(family)
    reasons=[]
    if not manager: reasons.append('Unrecognized distribution: no native installer selected')
    if immutable: reasons.append('Immutable or transactional host: use the distro-specific deployment workflow')
    if wsl: reasons.append('WSL: host installation requires explicit review; host services are not assumed')
    return {'family':family,'distro':distro,'version':info.get('version','unknown'),
            'architecture':info.get('arch','unknown'),'manager':manager,
            'host_install_allowed':bool(manager) and not immutable and not wsl,
            'warnings':reasons,'container':bool(info.get('container'))}


def candidates(requested, info):
    """Curated potential native names (all must still pass exact repository checks).

    Ubuntu's firefox package may bootstrap Snap. Report its native name but do
    not silently add Snap: the distro package manager decides dependencies.
    """
    discovery.validate_term(requested)
    family=info.get('family','unknown')
    name=catalog.native_name(requested,family)
    if requested=='python3' and family=='opensuse' and (info.get('id') in ('opensuse-tumbleweed','opensuse-slowroll') or str(info.get('version','')).startswith('16')):
        name='python313'
    if requested=='firefox' and family=='debian' and info.get('id') in ('ubuntu','pop','linuxmint'):
        name='firefox'
    # An absent curated mapping must not prevent an exact repository probe.
    # A candidate is NEVER installable without exact_available() succeeding.
    return list(dict.fromkeys([value for value in (name,requested) if value]))


def exact_query(family, package):
    discovery.validate_term(package)
    commands={'arch':['pacman','-Si',package],
              'debian':['apt-cache','show',package],
              'fedora':['dnf','-q','--cacheonly','info','--available',package],
              'rhel':['dnf','-q','--cacheonly','info','--available',package],
              'opensuse':['zypper','--non-interactive','--no-refresh','info',package],
              'alpine':['apk','search','-x',package]}
    return commands.get(family)


def _run(command):
    if not command or not shutil.which(command[0]):return None
    try:return subprocess.run(command,capture_output=True,text=True,timeout=15,env={**os.environ,'LC_ALL':'C'})
    except (OSError,subprocess.TimeoutExpired):return None


def exact_available(package,info,*,runner=None):
    """Require exact identity in active repository metadata; no fuzzy installs."""
    family=info.get('family','unknown')
    cmd=exact_query(family,package)
    if not cmd:return False
    key=['native-exact-v2',family,str(info.get('id')),str(info.get('version')),str(info.get('arch')),package]
    if runner is None:
        saved=cache.get(key)
        if saved is not None:return bool(saved)
    proc=(runner or _run)(cmd)
    if proc is None or proc.returncode:return False
    out=proc.stdout
    if family=='debian':
        result = bool(re.search(r'^Package:\s*'+re.escape(package)+r'\s*$',out,re.M))
    elif family=='opensuse':
        result = bool(re.search(r'^Name\s*:\s*'+re.escape(package)+r'\s*$',out,re.M))
    elif family in ('fedora','rhel'):
        result = bool(re.search(r'^Name\s*:\s*'+re.escape(package)+r'\s*$',out,re.M))
    elif family=='alpine':
        result = any(line.strip()==package or bool(re.match(r'^'+re.escape(package)+r'-\d',line.strip())) for line in out.splitlines())
    elif family=='arch':
        result = bool(re.search(r'^Name\s*:\s*'+re.escape(package)+r'\s*$',out,re.M))
    else:result=False
    if runner is None:cache.put(key,result)
    return result


def choose_native(requested,info,*,runner=None):
    """Return a validated curated native package name or None."""
    for name in candidates(requested,info):
        if exact_available(name,info,runner=runner):return name
    return None
