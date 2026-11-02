"""Explicit rootless Open WebUI lifecycle; preserve all application data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import developer

import journal

NAME = 'automation-open-webui'
VOLUME = 'automation-open-webui-data'
LABEL = 'org.automation-toolkit.webui'
IMAGE = re.compile(r'ghcr\.io/open-webui/open-webui@sha256:[0-9a-f]{64}\Z')


def call(command, *, timeout=30):
    try:
        env = dict(os.environ)
        for name in ('CONTAINER_HOST', 'CONTAINER_CONNECTION', 'CONTAINER_SSHKEY'):
            env.pop(name, None)
        return subprocess.run(['podman', '--remote=false', *command], capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('Podman timed out; inspect the owned resources before retrying') from None


def inspect(kind, name):
    exists = call([kind, 'exists', name])
    if exists.returncode == 1:
        return None
    if exists.returncode:
        raise ValueError('Podman could not determine whether the resource exists')
    result = call([kind, 'inspect', name])
    if result.returncode or len(result.stdout) > 1_000_000:
        raise ValueError('Podman inspection failed')
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError('Invalid Podman inspection response')
    return rows[0]


def receipt_path(*, create=False):
    return journal.state_dir(create=create)/'open-webui.json'


def pending_path():
    return journal.state_dir(create=False)/'open-webui.pending.json'


def read_metadata(path):
    if not path.exists():
        if path.is_symlink(): raise ValueError('Unsafe Open WebUI metadata link')
        return None
    st = path.lstat()
    if (path.is_symlink() or not path.is_file() or st.st_uid != os.getuid()
            or st.st_nlink != 1 or st.st_mode & 0o077 or st.st_size > 4096):
        raise ValueError('Unsafe Open WebUI metadata')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('Duplicate Open WebUI metadata field')
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique)


def valid_selection(value):
    return (isinstance(value, dict) and isinstance(value.get('token'), str)
            and bool(re.fullmatch('[0-9a-f]{32}', value['token']))
            and isinstance(value.get('image'), str) and bool(IMAGE.fullmatch(value['image']))
            and type(value.get('port')) is int and 1024 <= value['port'] <= 65535)


def receipt():
    value = read_metadata(receipt_path())
    if value is None: return None
    if (not valid_selection(value) or set(value) not in (
                {'schema', 'id', 'token', 'image', 'port'},
                {'schema', 'id', 'token', 'image', 'port', 'volume_created_at'})
            or type(value['schema']) is not int or value['schema'] != 1 or not isinstance(value['id'], str)
            or not re.fullmatch('[0-9a-f]{64}', value['id'])
            or ('volume_created_at' in value and not valid_stamp(value['volume_created_at']))):
        raise ValueError('Invalid Open WebUI receipt')
    return value


def valid_stamp(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9TtZz:+. -]{10,100}', value))


def pending():
    value = read_metadata(pending_path())
    if value is None: return None
    if (not valid_selection(value) or set(value) != {'schema','token','image','port','previous_id','volume_created_at'}
            or type(value['schema']) is not int or value['schema'] != 1
            or (value['previous_id'] is not None and (not isinstance(value['previous_id'],str)
                or not re.fullmatch('[0-9a-f]{64}',value['previous_id'])))
            or (value['volume_created_at'] is not None and not valid_stamp(value['volume_created_at']))):
        raise ValueError('Invalid pending Open WebUI operation')
    return value


def write_metadata(path, value, *, expected=None):
    data = (json.dumps(value, sort_keys=True)+'\n').encode()
    if expected is None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    else:
        read_metadata(path)
        if path.read_bytes() != expected: raise ValueError('Open WebUI receipt changed during operation; recovery required')
        backup = path.with_name('open-webui.previous-'+uuid.uuid4().hex+'.json')
        write_metadata(backup, json.loads(expected))
        developer.replace(path,data)


def checked_volume(value):
    row = inspect('volume', VOLUME)
    if (row is None or row.get('Labels',{}).get(LABEL) != value['token']
            or not valid_stamp(row.get('CreatedAt'))
            or (value.get('volume_created_at') is not None and row['CreatedAt'] != value['volume_created_at'])):
        raise ValueError('Original owned Open WebUI data volume is absent or changed')
    return row


def ensure_image(image, allow_pull):
    if inspect('image', image) is not None: return 0
    if not allow_pull:
        print('Pinned image is not cached; explicit --allow-pull is required')
        return 5
    result = call(['pull',image],timeout=1800)
    if result.returncode: return result.returncode
    if inspect('image',image) is None: raise ValueError('Pinned image could not be verified after pull')
    return 0


def recover(args, row, previous):
    intent = pending()
    if intent is None: raise ValueError('No pending Open WebUI operation to recover')
    expected_pending = pending_path().read_bytes()
    expected_receipt = receipt_path().read_bytes() if previous is not None else None
    if (previous is not None and row is not None and row.get('Id') == previous['id']
            and intent['previous_id'] != previous['id']
            and all(previous[k] == intent[k] for k in ('token','image','port'))):
        # Receipt publication succeeded before a caught interruption or power loss
        # prevented intent cleanup. Observe the exact container/volume again.
        owned(row,previous); checked_volume(previous)
        if args.check or args.dry_run: print('Receipt already committed; pending cleanup only'); return 0
        if not args.yes: print('Recovery cleanup requires --yes'); return 4
        if pending_path().read_bytes() != expected_pending or receipt_path().read_bytes() != expected_receipt:
            raise ValueError('Recovery metadata changed; preserving it')
        pending_path().unlink()
        print('Committed receipt verified; pending operation cleared')
        return 0
    if previous is not None:
        if (previous['id'] != intent['previous_id'] or any(previous[k] != intent[k] for k in ('token','image','port'))):
            raise ValueError('Pending operation differs from the preserved receipt')
        if inspect('container',previous['id']) is not None:
            raise ValueError('Original container still exists; no recreation or adoption is allowed')
    elif intent['previous_id'] is not None:
        raise ValueError('Original receipt is missing; preserve resources for manual review')
    if row is not None:
        candidate = {**intent,'id':row.get('Id')}
        if not isinstance(candidate['id'],str) or not re.fullmatch('[0-9a-f]{64}',candidate['id']):
            raise ValueError('Unrecognized recovery container identity')
        owned(row,candidate)
    if args.check or args.dry_run:
        print('Pending operation can be inspected; no resources or receipts changed')
        return 0
    if not args.yes: print('Recovery requires --yes'); return 4
    if pending_path().read_bytes() != expected_pending: raise ValueError('Recovery intent changed; refusing mutation')
    if row is None:
        code = ensure_image(intent['image'],args.allow_pull)
        if code: return code
        volume = inspect('volume',VOLUME)
        if volume is None:
            if previous is not None: raise ValueError('Original data volume is missing; it will not be replaced')
            created = call(['volume','create','--label',LABEL+'='+intent['token'],VOLUME])
            if created.returncode: return created.returncode
        checked_volume(intent)
        result = call(run_command(intent['image'],intent['port'],intent['token']),timeout=180)
        if result.returncode:
            print('Creation failed; owned data and pending receipt preserved. Use webui recover --yes.')
            return result.returncode
        identifier = result.stdout.strip()
        if not re.fullmatch('[0-9a-f]{64}',identifier): raise ValueError('Creation returned no exact container identity; use recovery')
        row = inspect('container',identifier)
        owned(row,{**intent,'id':identifier})
    volume = checked_volume(intent)
    value = {k:intent[k] for k in ('schema','token','image','port')}
    value.update(id=row['Id'],volume_created_at=volume['CreatedAt'])
    if pending_path().read_bytes() != expected_pending: raise ValueError('Recovery intent changed before receipt commit')
    write_metadata(receipt_path(),value,expected=expected_receipt)
    if pending_path().read_bytes() != expected_pending: raise ValueError('Pending operation was edited; it has been preserved')
    pending_path().unlink()
    print('Owned container recorded; application readiness is a separate check')
    return 0


def owned(row, value):
    if (not isinstance(row, dict) or not value or row.get('Id') != value['id']
            or row.get('Config', {}).get('Labels', {}).get(LABEL) != value['token']
            or row.get('Config', {}).get('Image') != value['image']):
        raise ValueError('Refusing an unrelated or changed Open WebUI container')
    mounts = [item for item in row.get('Mounts', []) if item.get('Destination') == '/app/backend/data']
    if len(mounts) != 1 or mounts[0].get('Name') != VOLUME:
        raise ValueError('Open WebUI data mount differs from the owned configuration')


def run_command(image, port, token):
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError('Supply the reviewed upstream image pinned to an exact SHA-256 digest')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('WebUI port must be 1024–65535')
    return ['run', '--detach', '--pull=never', '--name', NAME,
            '--label', LABEL+'='+token, '--publish', f'127.0.0.1:{port}:8080',
            '--umask=0077',
            '--volume', VOLUME+':/app/backend/data', '--env', 'WEBUI_AUTH=True',
            '--env', 'WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key',
            '--env', 'OLLAMA_BASE_URL=http://host.containers.internal:11434', image]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explicit rootless Open WebUI; no existing containers, volumes or services are adopted')
    parser.add_argument('action', choices=['plan', 'status', 'install', 'recover', 'recreate', 'start', 'stop', 'remove'])
    parser.add_argument('--image', help='Reviewed ghcr.io/open-webui/open-webui@sha256:DIGEST')
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--allow-pull', action='store_true')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'plan' or (args.dry_run and args.action == 'install'):
        print(json.dumps({'command': ['podman', *run_command(args.image, args.port, 'REVIEW_TOKEN')],
                          'note': 'Rootless Podman required. Default: no pull. Existing Ollama must be reachable from the container; no host binding/firewall changes are made. App login and browser operation require separate verification.'}, indent=2))
        return 0
    if os.geteuid() == 0 or not shutil.which('podman'):
        raise ValueError('Use installed rootless Podman as your normal user')
    info = call(['info', '--format', '{{.Host.Security.Rootless}}'])
    if info.returncode or info.stdout.strip() != 'true':
        raise ValueError('Podman must report rootless mode')
    row = inspect('container', NAME)
    value = receipt()
    if args.action == 'recover': return recover(args,row,value)
    if row is not None and value is None and pending() is not None and (args.check or args.action == 'status'):
        print(json.dumps({'installed':False,'recovery_pending':True,'note':'Container is not yet receipted; use webui recover --yes after review'}))
        return 0
    if row is not None:
        owned(row, value)
    if args.check or args.action == 'status':
        print(json.dumps({'installed': row is not None, 'running': bool(row and row.get('State', {}).get('Running')),
                          'data_preserved': True, 'recovery_pending': pending() is not None,
                          'readiness': 'not inferred from container state'}))
        return 0
    if args.action == 'install':
        command = run_command(args.image, args.port, uuid.uuid4().hex)
        if row is not None:
            if value['image'] != args.image or value['port'] != args.port:
                raise ValueError('Existing owned configuration differs; review and remove the stopped container first')
            print('Owned Open WebUI already installed; no changes')
            return 0
        if value is not None or receipt_path().exists() or inspect('volume', VOLUME) is not None or pending() is not None:
            raise ValueError('An earlier receipt or data volume exists; preserve and review it instead of adopting/overwriting')
        if not args.yes:
            print('Open WebUI installation requires --yes after reviewing webui plan')
            return 4
        code = ensure_image(args.image,args.allow_pull)
        if code: return code
        receipt_path(create=True)
        intent = {'schema':1,'token':command[command.index('--label')+1].split('=',1)[1],
                  'image':args.image,'port':args.port,'previous_id':None,'volume_created_at':None}
        write_metadata(pending_path(),intent)
        return recover(args,None,None)
    if args.action == 'recreate':
        if row is not None or value is None: raise ValueError('Recreate requires a preserved receipt and an absent original container')
        if inspect('container',value['id']) is not None: raise ValueError('Original container still exists under another name')
        if not value.get('volume_created_at'): raise ValueError('Older receipt has no observed volume identity; manual review required')
        if args.image and args.image != value['image']: raise ValueError('Recreate preserves the pinned image; upgrades require a separate backup/migration plan')
        checked_volume(value)
        if args.check or args.dry_run: print('Dry run: would recreate the exact owned configuration and reuse only its observed data volume'); return 0
        if not args.yes: print('Recreate requires --yes'); return 4
        if pending() is not None: raise ValueError('Recover the pending operation first')
        intent = {k:value[k] for k in ('schema','token','image','port','volume_created_at')}
        intent['previous_id'] = value['id']
        write_metadata(pending_path(),intent)
        return recover(args,None,value)
    if row is None:
        print('Owned Open WebUI container is absent; no changes')
        return 0
    if args.action == 'remove' and row.get('State', {}).get('Running'):
        raise ValueError('Stop the owned container explicitly before removing it')
    if args.dry_run:
        print('Dry run:', args.action, 'owned container; data volume preserved')
        return 0
    if not args.yes:
        print('Container lifecycle requires --yes')
        return 4
    # Recheck exact identity after approval; never target a name that can be reused.
    owned(inspect('container', value['id']), value)
    result = call([{'start': 'start', 'stop': 'stop', 'remove': 'rm'}[args.action], value['id']], timeout=180)
    if result.returncode == 0 and args.action == 'remove':
        print('Removed owned container only; receipt and application data retained for recovery')
    return result.returncode
