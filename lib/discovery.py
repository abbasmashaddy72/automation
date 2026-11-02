#!/usr/bin/env python3
"""Read-only discovery of similar packages in repositories *already configured*.

No repository changes, arbitrary command execution, remote scripts or guessed
package substitutions. Output candidates are suggestions, NOT equivalents.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
from functools import lru_cache
import cache

# Catalog source names may differ from repository names. Query terms are
# suggestions only, never implicitly approved installation names.
SEARCH_TERMS = {
    'visual-studio-code-bin': ('code', 'vscode', 'codium'),
    'brave-browser': ('brave',),
    'google-chrome': ('chrome', 'chromium'),
    'firefox-developer-edition': ('firefox',),
    'intellij-idea-community-edition': ('intellij', 'idea'),
    'pycharm-community-edition': ('pycharm',),
    'android-studio': ('android-studio',),
    'postman-bin': ('postman',),
    'tiny-rdm-bin': ('tiny-rdm', 'tinyrdm'),
    'ttf-hack-nerd': ('hack-font', 'hack'),
    'ttf-jetbrains-mono': ('jetbrains-mono',),
    'onlyoffice-bin': ('onlyoffice',),
    'dbeaver': ('dbeaver',),
    'torbrowser-launcher': ('torbrowser',),
    'virtualbox-guest-iso': ('virtualbox',),
}
PACKAGE_RX = re.compile(r'^[A-Za-z0-9][A-Za-z0-9+._-]{0,95}$')


def validate_term(value):
    if not isinstance(value,str) or not PACKAGE_RX.fullmatch(value):
        raise ValueError('Package names must be 1–96 characters: letters, digits, +, ., _, - (no shell syntax)')
    return value


def search_command(family, term):
    term = validate_term(term)
    commands = {
        'arch': ['pacman', '-Ss', term],
        'debian': ['apt-cache', 'search', term],
        'fedora': ['dnf', '-q', '--cacheonly', 'search', term],
        'rhel': ['dnf', '-q', '--cacheonly', 'search', term],
        'opensuse': ['zypper', '--non-interactive', '--no-refresh', 'search', '--details', term],
        'alpine': ['apk', 'search', '-v', term],
    }
    if family not in commands: raise ValueError('Unsupported Linux package-manager family')
    return commands[family]


def parse_search(family, output):
    """Parse conservative name/description pairs; malformed rows are ignored."""
    found = {}
    for line in output.splitlines()[:750]:
        line = line.strip()
        name, desc = None, ''
        if family == 'debian':
            m = re.match(r'^([A-Za-z0-9][A-Za-z0-9+._-]*)\s+-\s+(.+)$',line)
            if m: name,desc=m.groups()
        elif family == 'arch':
            m = re.match(r'^[A-Za-z0-9_.+-]+/([A-Za-z0-9+._-]+)\s+\S+',line)
            if m: name=m.group(1)
        elif family in ('fedora','rhel'):
            m = re.match(r'^([A-Za-z0-9+._-]+?)(?:\.(?:x86_64|aarch64|noarch|i686))?\s+:\s+(.+)$',line)
            if m: name,desc=m.groups()
        elif family == 'opensuse':
            cols = [x.strip() for x in line.split('|')]
            if len(cols) >= 4 and cols[-1].lower() in ('package','source package'):
                name, desc = cols[1],cols[2]
        elif family == 'alpine':
            m = re.match(r'^([A-Za-z0-9][A-Za-z0-9+._-]+?)-\d[^ ]*\s+-\s+(.+)$',line)
            if m: name,desc=m.groups()
        if name and PACKAGE_RX.fullmatch(name) and len(desc) < 400:
            found[name.lower()]={'package':name,'description':desc,'source':'native'}
    return list(found.values())


def _execute(cmd,timeout=9):
    if not shutil.which(cmd[0]): return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,env={**os.environ,'LC_ALL':'C'})
    except (OSError,subprocess.TimeoutExpired): return None


@lru_cache(maxsize=150)
def native_search(family, term):
    key=['native-search-v2',family,term]
    saved=cache.get(key)
    if saved is not None:return saved
    proc = _execute(search_command(family,term))
    if proc is None or proc.returncode: return []
    result=parse_search(family,proc.stdout)
    cache.put(key,result)
    return result


def normalize(s):
    return re.sub(r'[^a-z0-9]+','',re.sub(r'-bin$', '', s.lower()))


def rank(requested, results, limit=5):
    """Relevance ranks, NOT a claim of package identity or source trust."""
    requested=validate_term(requested)
    terms = (requested,*SEARCH_TERMS.get(requested,()))
    scored = []
    seen = set()
    for row in results:
        name=row.get('package','')
        if not PACKAGE_RX.fullmatch(name) or (row.get('source'),name.lower()) in seen: continue
        seen.add((row.get('source'),name.lower()))
        normalized=normalize(name)
        if not normalized: continue
        scores=[]
        name_tokens=set(re.findall(r'[a-z0-9]+',name.lower()))
        for term in terms:
            normalized_term=normalize(term)
            term_tokens=set(re.findall(r'[a-z0-9]+',term.lower()))
            if normalized == normalized_term:
                score=0.99 if term == requested else 0.92
            elif term_tokens and term_tokens.issubset(name_tokens):
                # Word-boundary matches only: 'code' must NOT match 'codec'.
                score=0.85
            elif len(normalized_term)>=6 and len(normalized)>=6 and (normalized_term in normalized or normalized in normalized_term):
                score=0.77
            elif len(normalized_term)>=6 and len(normalized)>=6 and abs(len(normalized_term)-len(normalized))<=5:
                similarity=difflib.SequenceMatcher(None,normalized_term,normalized).ratio()
                score=similarity*0.75 if similarity>=0.86 else 0
            else:
                score=0
            scores.append(score)
        score=max(scores)
        if score < 0.52: continue
        exact = name.lower() == requested.lower()
        # Product identity != name similarity. Even a same-name repository
        # listing does not establish upstream provenance or signature trust.
        different_products = {
            'google-chrome': {'chromium'},
            'visual-studio-code-bin': {'codium','vscodium','code-oss'},
            'firefox-developer-edition': {'firefox'},
        }
        identity = ('related-different-product' if name.lower() in different_products.get(requested, set())
                    else 'exact-name-source-unverified' if exact
                    else 'similar-name-identity-unverified')
        rank_label = 'exact name' if exact else 'similar / verify identity'
        scored.append({**row, 'confidence':int(score*100),'relation':rank_label,'identity':identity})
    scored.sort(key=lambda x:(-x['confidence'],x['source']!='native',x['package']))
    return scored[:max(1,min(limit,10))]


def suggest(name, info, *, limit=5, enable_aur=False, include_flatpak=True):
    """Discover name matches via native metadata and enabled optional sources.

    AUR checks are read-only; results are NEVER installed without user approval.
    Flatpak suggestions are validated against the configured Flathub remote.
    """
    name=validate_term(name)
    family=info.get('family')
    if family not in ('arch','debian','fedora','rhel','opensuse','alpine'): return []
    terms=list(dict.fromkeys((name,*SEARCH_TERMS.get(name,()))))[:4]
    found=[]
    for term in terms:
        found.extend(native_search(family,term))
    if family=='arch' and enable_aur and (shutil.which('paru') or shutil.which('yay')):
        helper='paru' if shutil.which('paru') else 'yay'
        # Search enabled AUR only on Arch, without running build scripts.
        for term in terms[:2]:
            proc=_execute([helper,'-Ss',term],timeout=12)
            if proc and proc.returncode==0:
                for row in parse_search('arch',proc.stdout):
                    found.append({**row,'source':'aur:'+helper})
    if include_flatpak and info.get('desktop') and shutil.which('flatpak'):
        try:
            import catalog
            app_id=catalog.FLATPAKS.get(name)
            if app_id:
                proc=_execute(['flatpak','remote-info','--user','flathub',app_id],timeout=8)
                if proc and proc.returncode==0:
                    desc='Configured Flathub application: '+app_id
                    if name=='visual-studio-code-bin': desc+=' (unofficial, unverified community repackaging)'
                    found.append({'package':name,'description':desc,'source':'flatpak','app_id':app_id})
        except (ImportError,OSError): pass
    return rank(name,found,limit)
