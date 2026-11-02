"""Validated Git sources and noninteractive host-trust-preserving transport."""
from __future__ import annotations
import os
from pathlib import Path
import re
import urllib.parse
from . import common as production


def repository(value,allow_local=False):
    if allow_local and value and Path(value).is_absolute():return str(production.checked(value))
    if not isinstance(value,str) or len(value)>1024 or any(ord(c)<33 for c in value):raise ValueError('Provide a literal SSH/HTTPS repository')
    if re.fullmatch(r'git@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9_./-]+',value) and '..' not in value.split(':',1)[1].split('/'):return value
    url=urllib.parse.urlsplit(value)
    if url.scheme=='https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.path.startswith('/'):
        return value
    raise ValueError('Repository credentials must use an SSH agent or credential helper, never URL tokens')


def environment():
    env=dict(os.environ)
    for name in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_CONFIG','GIT_CONFIG_COUNT','GIT_CONFIG_PARAMETERS','COMPOSER','COMPOSER_VENDOR_DIR','BASH_ENV','ENV'):
        env.pop(name,None)
    env.update(GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes',COMPOSER_NO_INTERACTION='1')
    return env
