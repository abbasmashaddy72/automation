"""Private local keys and live loopback authentication checks (no proxy)."""

from __future__ import annotations
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


def safe_path(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError("Key path must be absolute")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("Symlink key path is forbidden")
    return path


def validate_key(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value):
        raise ValueError(
            "Key must contain 32–256 ASCII letters, digits, underscores or hyphens"
        )
    return value


def read(path):
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or st.st_mode & 0o077
            or st.st_nlink != 1
        ):
            raise ValueError(
                "Key must be a private regular file owned by the current user (0600)"
            )
        return validate_key(stream.read(258).strip())


def save(path, value, *, replace=False):
    path = safe_path(path)
    source = Path(__file__).resolve().parents[1]
    if path == source or source in path.resolve().parents:
        raise ValueError("Store API keys outside the toolkit source tree")
    validate_key(value)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
        raise ValueError("Key directory must be owned by this user with mode 0700")
    if path.exists():
        read(path)
        if not replace:
            return False
    fd, stage = tempfile.mkstemp(prefix=".key-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(stage, path)
        else:
            os.link(stage, path)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
    return True


def copy_key(value):
    cmd = None
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmd = ["wl-copy", "--type", "text/plain"]
    elif os.environ.get("DISPLAY") and shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif os.environ.get("DISPLAY") and shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    if cmd:
        try:
            if (
                subprocess.run(
                    cmd, input=value, text=True, capture_output=True, timeout=5
                ).returncode
                == 0
            ):
                print("API key copied to the session clipboard.")
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Explicit copy action may reveal the key only on a controlling terminal.
    try:
        with open("/dev/tty", "w") as terminal:
            terminal.write("Private API key (select to copy): " + value + "\n")
        print("Key shown on the controlling terminal only.")
        return 0
    except OSError:
        print(
            "No session clipboard or controlling terminal available. Key was not printed."
        )
        return 3


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def verify_key(backend, key, host="127.0.0.1", port=None):
    """Verify the protected model endpoint without returning credentials or payloads."""
    validate_key(key)
    base = ai_health.endpoint(
        backend, host, ai_health.DEFAULT_PORTS[backend] if port is None else port
    )
    url = base.split("/health")[0] + "/v1/models" if backend == "llamacpp" else base
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(value):
        headers = {"Authorization": "Bearer " + value} if value else {}
        try:
            with opener.open(
                urllib.request.Request(url, headers=headers), timeout=5
            ) as response:
                body = response.read(65537)
                if len(body) > 65536:
                    raise ValueError("Authentication response too large")
                return response.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            return code, None

    good, payload = request(key)
    bad, _ = request("invalid-" + secrets.token_hex(24))
    absent, _ = request(None)
    ok = (
        good == 200
        and isinstance(payload, dict)
        and isinstance(payload.get("data"), list)
        and bad in (401, 403)
        and absent in (401, 403)
    )
    return ok, (good, bad, absent)


def test_endpoint(backend, path, host="127.0.0.1", port=None):
    if backend not in ("llamacpp", "vllm", "jan"):
        print("Native API-key enforcement is not configured for this backend.")
        return 3
    ai_health.endpoint(
        backend, host, ai_health.DEFAULT_PORTS[backend] if port is None else port
    )
    key = read(path)
    try:
        ok, (good, bad, absent) = verify_key(backend, key, host, port)
    except (OSError, ValueError):
        print("Authentication test failed: endpoint unavailable or invalid response.")
        return 3
    print(
        f"Live authentication: valid HTTP {good}; invalid HTTP {bad}; absent HTTP {absent}."
    )
    print(
        "Enforcement verified on /v1/models."
        if ok
        else "Authentication enforcement NOT verified."
    )
    return 0 if ok else 5
