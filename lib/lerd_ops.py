"""Verified Lerd Desktop identity and safe integration helpers (stdlib only)."""
from __future__ import annotations
import configparser
import re
import subprocess
import urllib.request

FLATPAK_REF = 'https://lerd.sh/lerd.flatpakref'


def parse_flatpakref(content: bytes) -> str:
    """Extract the publisher-declared application ID, not an inferred package name."""
    if len(content) > 65536 or b'\x00' in content:
        raise ValueError('Invalid Flatpak reference content')
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(content.decode('utf-8'))
    except (UnicodeError, configparser.Error) as exc:
        raise ValueError('Invalid Flatpak reference format') from exc
    if not parser.has_section('Flatpak Ref') or parser.getboolean('Flatpak Ref', 'IsRuntime', fallback=False):
        raise ValueError('Expected a Flatpak application reference')
    identity = parser.get('Flatpak Ref', 'Name', fallback='')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,}', identity):
        raise ValueError('Invalid application ID in official Flatpak reference')
    return identity


def official_desktop_id(*, timeout=15) -> str:
    request = urllib.request.Request(FLATPAK_REF, headers={'User-Agent':'LinuxAutomationToolkit/3'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.url != FLATPAK_REF:
            raise ValueError('Unexpected Flatpak reference origin')
        contents = response.read(65537)
    return parse_flatpakref(contents)


def desktop_installed(identifier: str) -> bool:
    try:
        result = subprocess.run(['flatpak','info','--user','--show-ref',identifier],
                                capture_output=True,text=True,timeout=20)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
