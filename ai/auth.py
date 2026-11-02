"""Private local keys and live loopback authentication checks (no proxy)."""
from __future__ import annotations
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
import ai_health


def menu(args):
    """Explicit interactive API configuration; reuse the same tested actions."""
    import sys
    if not sys.stdin.isatty():print('API configuration menu requires an interactive terminal.');return 4
    actions=['key-generate','key-use','key-copy','test-auth','key-rotate','key-revoke','key-status']
    labels=['Generate API key','Use existing API key','Copy API key','Test API authentication','Rotate API key','Revoke stored API key','View key status']
    print('AI API configuration')
    for index,label in enumerate(labels,1):print(f'{index}. {label}')
    choice=input('Choose [1–7], or Enter to cancel: ').strip()
    if not choice:return 0
    if choice not in tuple(str(x) for x in range(1,8)):print('Invalid menu choice.');return 2
    import argparse
    selected=argparse.Namespace(**{**vars(args),'action':actions[int(choice)-1]})
    if selected.action in ('key-generate','key-use','key-rotate','key-revoke') and not selected.yes and not selected.dry_run:
        if input('Change the stored API key? [y/N]: ').strip().lower() not in ('y','yes'):return 4
        selected.yes=True
    return main(selected)


def key_path(backend):
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'automation-toolkit/ai' / backend / 'api-key'


def safe_path(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError('Key path must be absolute')
    for component in (path, *path.parents):
        if component.is_symlink(): raise ValueError('Symlink key path is forbidden')
    return path


def validate_key(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', value):
        raise ValueError('Key must contain 32–256 ASCII letters, digits, underscores or hyphens')
    return value


def read(path):
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1:
            raise ValueError('Key must be a private regular file owned by the current user (0600)')
        return validate_key(stream.read(258).strip())


def read_legacy(path):
    """Import one old raw/env key as data; never source it or change the old file."""
    path=safe_path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        st=os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_nlink!=1 or st.st_size>512:
            raise ValueError('Legacy key must be a bounded private owned regular file')
        value=stream.read(513).strip()
    if value.startswith('VLLM_API_KEY='):value=value[len('VLLM_API_KEY='):]
    return validate_key(value)


def save(path, value, *, replace=False):
    path = safe_path(path)
    source=Path(__file__).resolve().parents[1]
    if path==source or source in path.resolve().parents:
        raise ValueError('Store API keys outside the toolkit source tree')
    validate_key(value)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
        raise ValueError('Key directory must be owned by this user with mode 0700')
    if path.exists():
        read(path)
        if not replace: return False
    fd, stage = tempfile.mkstemp(prefix='.key-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value + '\n'); stream.flush(); os.fsync(stream.fileno())
        if replace: os.replace(stage, path)
        else: os.link(stage, path)
    finally:
        if os.path.exists(stage): os.unlink(stage)
    return True


def copy_key(value):
    cmd = None
    if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-copy'):
        cmd = ['wl-copy', '--type', 'text/plain']
    elif os.environ.get('DISPLAY') and shutil.which('xclip'):
        cmd = ['xclip', '-selection', 'clipboard']
    elif os.environ.get('DISPLAY') and shutil.which('xsel'):
        cmd = ['xsel', '--clipboard', '--input']
    if cmd:
        try:
            if subprocess.run(cmd, input=value, text=True, capture_output=True, timeout=5).returncode == 0:
                print('API key copied to the session clipboard.'); return 0
        except (OSError, subprocess.TimeoutExpired): pass
    # Explicit copy action may reveal the key only on a controlling terminal.
    try:
        with open('/dev/tty', 'w') as terminal:
            terminal.write('Private API key (select to copy): ' + value + '\n')
        print('Key shown on the controlling terminal only.'); return 0
    except OSError:
        print('No session clipboard or controlling terminal available. Key was not printed.')
        return 3


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def test_endpoint(backend, path, host='127.0.0.1', port=None):
    if backend not in ('llamacpp', 'vllm','jan'):
        print('Native API-key enforcement is not configured for this backend.'); return 3
    key = read(path)
    base = ai_health.endpoint(backend, host, port or ai_health.DEFAULT_PORTS[backend])
    url = base.split('/health')[0] + '/v1/models' if backend == 'llamacpp' else base
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def request(value):
        headers = {'Authorization': 'Bearer ' + value} if value else {}
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=5) as response:
                body = response.read(65537)
                if len(body) > 65536: raise ValueError('Authentication response too large')
                return response.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            code = exc.code; exc.close(); return code, None
    try:
        good, payload = request(key)
        bad, _ = request('invalid-' + secrets.token_hex(24))
        absent, _ = request(None)
    except (OSError, ValueError):
        print('Authentication test failed: endpoint unavailable or invalid response.'); return 3
    ok = good == 200 and isinstance(payload, dict) and isinstance(payload.get('data'), list) and bad in (401,403) and absent in (401,403)
    print(f'Live authentication: valid HTTP {good}; invalid HTTP {bad}; absent HTTP {absent}.')
    print('Enforcement verified on /v1/models.' if ok else 'Authentication enforcement NOT verified.')
    return 0 if ok else 5


def main(args):
    if args.backend not in ('llamacpp', 'vllm','jan'):
        print('Native authentication management is available for llama.cpp, vLLM and an existing Jan API.'); return 3
    path = safe_path(args.key_file or key_path(args.backend))
    action = args.action.removeprefix('key-')
    if action == 'status':
        if not path.exists(): print('No toolkit key configured.'); return 0
        read(path)
        print('Private key present: ******** (endpoint enforcement requires test-auth).'); return 0
    if args.dry_run:
        print('Dry run: key operation planned; no secrets read, written, copied or sent.'); return 0
    if args.action == 'test-auth': return test_endpoint(args.backend, path, args.host, args.port)
    if action == 'copy': return copy_key(read(path))
    if not args.yes:
        print('Changing API keys requires --yes.'); return 4
    if action=='import':
        source=getattr(args,'legacy_key_file',None)
        if source is None:raise ValueError('key-import requires --legacy-key-file')
        value=read_legacy(source)
        if path.exists() and read(path)!=value:raise ValueError('Destination key differs; import never overwrites it')
        save(path,value)
        print('Legacy key imported privately; original file preserved.')
    elif action in ('generate', 'rotate', 'use'):
        if action == 'use':
            if not os.isatty(0): print('Use-existing requires a private interactive terminal.'); return 4
            value = getpass.getpass('Existing API key: ')
        else: value = 'sk-local-' + secrets.token_urlsafe(36)
        changed = save(path, value, replace=action != 'generate')
        print('Private key saved.' if changed else 'Existing key preserved.')
    elif action == 'revoke':
        read(path); path.unlink()
        print('Stored key removed. Running endpoints retain loaded keys until explicitly restarted.')
    else: raise ValueError('Unknown key operation')
    print('No running server changed. Restart with the reviewed key file to activate changes.')
    if args.backend=='jan':print('Apply the reviewed key in Jan Desktop API settings; this tool does not edit Jan configuration.')
    return 0
