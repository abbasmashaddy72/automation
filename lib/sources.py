"""Read-only multi-source discovery, separated from installation authorization.

Native repositories, AUR helpers and Shelly are distinct sources. We do not
assume that similar package names are identical products or that community
packages are trustworthy. All subprocess calls use argv, never the shell.
"""
from __future__ import annotations

import re
import os
import shutil
import subprocess
import time
import cache

from discovery import validate_term

HELPERS = ('shelly', 'paru', 'yay', 'pamac')
RX_NAME = re.compile(r'^\s*Name\s*:\s*(\S+)\s*$', re.I | re.M)
RX_REPO = re.compile(r'^\s*Repository\s*:\s*(\S+)\s*$', re.I | re.M)


def arch_sources(info, *, which=None):
    """List ALL usable Arch source frontends, not just the first helper."""
    if info.get('family') != 'arch':
        return []
    which = which or shutil.which
    return [name for name in HELPERS if which(name)]


def commands(source, name):
    validate_term(name)
    return {
        'paru': ['paru', '-Si', name],
        'yay': ['yay', '-Si', name],
        'pamac': ['pamac', 'info', '--aur', name],
        'shelly': ['shelly', 'aur', 'search', name],
    }[source]


def _execute(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=12,env={**os.environ,'LC_ALL':'C'})
    except (OSError, subprocess.TimeoutExpired):
        return None


def exact_metadata(source, name, output):
    """Require an exact package-name field for helper info output.

    Shelly documents `aur search` but doesn't promise stable machine-readable
    output. Only accept a visibly anchored `aur/name VERSION` search hit; other
    text remains an unverified suggestion, never an automatic install target.
    """
    name = validate_term(name)
    if source == 'shelly':
        # Shelly releases have used multiple human-readable AUR search layouts.
        # Only accept anchored name cells/fields, never description mentions.
        exact = re.escape(name)
        return bool(
            re.search(r'(?im)^\s*(?:aur/)' + exact + r'\s+\S+', output)
            or re.search(r'(?im)^\s*Name\s*:\s*' + exact + r'\s*$', output)
            or re.search(r'(?im)^\s*' + exact + r'\s+[0-9][A-Za-z0-9:._+~-]*', output)
            or re.search(r'(?im)^\s*' + exact + r'\s*$', output)
        )
    match = RX_NAME.search(output)
    if not match or match.group(1).lower() != name.lower():
        return False
    repo = RX_REPO.search(output)
    if source in ('yay', 'paru'):
        return bool(repo and repo.group(1).lower() == 'aur')
    return source == 'pamac' and (not repo or repo.group(1).lower() == 'aur')


def search_exact(name, info, *, runner=None, which=None):
    """Read-only check of each available frontend. Returns verified candidates.

    No AUR PKGBUILD execution or installation is performed here.
    """
    validate_term(name)
    real_query = runner is None and which is None
    key=['aur-exact-v1',str(info.get('id')),str(info.get('arch')),name]
    if real_query:
        previous=cache.get(key,ttl=300)
        if previous is not None:return previous
    runner = runner or _execute
    candidates = []
    for source in arch_sources(info, which=which):
        proc = runner(commands(source, name))
        if proc is not None and proc.returncode == 0 and exact_metadata(source, name, proc.stdout):
            candidates.append({'package': name, 'source': source, 'identity': 'exact-name-aur-community',
                               'description': 'AUR build recipe; review PKGBUILD, upstream and maintainer before approving'})
    if real_query:cache.put(key,candidates)
    return candidates


def helper_install_cmd(source, name):
    validate_term(name)
    if source == 'shelly':
        # Documented Shelly AUR interface; do NOT use old -Is/-n flags.
        return ['shelly', 'aur', 'install', name]
    if source in ('yay', 'paru'):
        # Do not suppress PKGBUILD review or run helpers as root.
        return [source, '-S', name]
    if source == 'pamac':
        return ['pamac', 'build', name]
    raise ValueError('Unsupported AUR provider')
