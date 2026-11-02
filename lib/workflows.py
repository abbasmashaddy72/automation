"""Portable profiles, machine-readable plans, offline artifact receipts and static status pages.

All inputs are treated as data. No remote downloads, shell evaluation or service changes.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone

import journal

PROFILE_KEYS = {
    'AUTOMATION_PROFILE', 'AUTOMATION_LERD', 'AUTOMATION_PREFER_FLATPAK',
    'AUTOMATION_ENABLE_AUR', 'AUTOMATION_PREFER_SHELLY', 'AUTOMATION_AUTO_SEARCH',
    'AUTOMATION_SEARCH_LIMIT', 'AUTOMATION_SELECTED_PACKAGES',
    'AUTOMATION_EXCLUDED_PACKAGES', 'AUTOMATION_AI_BACKEND', 'AUTOMATION_AI_CONTEXT',
    'AUTOMATION_AI_THREADS', 'AUTOMATION_AI_QUOTA', 'AUTOMATION_AI_PORT',
}
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,47}\Z')
ARTIFACT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+~-]{0,180}\Z')
MAX_JSON = 1024 * 1024


def read_json(path: Path, *, max_size=MAX_JSON):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_size:
        raise ValueError('Refusing symlink, non-file, or oversized input')
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value, *, private=False):
    """Atomic write, no directory creation, no symlink overwrite, no secret exposure."""
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.parent.is_dir() or any(part.is_symlink() for part in (path.parent, *path.parent.parents)):
        raise ValueError('Output parent must exist and neither target nor ancestors can be symlinks')
    if path.exists():
        raise ValueError('Output exists: choose a new file (no overwrite)')
    data = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + '\n'
    if len(data) > MAX_JSON: raise ValueError('Output too large')
    fd, tmp = tempfile.mkstemp(prefix='.automation-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600 if private else 0o644)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            fd = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists() or path.is_symlink(): raise ValueError('Output was created concurrently')
        os.link(tmp, path, follow_symlinks=False)  # atomic create-only; avoid replacement
    finally:
        if fd >= 0: os.close(fd)
        Path(tmp).unlink(missing_ok=True)
    return path


def profile_data(settings):
    values = {k: v for k, v in settings.items() if k in PROFILE_KEYS}
    return {'schema': 1, 'type': 'automation-profile', 'settings': values}


def validate_profile(obj, validate_settings):
    if not isinstance(obj, dict) or set(obj) != {'schema', 'type', 'settings'} or obj['schema'] != 1 or obj['type'] != 'automation-profile':
        raise ValueError('Unsupported profile schema')
    values = obj['settings']
    if not isinstance(values, dict) or set(values) - PROFILE_KEYS:
        raise ValueError('Profile contains forbidden settings')
    validate_settings(values)
    return values


def profile_dir(state='', *, create=True):
    root = journal.state_dir(state,create=create)
    folder = root / 'profiles'
    if folder.is_symlink(): raise ValueError('Symlink profile directory')
    if not create and not folder.exists(): return folder
    if create: folder.mkdir(mode=0o700, exist_ok=True)
    if folder.stat().st_mode & 0o077: raise ValueError('Profiles must be private')
    return folder


def import_profile(source, state, validate_settings):
    values = validate_profile(read_json(Path(source)), validate_settings)
    name = Path(source).stem
    if not NAME.fullmatch(name): raise ValueError('Profile filename must be a simple name (letters, digits, hyphen or underscore)')
    destination = profile_dir(state) / (name + '.json')
    write_json(destination, {'schema': 1, 'type': 'automation-profile', 'settings': values}, private=True)
    return destination


def saved_profile(name, state, validate_settings):
    if not NAME.fullmatch(name): raise ValueError('Invalid profile name')
    return validate_profile(read_json(profile_dir(state,create=False) / (name + '.json')), validate_settings)


def list_profiles(state):
    return sorted(p.stem for p in profile_dir(state,create=False).glob('*.json') if p.is_file() and not p.is_symlink() and NAME.fullmatch(p.stem))


def plan_data(info, rows, *, profile='default'):
    """A snapshot, not a promise the same packages will be available later."""
    safe_host = {k: info.get(k) for k in ('id', 'version', 'family', 'arch', 'manager')}
    packages = [{k: row.get(k) for k in ('name', 'status', 'source', 'actual')} for row in rows]
    return {'schema': 1, 'type': 'automation-plan', 'host': safe_host,
            'profile': profile, 'packages': packages,
            'note': 'Read-only snapshot; revalidate with setup.sh before installation.'}


def validate_plan(value):
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('type') != 'automation-plan':
        raise ValueError('Invalid installation plan')
    rows = value.get('packages')
    if not isinstance(rows, list) or len(rows) > 1000: raise ValueError('Invalid plan package list')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not NAME_PACKAGE.fullmatch(row['name']):
            raise ValueError('Invalid plan package name')
        if row.get('status') not in ('installed','available','managed','unavailable'):
            raise ValueError('Invalid plan package status')
        if not isinstance(row.get('actual'), (str, type(None))):
            raise ValueError('Invalid actual package name')
    return rows


NAME_PACKAGE = re.compile(r'[A-Za-z0-9][A-Za-z0-9+._-]{0,95}\Z')
EXTENSIONS = ('.deb', '.rpm', '.apk', '.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz')


def prepare_offline(plan_path, cache_dir, output, assignments=()):
    """Record explicit locally cached artifacts only; never infer package equivalence."""
    plan = read_json(Path(plan_path))
    rows = validate_plan(plan)
    cache = Path(cache_dir).expanduser().resolve(strict=True)
    if not cache.is_dir(): raise ValueError('Cache must be a directory')
    mapping = {}
    selected = {r['name'] for r in rows}
    for assignment in assignments:
        if '=' not in assignment: raise ValueError('Artifact requires PACKAGE=FILENAME')
        name, filename = assignment.split('=', 1)
        if name not in selected or not ARTIFACT.fullmatch(filename) or filename.startswith('.') or not filename.endswith(EXTENSIONS):
            raise ValueError('Unknown package or unsafe artifact filename')
        if name in mapping: raise ValueError('Duplicate artifact mapping')
        mapping[name] = filename
    entries = []
    family = (plan.get('host') or {}).get('family')
    suffixes = {'arch':('.pkg.tar.zst','.pkg.tar.xz','.pkg.tar.gz'),
                'debian':('.deb',), 'fedora':('.rpm',), 'rhel':('.rpm',),
                'opensuse':('.rpm',), 'alpine':('.apk',)}
    for row in rows:
        name = row['name']
        record = {'package': name, 'status': 'not-needed' if row['status']=='installed' else 'not-cached',
                  'filename': None, 'sha256': None, 'size': None}
        if name in mapping:
            if family not in suffixes or not mapping[name].endswith(suffixes[family]):
                raise ValueError('Artifact extension is incompatible with the plan distribution family')
            if row['status'] != 'available':
                raise ValueError('Offline artifact mappings require a plan entry in available status')
            file = cache / mapping[name]
            if file.is_symlink() or not file.is_file() or file.resolve().parent != cache:
                raise ValueError('Artifact must be a regular file directly inside cache')
            digest = sha256(file)
            record.update(status='verified-local', filename=file.name, sha256=digest, size=file.stat().st_size)
        entries.append(record)
    manifest = {'schema': 1, 'type': 'automation-offline-manifest', 'host': plan.get('host'),
                'artifacts': entries, 'note': 'Does not download or install; cache filenames must be supplied explicitly.'}
    write_json(Path(output), manifest)
    return manifest


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_offline(manifest_path, cache_dir):
    manifest = read_json(Path(manifest_path))
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or manifest.get('type') != 'automation-offline-manifest':
        raise ValueError('Invalid offline manifest')
    cache = Path(cache_dir).expanduser().resolve(strict=True)
    if not cache.is_dir(): raise ValueError('Cache must be a directory')
    items = manifest.get('artifacts', [])
    if not isinstance(items, list) or len(items)>1000: raise ValueError('Invalid artifact list')
    checked = 0; missing = []; invalid = []; not_cached = []
    for item in items:
        if not isinstance(item, dict): raise ValueError('Invalid artifact entry')
        if item.get('status') == 'not-cached':
            name = item.get('package')
            if not isinstance(name,str) or not NAME_PACKAGE.fullmatch(name):
                raise ValueError('Invalid uncached package name')
            not_cached.append(name)
            continue
        if item.get('status') == 'not-needed': continue
        if item.get('status') != 'verified-local': raise ValueError('Invalid artifact status')
        filename = item.get('filename')
        if not isinstance(filename, str) or not ARTIFACT.fullmatch(filename) or filename.startswith('.') or not filename.endswith(EXTENSIONS):
            raise ValueError('Unsafe cached artifact reference')
        file = cache / filename
        if file.is_symlink() or not file.is_file() or file.resolve().parent != cache:
            missing.append(filename); continue
        if file.stat().st_size != item.get('size') or sha256(file) != item.get('sha256'):
            invalid.append(filename)
        else: checked += 1
    return {'verified': checked, 'missing': missing, 'mismatched': invalid, 'not_cached': not_cached,
            'integrity_ok': not (missing or invalid), 'complete': not (missing or invalid or not_cached),
            'ok': not (missing or invalid or not_cached)}


def dashboard_html(inventory, recovery):
    """Self-contained HTML; no JS, CDN, remote fonts or networking."""
    def esc(value): return html.escape(str(value), quote=True)
    rows = ''.join('<tr><td>'+esc(name)+'</td><td>'+esc(item.get('package',''))+'</td><td>'+esc(item.get('source',''))+'</td></tr>'
                   for name, item in sorted(inventory.items()) if isinstance(item, dict))
    latest = recovery.get('latest') if isinstance(recovery,dict) else None
    status = latest.get('event','unknown') if isinstance(latest,dict) else 'No recorded installation'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
            '<title>Automation Toolkit Report</title><style>body{font-family:system-ui;max-width:850px;margin:3rem auto;padding:1rem}'
            'table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #aaa;padding:.6rem;text-align:left}'
            '</style></head><body><h1>Linux Automation Toolkit</h1><p>Last installation: '+esc(status)+'</p>'
            '<h2>Observed toolkit package installs</h2><table><thead><tr><th>Selection</th><th>Package</th><th>Source</th></tr></thead>'
            '<tbody>'+rows+'</tbody></table><p>Observational report only. No uninstall rights implied.</p></body></html>')


def export_dashboard(output, state=''):
    path = Path(output).expanduser().absolute()
    if path.is_symlink() or path.exists() or not path.parent.is_dir() or any(p.is_symlink() for p in (path.parent,*path.parent.parents)):
        raise ValueError('Output must be a new file under a non-symlink directory')
    document = dashboard_html(journal.owned(directory=state), journal.status(directory=state))
    fd, tmp = tempfile.mkstemp(prefix='.automation-html-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            fd=-1; f.write(document); f.flush(); os.fsync(f.fileno())
        os.link(tmp, path, follow_symlinks=False)
    finally:
        if fd>=0:os.close(fd)
        Path(tmp).unlink(missing_ok=True)
    return path
