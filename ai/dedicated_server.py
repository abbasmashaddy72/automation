#!/usr/bin/env python3
"""Dedicated, single-process llama.cpp server integration for the original toolkit.

Preserves existing models/services and requires opt-in for changes. No drive erasure,
no driver upgrades, no installation of Ollama/vLLM, no shell execution of URLs.
"""

from __future__ import annotations
import argparse
import datetime
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib import request, parse, error

from hardware_inventory import desktop_details, inventory, run
from llama_launcher import command as launcher_command
import server_storage

HERE = Path(__file__).resolve().parent
ROOT = Path("/srv/ai")
SOURCE = Path("/opt/automation-ai/llama.cpp")
BIN = SOURCE / "build/bin/llama-server"
BUILD_META = SOURCE / "automation-build.json"
ETC = Path("/etc/automation-ai")
CFG = ETC / "llamacpp.json"
KEY = ETC / "api-key"
LAUNCH = Path("/usr/local/lib/automation-ai/llama_launcher.py")
PROXY_CODE = Path("/usr/local/lib/automation-ai/lan_proxy.py")
SERVICE = Path("/etc/systemd/system/automation-llamacpp.service")
GATEWAY = Path("/etc/systemd/system/automation-ai-api.service")
MARK = "# Managed by Automation Toolkit dedicated llama.cpp server v2.1"
MODEL_CATALOG = {
    "general": {
        "name": "Qwen2.5 1.5B Instruct Q4_K_M",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    "coding": {
        "name": "Qwen2.5 Coder 1.5B Q4_K_M",
        "filename": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/f86cb2c1fa58255f8052cc32aeede1b7482d4361/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    },
}


# Catalog entries identify reviewed single-file GGUFs. Runtime estimates are calculated separately.
MODEL_SUGGESTIONS = {
    **{kind: {**entry, "layers": 28} for kind, entry in MODEL_CATALOG.items()},
    "reasoning": {
        "name": "DeepSeek-R1-Distill-Qwen 1.5B Q4_K_M",
        "filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/9cc28b17e86fa2415fcb070f8ee5ec27c965aa61/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "layers": 28,
    },
    "balanced": {
        "name": "Qwen3 4B Instruct 2507 Q4_K_M",
        "filename": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "layers": 36,
    },
    "compact_2026": {
        "name": "Qwen3.5 0.8B Q4_K_M (Unsloth GGUF)",
        "filename": "Qwen3.5-0.8B-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/6ab461498e2023f6e3c1baea90a8f0fe38ab64d0/Qwen3.5-0.8B-Q4_K_M.gguf",
        "layers": 24,
        "year": 2026,
        "runtime_note": "Requires a llama.cpp build with Qwen3.5 support",
    },
    "general_2026": {
        "name": "Qwen3.5 2B Q4_K_M (Unsloth GGUF)",
        "filename": "Qwen3.5-2B-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376be1edb4d416d56da11e5397a961aca8ae/Qwen3.5-2B-Q4_K_M.gguf",
        "layers": 24,
        "year": 2026,
        "runtime_note": "Requires a llama.cpp build with Qwen3.5 support",
    },
    "balanced_2026": {
        "name": "Qwen3.5 4B Q4_K_M (Unsloth GGUF)",
        "filename": "Qwen3.5-4B-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf",
        "layers": 32,
        "year": 2026,
        "runtime_note": "Requires a llama.cpp build with Qwen3.5 support",
    },
    "deepseek_v3_distill": {
        "name": "TeichAI Qwen3 4B · DeepSeek V3.2 Speciale Math Distill Q4_K_M",
        "filename": "Qwen3-4B-Thinking-2507-DeepSeek-v3.2-Speciale-Math-Distill.q4_k_m.gguf",
        "url": "https://huggingface.co/TeichAI/Qwen3-4B-Thinking-2507-DeepSeek-v3.2-Speciale-Math-Distill-GGUF/resolve/68c0114a86d8043591ee756aa73aa72d31600c53/Qwen3-4B-Thinking-2507-DeepSeek-v3.2-Speciale-Math-Distill.q4_k_m.gguf",
        "layers": 36,
        "manual_only": True,
    },
}


MODEL_FILES = {
    "general": (
        "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        1117320736,
    ),
    "coding": (
        "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046",
        1117320768,
    ),
    "reasoning": (
        "1741e5b2d062b07acf048bf0d2c514dadf2a48f94e2b4aa0cfe069af3838ee2f",
        1117320800,
    ),
    "balanced": (
        "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
        2497281120,
    ),
    "compact_2026": (
        "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517",
        532517120,
    ),
    "general_2026": (
        "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
        1280835840,
    ),
    "balanced_2026": (
        "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
        2740937888,
    ),
    "deepseek_v3_distill": (
        "3236a5a71aa680bca4e9052cc97931fba83e43d26f6cef02d517e94ff1553303",
        2497281120,
    ),
}


def action(argv, *, root=False, check=True, capture=False, timeout=120):
    privileged = root and os.geteuid() != 0
    if privileged and os.environ.get("AUTOMATION_DASHBOARD_TTY") == "1":
        cached = subprocess.run(
            ["sudo", "-n", "-v"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if cached.returncode:
            print("Dashboard authentication: pending", flush=True)
            verified = subprocess.run(["sudo", "-v"], timeout=180, check=False)
            if verified.returncode:
                print("Dashboard authentication: failed", flush=True)
                verified.check_returncode()
            print("Dashboard authentication: complete", flush=True)
    cmd = (["sudo"] if privileged else []) + list(map(str, argv))
    return subprocess.run(
        cmd, check=check, text=True, timeout=timeout, capture_output=capture
    )


def install_owned(path, content, mode="0644"):
    old = None
    try:
        result = action(["cat", path], root=True, capture=True, check=False)
        old = result.stdout if result.returncode == 0 else None
    except OSError:
        pass
    if old == content:
        return False
    if old is not None and not old.startswith(MARK):
        raise RuntimeError(f"Existing unmanaged file not overwritten: {path}")
    if old is not None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        action(["cp", "-a", path, str(path) + ".backup-" + stamp], root=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "source"
        tmp.write_text(content)
        action(["install", "-D", "-m", mode, tmp, path], root=True)
    return True


def load_config():
    if not CFG.is_file():
        raise RuntimeError("No managed llama.cpp config; run install first")
    cfg = json.loads(CFG.read_text())
    return cfg


def store_config(cfg):
    # Marker is stored as a JSON field and the ownership check recognizes it.
    old = None
    try:
        old = action(["cat", CFG], root=True, capture=True, check=False).stdout
    except OSError:
        pass
    if old:
        try:
            if json.loads(old).get("_managed") != MARK:
                raise RuntimeError("Foreign AI configuration, refusing overwrite")
        except ValueError:
            raise RuntimeError("Invalid existing config; refusing overwrite")
    cfg["_managed"] = MARK
    if old and json.loads(old) == cfg:
        return False
    if old:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
        action(["cp", "-a", CFG, str(CFG) + ".backup-" + stamp], root=True)
    with tempfile.TemporaryDirectory() as td:
        temp = Path(td) / "config"
        temp.write_text(json.dumps(cfg, indent=2) + "\n")
        action(["install", "-D", "-m", "0644", temp, CFG], root=True)
    return True


def host_support():
    sys.path.insert(0, str(HERE.parent / "lib"))
    from automation import platform_info
    from providers import capability

    info = platform_info()
    reasons = list(capability(info)["warnings"])
    if info["init"] != "systemd" or not shutil.which("systemctl"):
        reasons.append(
            "An active systemd system manager is required for managed installation"
        )
    if info["container"]:
        reasons.append("Managed installation requires a host or VM")
    if not info["manager"] or not shutil.which(info["manager"]):
        reasons.append("Native package manager unavailable")
    return info, reasons


def disk(path):
    return server_storage.inspect(path)


def lan():
    try:
        route = json.loads(run(["ip", "-j", "route", "get", "1.1.1.1"]))[0]
        device = route["dev"]
        src = route.get("prefsrc") or route.get("src")
        addresses = json.loads(run(["ip", "-j", "address", "show", "dev", device]))[0][
            "addr_info"
        ]
        for a in addresses:
            if a.get("local") == src and a.get("family") == "inet":
                net = ipaddress.ip_network(f"{src}/{a['prefixlen']}", strict=False)
                if not ipaddress.ip_address(src).is_private:
                    raise ValueError("Not private LAN")
                return {"device": device, "ip": src, "subnet": str(net)}
    except (IndexError, KeyError, ValueError, TypeError):
        pass
    return None


def detect_backend(info):
    sysname = info["system"]["os_id"]
    nvidia = [
        g
        for g in info["gpus"]
        if g.get("vendor") == "NVIDIA" and g.get("dedicated_vram_mib")
    ]
    if sys.platform == "darwin":
        return "metal"
    if nvidia and run(["nvidia-smi", "-L"]):
        return "cuda"
    if any(g.get("vendor") == "AMD" for g in info["gpus"]):
        if shutil.which("hipcc") and run(["rocminfo"]):
            return "hip"
        if shutil.which("vulkaninfo") and run(["vulkaninfo", "--summary"]):
            return "vulkan"
    return "cpu"


def profile(info, mode="auto"):
    if mode not in ("auto", "maximum", "balanced", "low-memory", "multi-user"):
        raise ValueError("Unknown performance profile")
    gpu = max(
        (
            int(g.get("dedicated_vram_mib") or 0)
            for g in info["gpus"]
            if g.get("vendor") == "NVIDIA"
        ),
        default=0,
    )
    ram = int(info["ram"].get("total_bytes") or 0)
    cores = int(
        info["cpu"].get("physical_cores") or info["cpu"].get("logical_threads") or 2
    )
    base = {
        "context": 2048 if gpu and gpu <= 6144 else 4096,
        "threads": max(1, min(cores, 32)),
        "batch": 512,
        "ubatch": 128 if gpu and gpu <= 4096 else 256,
        "parallel": 1,
        "gpu_layers": "auto" if gpu else "0",
        "flash_attn": "auto",
        "model_alias": "shared-ai",
        "profile": mode,
    }
    if mode == "maximum":
        base.update(batch=1024, ubatch=256, context=min(4096, base["context"] * 2))
    elif mode == "low-memory":
        base.update(context=1024, batch=256, ubatch=64, parallel=1)
    elif mode == "multi-user":
        base.update(parallel=2 if (gpu > 6144 or ram > 24 * 1024**3) else 1, batch=512)
    return base


def check_conflicts(migrate=False, commit=False):
    units = ["ollama", "vllm", "automation-ai-api"]
    active = [x for x in units if run(["systemctl", "is-active", x]) == "active"]
    unmanaged = [u for u in active if u != "automation-ai-api"]
    if unmanaged:
        raise RuntimeError(
            "Unmanaged inference service active: "
            + ", ".join(unmanaged)
            + ". Stop it manually"
        )
    if "automation-ai-api" in active:
        present = action(["cat", GATEWAY], root=True, capture=True, check=False).stdout
        if present.startswith(MARK):
            # The active gateway already belongs to this llama.cpp release.
            # It is not a legacy service; reruns must be idempotent.
            return active
        if "Managed by Automation Toolkit dedicated AI server v2" not in present:
            raise RuntimeError("Existing API gateway is not toolkit-owned")
        if not migrate:
            raise RuntimeError(
                "Legacy gateway active. Use --migrate-legacy for approved replacement."
            )
        if commit:
            action(["systemctl", "disable", "--now", "automation-ai-api"], root=True)
        # Old managed unit will be backed up before replacement.
    return active


def dependencies(backend, *, build=True, lan_api=False):
    if build and backend == "cuda" and not shutil.which("nvcc"):
        raise RuntimeError("Install a reviewed CUDA compiler separately")
    if build and backend == "hip" and not shutil.which("hipcc"):
        raise RuntimeError("Install a reviewed ROCm compiler separately")
    if (
        build
        and backend == "vulkan"
        and not all(shutil.which(tool) for tool in ("glslc", "vulkaninfo"))
    ):
        raise RuntimeError(
            "Install the Vulkan SDK and vulkaninfo from your distro before choosing Vulkan"
        )
    flags = ["--with-ai-build"] if build else []
    if lan_api:
        flags.append("--with-ai-lan")
    try:
        action(
            [
                "bash",
                HERE.parent / "scripts/prerequisites.sh",
                "install",
                "--runtime-only",
                "--with-ai-server",
                *flags,
                "--without-ui",
                "--yes",
            ],
            timeout=1800,
        )
    except subprocess.SubprocessError as exc:
        raise RuntimeError(
            "Native prerequisites failed; review the package manager output before retrying"
        ) from exc


def build_backend(backend, update=False, *, rebuild=False):
    if rebuild and not BUILD_META.is_file():
        raise RuntimeError("Reinstall requires a toolkit-owned source build")
    if BIN.is_file() and not (update or rebuild):
        if not BUILD_META.is_file():
            raise RuntimeError(
                "Existing build is not toolkit-managed; use a fresh source directory"
            )
        existing = json.loads(BUILD_META.read_text())
        if existing.get("backend") != backend:
            raise RuntimeError(
                "Existing backend differs; explicitly use --update-source"
            )
        print(
            "Reusing existing llama-server with backend",
            backend,
            "revision",
            existing.get("revision"),
        )
        return
    src = SOURCE
    if (src / ".git").is_dir():
        origin = (
            action(
                ["git", "-C", src, "remote", "get-url", "origin"],
                root=True,
                capture=True,
            )
            .stdout.strip()
            .rstrip("/")
        )
        if origin not in (
            "https://github.com/ggml-org/llama.cpp",
            "https://github.com/ggml-org/llama.cpp.git",
        ):
            raise RuntimeError("Unexpected llama.cpp source origin")
        dirty = action(
            ["git", "-C", src, "status", "--porcelain", "--untracked-files=no"],
            root=True,
            capture=True,
        ).stdout.strip()
        # Build dir is ignored by upstream; refuse tracked source modifications.
        if dirty:
            raise RuntimeError("Local llama.cpp changes detected; refusing upgrade")
        if update:
            action(["git", "-C", src, "pull", "--ff-only"], root=True, timeout=600)
    elif src.exists():
        raise RuntimeError("Unmanaged source tree exists; will not overwrite")
    else:
        action(["install", "-d", "-m", "0755", src.parent], root=True)
        action(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/ggml-org/llama.cpp",
                src,
            ],
            root=True,
            timeout=600,
        )
    cmake = {
        name: [
            "-DGGML_" + feature + "=" + ("ON" if feature == selected else "OFF")
            for feature in ("CUDA", "HIP", "VULKAN", "METAL")
        ]
        for name, selected in (
            ("cpu", None),
            ("cuda", "CUDA"),
            ("hip", "HIP"),
            ("vulkan", "VULKAN"),
            ("metal", "METAL"),
        )
    }[backend]
    generator = (
        [] if (src / "build/CMakeCache.txt").exists() else ["-G", "Unix Makefiles"]
    )
    action(
        [
            "cmake",
            "-S",
            src,
            "-B",
            src / "build",
            *generator,
            "-DCMAKE_BUILD_TYPE=Release",
            "-DLLAMA_BUILD_TESTS=OFF",
            "-DLLAMA_OPENSSL=OFF",
            "-DLLAMA_BUILD_APP=OFF",
            "-DLLAMA_BUILD_UI=OFF",
            "-DLLAMA_USE_PREBUILT_UI=OFF",
            "-DLLAMA_CONNECT=OFF",
            "-DLLAMA_SUBPROCESS=OFF",
            *cmake,
        ],
        root=True,
        timeout=600,
    )
    action(
        [
            "cmake",
            "--build",
            src / "build",
            "--config",
            "Release",
            "--target",
            "llama-server",
            "-j",
            str(min(os.cpu_count() or 2, 4)),
        ],
        root=True,
        timeout=7200,
    )
    if not BIN.is_file():
        raise RuntimeError("llama-server binary missing after build")
    revision = action(
        ["git", "-C", src, "rev-parse", "HEAD"], root=True, capture=True
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "build-meta"
        out.write_text(
            json.dumps({"backend": backend, "revision": revision}, indent=2) + "\n"
        )
        action(["install", "-m", "0644", out, BUILD_META], root=True)


def model_path(root, model):
    p = Path(model)
    if not p.is_absolute():
        p = Path(root) / "models" / model
    resolved = p.resolve(strict=True)
    if not resolved.is_file() or Path(root).resolve() not in resolved.parents:
        raise RuntimeError(
            "GGUF must be a file stored in the selected AI data directory"
        )
    if resolved.suffix.lower() != ".gguf" or not gguf_header(resolved):
        raise RuntimeError("Model is not a GGUF file")
    return str(p)


def ensure_account():
    if run(["id", "-u", "ai-llama"]):
        return
    action(
        [
            "useradd",
            "--system",
            "--home-dir",
            "/nonexistent",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            "ai-llama",
        ],
        root=True,
    )


def prepare_model_store(root):
    ensure_account()
    base = Path(root) / "models"
    owner = os.environ.get("SUDO_USER") if os.geteuid() == 0 else os.environ.get("USER")
    if not owner or not re.fullmatch("[a-z_][a-z0-9_-]{0,31}", owner):
        raise RuntimeError(
            "Cannot determine an ordinary administrator to own model downloads"
        )
    if not base.exists():
        action(
            ["install", "-d", "-m", "02770", "-o", owner, "-g", "ai-llama", base],
            root=True,
        )
    elif base.is_symlink() or not base.is_dir():
        raise RuntimeError("Model storage directory is unsafe")
    return base


def allow_service_read(path):
    # Do not take ownership or delete user data; grant only a known local group.
    action(["chgrp", "ai-llama", path], root=True)
    action(["chmod", "0640", path], root=True)


def acquire_model(
    root,
    choice="general",
    url=None,
    sha256=None,
    allow_oversized=False,
    *,
    size_bytes=None,
):
    from models import HTTPSRedirect, https_url

    if choice in MODEL_CATALOG and not url:
        entry = MODEL_CATALOG[choice]
        url = entry["url"]
        filename = entry["filename"]
    else:
        if not url or not sha256 or not re.fullmatch("[0-9a-fA-F]{64}", sha256):
            raise RuntimeError(
                "Custom model download needs --model-url and an independently verified --sha256"
            )
        filename = Path(parse.urlsplit(url).path).name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,190}\.gguf", filename):
        raise RuntimeError("Unsafe model filename")
    https_url(url)
    if sha256 is not None and not re.fullmatch("[0-9a-fA-F]{64}", sha256):
        raise RuntimeError("Provide an independently verified --sha256")
    path = Path(root) / "models" / filename
    receipt = path.with_name(filename + ".sha256")
    if any(part.is_symlink() for part in (path, receipt, *path.parents)):
        raise RuntimeError("Model and receipt paths must not contain symlinks")
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Unexpected existing model path")
        expected = (
            sha256.lower()
            if sha256
            else (
                receipt.read_text().strip().lower()
                if receipt.is_file() and not receipt.is_symlink()
                else None
            )
        )
        if not expected or not re.fullmatch("[0-9a-f]{64}", expected):
            raise RuntimeError(
                "Existing GGUF has no SHA-256 receipt. Use explicit --model path or independently verify it; refusing silent reuse"
            )
        if size_bytes is not None and path.stat().st_size != size_bytes:
            raise RuntimeError("Existing model differs from reviewed size")
        digest = sha_file(path)
        if digest != expected:
            raise RuntimeError("Existing model SHA-256 differs from receipt/reference")
        if not gguf_header(path):
            raise RuntimeError("Existing model header is invalid")
        allow_service_read(path)
        print("Reusing existing verified GGUF:", path)
        return str(path)
    if receipt.exists():
        raise RuntimeError(
            "An existing receipt has no model; review it before downloading"
        )
    if not sha256 or size_bytes is None or not 4 <= size_bytes <= 100 * 1024**3:
        raise RuntimeError(
            "New model downloads require independently verified --sha256 and --size-bytes"
        )
    size = size_bytes
    if shutil.disk_usage(root).free < size + 2 * 1024**3:
        raise RuntimeError("Insufficient free SSD space")
    hw = inventory()
    ram = hw["ram"].get("total_bytes") or 0
    dedicated = sum(int(g.get("dedicated_vram_mib") or 0) * 1024**2 for g in hw["gpus"])
    if not allow_oversized and size > max(3 * 1024**3, int((ram + dedicated) * 0.7)):
        raise RuntimeError(
            "Model is too large for conservative RAM+dedicated VRAM budget; pass --allow-oversized only if you accept CPU/offload/swapping risk"
        )
    dest = prepare_model_store(root)
    expected = sha256.lower()
    opener = request.build_opener(request.ProxyHandler({}), HTTPSRedirect())
    with tempfile.TemporaryDirectory(prefix=".gguf-download-", dir=dest) as stage:
        tmp = Path(stage) / filename
        req = request.Request(url, headers={"User-Agent": "AI-Server-Automation/2.1"})
        digest = hashlib.sha256()
        n = 0
        with opener.open(req, timeout=120) as response, tmp.open("xb") as output:
            while True:
                part = response.read(min(4 * 1024 * 1024, size - n + 1))
                if not part:
                    break
                n += len(part)
                if n > size:
                    raise RuntimeError("Download exceeded reviewed model size")
                output.write(part)
                digest.update(part)
        if n != size or digest.hexdigest() != expected or not gguf_header(tmp):
            raise RuntimeError("Model size, SHA-256 or header verification failed")
        os.link(tmp, path, follow_symlinks=False)
        with receipt.open("x") as stream:
            stream.write(expected + "\n")
        allow_service_read(path)
    print("Verified GGUF download:", path, "SHA-256:", expected)
    return str(path)


def gguf_header(path):
    with Path(path).open("rb") as stream:
        return stream.read(4) == b"GGUF"


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while data := f.read(4 * 1024 * 1024):
            h.update(data)
    return h.hexdigest()


def unit(root):
    root = server_storage.checked_root(root)
    return "\n".join(
        [
            MARK,
            "[Unit]",
            "Description=One shared llama.cpp AI inference server",
            "After=network-online.target",
            "Wants=network-online.target",
            f"RequiresMountsFor={root}",
            "[Service]",
            "Type=simple",
            "User=ai-llama",
            "Group=ai-llama",
            "ExecStart=/usr/bin/python3 " + str(LAUNCH),
            "Restart=on-failure",
            "RestartSec=4",
            "TimeoutStartSec=240",
            "NoNewPrivileges=true",
            "ProtectSystem=full",
            "PrivateTmp=true",
            "LimitNOFILE=65536",
            "OOMScoreAdjust=100",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def gateway_unit(address, subnet):
    return "\n".join(
        [
            MARK,
            "[Unit]",
            "Description=Authenticated LAN API gateway for llama.cpp",
            "After=automation-llamacpp.service",
            "Requires=automation-llamacpp.service",
            "[Service]",
            "User=ai-llama",
            "Group=ai-llama",
            f"ExecStart=/usr/bin/python3 {PROXY_CODE} --listen {address} --port 11435 --subnet {subnet} --key-file {KEY}",
            "Restart=on-failure",
            "RestartSec=4",
            "NoNewPrivileges=true",
            "ProtectSystem=full",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def ensure_service(cfg, root, force_restart=False):
    launcher_command(cfg)
    ensure_account()
    prepare_model_store(root)
    allow_service_read(cfg["model"])
    launcher_changed = install_owned(
        LAUNCH, MARK + "\n" + (HERE / "llama_launcher.py").read_text(), "0755"
    )
    cfg_changed = store_config(cfg)
    unit_changed = install_owned(SERVICE, unit(root))
    active = run(["systemctl", "is-active", SERVICE.name]) == "active"
    changed = launcher_changed or cfg_changed or unit_changed or force_restart
    if run(["systemctl", "is-enabled", SERVICE.name]) != "enabled":
        action(["systemctl", "enable", SERVICE.name], root=True)
    elif not active or unit_changed:
        action(["systemctl", "daemon-reload"], root=True)
    if not active or changed:
        action(["systemctl", "restart" if active else "start", SERVICE.name], root=True)
    else:
        print(
            "Existing shared llama.cpp config unchanged; preserving in-flight requests"
        )
    if run(["systemctl", "is-active", SERVICE.name]) != "active":
        raise RuntimeError(
            "llama.cpp service failed: journalctl -u automation-llamacpp"
        )
    if run(["systemctl", "is-enabled", SERVICE.name]) != "enabled":
        raise RuntimeError(
            "llama.cpp is active, but startup at boot could not be verified"
        )
    print("Managed llama.cpp is running as a systemd service and enabled at boot.")


def wait_health(port=8080, timeout=150):
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
        try:
            client.request("GET", "/health")
            response = client.getresponse()
            if response.status == 200:
                payload = json.loads(response.read(8193))
                if isinstance(payload, dict) and payload.get("status") == "ok":
                    return True
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            client.close()
        time.sleep(3)
    return False


def gateway_setup(root):
    net = lan()
    if not net:
        raise RuntimeError("No private IPv4 LAN discovered; gateway not installed")
    if not KEY.exists():
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "key"
            tmp.write_text(secrets.token_urlsafe(48) + "\n")
            action(
                [
                    "install",
                    "-D",
                    "-m",
                    "0640",
                    "-o",
                    "root",
                    "-g",
                    "ai-llama",
                    tmp,
                    KEY,
                ],
                root=True,
            )
    else:
        st = KEY.stat()
        if st.st_uid != 0 or st.st_mode & 0o007:
            raise RuntimeError(
                "Existing API key permissions are unsafe; refusing reuse"
            )
        action(["chgrp", "ai-llama", KEY], root=True)
        action(["chmod", "0640", KEY], root=True)
    proxy_changed = install_owned(
        PROXY_CODE, MARK + "\n" + (HERE / "lan_proxy.py").read_text(), "0755"
    )
    # Older toolkit-owned gateway units may have a different marker; backed up explicitly.
    old = action(["cat", GATEWAY], root=True, check=False, capture=True).stdout
    if old and "Managed by Automation Toolkit dedicated AI server v2" in old:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        action(["cp", "-a", GATEWAY, str(GATEWAY) + ".backup-" + stamp], root=True)
        action(["rm", "-f", GATEWAY], root=True)
    gateway_changed = install_owned(GATEWAY, gateway_unit(net["ip"], net["subnet"]))
    if (
        proxy_changed
        or gateway_changed
        or run(["systemctl", "is-active", "automation-ai-api"]) != "active"
    ):
        action(["systemctl", "daemon-reload"], root=True)
        action(["systemctl", "enable", "--now", "automation-ai-api"], root=True)
        action(["systemctl", "restart", "automation-ai-api"], root=True)
    else:
        print(
            "Authenticated LAN gateway already configured; preserving active connections"
        )
    print("Authenticated OpenAI API: http://" + net["ip"] + ":11435/v1")


def temperature_ok(max_c=83):
    value = run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]
    )
    readings = []
    for v in value.splitlines():
        try:
            readings.append(int(v.strip()))
        except ValueError:
            pass
    return not readings or max(readings) < max_c


def tune_live(args):
    """Benchmark candidates on the actual server; rollback if any candidate fails.

    Cap concurrency for small VRAM; do not change device clocks, power or drivers.
    """
    if run(["systemctl", "is-active", "automation-llamacpp"]) != "active":
        raise RuntimeError("llama.cpp service is not active")
    current = load_config()
    candidates = [dict(current)]
    for context in (1024, 2048, 4096):
        for ubatch in (64, 128):
            if context > max(4096, int(current["context"])):
                continue
            if context == current["context"] and ubatch == current["ubatch"]:
                continue
            candidate = dict(
                current,
                context=context,
                ubatch=ubatch,
                batch=max(256, int(current["batch"])),
                parallel=current["parallel"],
            )
            candidates.append(candidate)
    # Guarantee bounded trial count even when users manually supply large ctx.
    candidates = candidates[:6]
    from llama_benchmark import benchmark

    rows = []
    baseline = None
    selected = dict(current)
    try:
        for i, c in enumerate(candidates):
            if not temperature_ok():
                raise RuntimeError("GPU temperature exceeds 83°C; aborting tune")
            if i:
                store_config(c)
                action(["systemctl", "restart", "automation-llamacpp"], root=True)
                if not wait_health(port=c["port"], timeout=180):
                    rows.append(
                        {
                            "context": c["context"],
                            "ubatch": c["ubatch"],
                            "error": "service not healthy",
                        }
                    )
                    continue
            try:
                measurement = benchmark(
                    "http://127.0.0.1:" + str(c["port"]), c["alias"], args.repeats
                )
                speed = measurement["median_generation_tokens_per_second"]
                spread = measurement["relative_spread"]
                if spread > 0.5:
                    raise RuntimeError("unstable output speed")
                record = {
                    "context": c["context"],
                    "ubatch": c["ubatch"],
                    "tokens_per_second": speed,
                    "ttft_seconds": measurement["median_ttft_seconds"],
                    "relative_spread": spread,
                }
                rows.append(record)
                if i == 0:
                    baseline = record
            except (OSError, ValueError, RuntimeError) as e:
                rows.append(
                    {"context": c["context"], "ubatch": c["ubatch"], "error": str(e)}
                )
        stable = [r for r in rows if r.get("tokens_per_second")]
        if not stable or baseline is None:
            raise RuntimeError("No stable successful baseline and candidates")

        # 80% generation throughput + 20% inverse TTFT; speed improvement
        # threshold avoids changing config due to benchmark noise.
        def score(r):
            return 0.8 * r["tokens_per_second"] + 0.2 / (r["ttft_seconds"] + 0.01)

        best = max(stable, key=score)
        if score(best) > score(baseline) * 1.05:
            selected = next(
                c
                for c in candidates
                if c["context"] == best["context"] and c["ubatch"] == best["ubatch"]
            )
        else:
            best = baseline
        result = {
            "candidates": rows,
            "selected": {"context": selected["context"], "ubatch": selected["ubatch"]},
            "baseline": baseline,
            "winner": best,
            "reason": "Measured stable generation/TTFT score with 5% improvement threshold",
        }
        target = Path(args.output or "ai-tuning.json").expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        print("Saved:", target)
    except BaseException:
        store_config(current)
        action(["systemctl", "restart", "automation-llamacpp"], root=True)
        raise
    # Apply verified winner only. Restore original even if final health fails.
    try:
        store_config(selected)
        action(["systemctl", "restart", "automation-llamacpp"], root=True)
        if not wait_health(port=selected["port"], timeout=180):
            raise RuntimeError("Winner not healthy")
    except BaseException:
        store_config(current)
        action(["systemctl", "restart", "automation-llamacpp"], root=True)
        raise
    return 0


def check_installed_storage(config, storage):
    if config and config["data_root"] == storage["directory"]:
        mount = config.get("storage_mount", config["data_root"])
        uuid = config.get("storage_uuid")
        if mount != storage["mount"] or (uuid and uuid != storage["uuid"]):
            raise RuntimeError(
                "Restore the configured model filesystem before writing model files"
            )


def installation(args):
    _, reasons = host_support()
    if reasons:
        raise RuntimeError("; ".join(reasons))
    root = server_storage.checked_root(args.data_root)
    check_conflicts(args.migrate_legacy, commit=False)
    i = inventory()
    backend = detect_backend(i) if args.backend == "auto" else args.backend
    if backend == "cpu" and getattr(args, "gpu_layers", 0):
        raise ValueError("Choose a GPU-capable build before setting GPU layers")
    if backend == "metal":
        raise RuntimeError(
            "Metal requires a native macOS build; use manual llama.cpp instructions"
        )
    if backend == "cuda" and not run(["nvidia-smi", "-L"]):
        raise RuntimeError("NVIDIA driver not functional")
    if backend == "hip" and not shutil.which("hipcc"):
        raise RuntimeError("ROCm compiler absent")
    # Refuse preexisting foreign service names and configurations before expensive work.
    if SERVICE.exists() and not SERVICE.read_text().startswith(MARK):
        raise RuntimeError("Foreign llama.cpp service exists")
    previous = load_config() if CFG.exists() else None
    port = getattr(args, "port", None) or (
        previous.get("port", 8080) if previous else 8080
    )
    if port != 8080 and (args.with_lan_api or GATEWAY.exists()):
        raise ValueError("The LAN gateway requires llama.cpp port 8080")
    if previous and port != previous.get("port", 8080) and not args.reconfigure:
        raise ValueError("Changing an installed port requires --reconfigure")
    if run(["systemctl", "is-active", "automation-llamacpp"]) != "active" or (
        previous and port != previous.get("port", 8080)
    ):
        import socket

        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot bind 127.0.0.1:{port}; check the existing listener"
                ) from exc
    settings = profile(i, args.profile)
    if args.model and args.model_url:
        raise RuntimeError("Select a local --model OR a --model-url, not both")
    if previous and previous.get("_managed") != MARK:
        raise RuntimeError("Foreign AI configuration, refusing to overwrite")
    if args.no_pull and not args.model:
        raise RuntimeError("--no-pull requires an existing --model")
    if (
        previous
        and previous["data_root"] != args.data_root
        and not (args.reconfigure and (args.model or args.model_url))
    ):
        raise RuntimeError(
            "Changing the installed model directory requires --reconfigure and a model selection for the new directory"
        )
    if args.mount_uuid and not server_storage.UUID.fullmatch(args.mount_uuid):
        raise ValueError("Choose a filesystem UUID from ai server storage")
    rebuild = getattr(args, "rebuild", False)
    needs_build = not BIN.exists() or args.update_source or rebuild
    preflight_done = not all(
        shutil.which(tool) for tool in ("findmnt", "lsblk", "mount")
    )
    if preflight_done:
        dependencies(backend, build=needs_build, lan_api=args.with_lan_api)
    if args.mount_uuid:
        mounted = server_storage.is_mount(root)
        if previous and previous["data_root"] == str(root):
            if mounted:
                check_installed_storage(previous, disk(root))
            elif (previous.get("storage_mount"), previous.get("storage_uuid")) != (
                str(root),
                args.mount_uuid.lower(),
            ):
                raise RuntimeError(
                    "Use a different --data-root to move an installed model store to another disk"
                )
        if not mounted:
            server_storage.selected(args.mount_uuid)
    else:
        check_installed_storage(previous, disk(root))
    if not args.model and (not previous or args.reconfigure or args.model_url):
        model_name = (
            Path(parse.urlsplit(args.model_url).path).name
            if args.model_url
            else MODEL_CATALOG[args.model_choice]["filename"]
        )
        if not (root / "models" / model_name).is_file() and not (
            args.sha256
            and re.fullmatch("[0-9a-fA-F]{64}", args.sha256)
            and args.size_bytes
            and 4 <= args.size_bytes <= 100 * 1024**3
        ):
            raise RuntimeError(
                "Supply an existing --model or a reviewed --sha256 and --size-bytes"
            )
    if args.model and not args.mount_uuid:
        model_path(root, args.model)
    if not preflight_done:
        dependencies(backend, build=needs_build, lan_api=args.with_lan_api)
    if args.mount_uuid:
        storage = server_storage.mount_selected(root, args.mount_uuid, action, MARK)
    else:
        action(["mkdir", "-p", "--", root], root=True)
        storage = disk(root)

    check_installed_storage(previous, storage)
    if args.model:
        selected = model_path(args.data_root, args.model)
    elif previous and not args.reconfigure and not args.model_url:
        selected = model_path(args.data_root, previous["model"])
        print("Preserving previously selected GGUF on repeat installation:", selected)
    else:
        selected = acquire_model(
            args.data_root,
            args.model_choice,
            args.model_url,
            args.sha256,
            args.allow_oversized,
            size_bytes=args.size_bytes,
        )
    if rebuild:
        build_backend(backend, args.update_source, rebuild=True)
    else:
        build_backend(backend, args.update_source)
    cfg = {
        "binary": str(BIN),
        "data_root": args.data_root,
        "model": selected,
        "alias": settings["model_alias"],
        "context": settings["context"],
        "threads": settings["threads"],
        "batch": settings["batch"],
        "ubatch": settings["ubatch"],
        "parallel": settings["parallel"],
        "gpu_layers": str(args.gpu_layers)
        if getattr(args, "gpu_layers", None) is not None
        else settings["gpu_layers"]
        if backend != "cpu"
        else "0",
        "storage_mount": storage["mount"],
        "storage_uuid": storage["uuid"],
        "flash_attn": settings["flash_attn"],
        "port": port,
        "backend": backend,
        "profile": args.profile,
    }
    if (
        previous
        and previous.get("context_manual") is True
        and previous["model"] == selected
        and previous.get("backend") == backend
    ):
        cfg.update(context=previous["context"], context_manual=True)
    check_conflicts(args.migrate_legacy, commit=True)
    if previous and not args.reconfigure and not args.model and not args.model_url:
        cfg = previous
        print(
            "Preserving previous hardware settings; supply --reconfigure for explicit profile changes"
        )
    ensure_service(cfg, args.data_root, force_restart=args.update_source or rebuild)
    if not wait_health(port=cfg["port"]):
        raise RuntimeError(
            "Model failed to become ready; check journalctl -u automation-llamacpp"
        )
    if args.with_lan_api:
        gateway_setup(args.data_root)
    if not args.skip_smoke:
        from llama_benchmark import run_once

        print(
            "First real GPU/CPU inference smoke test:",
            run_once(base=f"http://127.0.0.1:{port}", alias=cfg["alias"]),
        )
        if (
            args.profile == "auto"
            and not args.skip_tune
            and not cfg.get("context_manual")
            and (not previous or args.reconfigure or args.update_source)
        ):
            try:
                tune_live(args)
            except Exception as exc:
                print(
                    "WARNING: Auto-tuning unavailable or unstable; baseline preserved:",
                    exc,
                    file=sys.stderr,
                )
    print(
        "SUCCESS: one shared llama.cpp service. Model:", selected, "Backend:", backend
    )


def gpu_planning_ready(backend):
    if backend not in ("cuda", "hip", "vulkan"):
        return False
    if BIN.is_file():
        try:
            if json.loads(BUILD_META.read_text()).get("backend") == backend:
                return True
        except (OSError, ValueError, AttributeError):
            pass
    compiler = {"cuda": "nvcc", "hip": "hipcc", "vulkan": "glslc"}[backend]
    return bool(shutil.which(compiler))


def assess_models(info, storage, backend, layers, *, gpu_ready):
    gib = 1024**3
    cpu = info.get("cpu", {})
    arch = info.get("system", {}).get("architecture") or cpu.get("architecture")
    threads = cpu.get("logical_threads") or 0
    flags = set(cpu.get("supported_instruction_flags") or ())
    fast_cpu = threads >= 4 and bool(flags & {"avx2", "avx512f", "asimd", "neon"})
    ram = (info.get("ram", {}).get("available_bytes") or 0) / gib
    disk = storage.get("free_gib") or 0
    cards = info.get("gpus", [])
    gpu_vendor = {"cuda": "NVIDIA", "hip": "AMD"}.get(backend)
    eligible = (
        [card for card in cards if card.get("vendor") == gpu_vendor]
        if gpu_vendor
        else []
    )
    displayed = eligible or cards
    gpu = max(
        displayed, key=lambda card: card.get("available_vram_mib") or 0, default={}
    )
    vram = gpu.get("available_vram_mib")
    # Available VRAM has to be measured for the selected GPU and backend.
    usable_vram = max(0, (vram or 0) / 1024 - 0.75) if gpu_ready and eligible else 0
    catalog = {}
    for kind, entry in MODEL_SUGGESTIONS.items():
        digest, size = MODEL_FILES[kind]
        weights = size / gib
        weight_offload = 0.0
        if layers is None:
            weight_offload = min(weights, usable_vram)
        elif layers > 0:
            weight_offload = weights * min(layers, entry["layers"]) / entry["layers"]
        # Keep memory for context, buffers and the OS. CPU RAM and VRAM are separate budgets.
        ram_required = 2.5 + weights - weight_offload
        problems = []
        if arch not in ("x86_64", "amd64", "aarch64", "arm64") or not threads:
            problems.append("CPU architecture or parallelism is unverified")
        if disk < weights + 2:
            problems.append("Selected folder needs more free disk")
        if ram < ram_required:
            problems.append("Available system RAM is below the estimate")
        if weight_offload and (not gpu_ready or weight_offload > usable_vram):
            problems.append("Requested offload exceeds verified GPU planning capacity")
        if weights >= 2 and not fast_cpu and weight_offload < weights:
            problems.append(
                "Prefer a smaller model on this CPU unless most weights fit on the GPU"
            )
        mode = (
            "GPU weights fit"
            if weight_offload == weights
            else "Hybrid estimate"
            if weight_offload
            else "CPU estimate"
        )
        catalog[kind] = {
            **entry,
            "sha256": digest,
            "size_bytes": size,
            "fit": not problems,
            "fit_mode": mode,
            "fit_issues": problems,
            "estimated_ram_gib": round(ram_required, 1),
            "estimated_disk_gib": round(weights + 2, 1),
        }
    # Prefer a larger general model when its weights fit on the GPU, then lighter models
    # on the CPU. Coding and reasoning remain visible as separate task choices.
    rank = {"GPU weights fit": 0, "Hybrid estimate": 1, "CPU estimate": 2}
    ordered = sorted(
        catalog.items(),
        key=lambda item: (
            -item[1].get("year", 2025),
            rank[item[1]["fit_mode"]],
            -item[1]["size_bytes"]
            if item[1]["fit_mode"] == "GPU weights fit"
            else item[1]["size_bytes"],
        ),
    )
    newer = {"general": "general_2026", "balanced": "balanced_2026"}
    recommended = {
        key: row
        for key, row in ordered
        if row["fit"]
        and not row.get("manual_only")
        and (key not in newer or not catalog[newer[key]]["fit"])
    }
    summary = {
        "backend": backend,
        "cpu_threads": threads,
        "cpu_vector_support": fast_cpu,
        "available_ram_gib": round(ram, 1),
        "free_disk_gib": disk,
        "gpu": gpu.get("name"),
        "available_vram_mib": vram,
        "gpu_planning_ready": gpu_ready,
    }
    return catalog, recommended, summary


def make_plan(args):
    info = inventory()
    backend = (
        detect_backend(info)
        if getattr(args, "backend", "auto") == "auto"
        else args.backend
    )
    if backend == "cpu" and getattr(args, "gpu_layers", 0):
        raise ValueError("Choose a GPU-capable build before setting GPU layers")
    host, reasons = host_support()
    config = load_config() if CFG.exists() else {}
    try:
        storage = disk(args.data_root)
        check_installed_storage(config, storage)
    except (OSError, RuntimeError, ValueError) as e:
        storage = {"ready": False, "error": str(e)}
    try:
        volumes = server_storage.devices()
    except (OSError, RuntimeError, ValueError):
        volumes = None
    selection = getattr(args, "mount_uuid", None)
    model = getattr(args, "model", None)
    if (
        model
        and not selection
        and getattr(args, "action", "plan") in ("plan", "install")
    ):
        model_path(args.data_root, model)
    if selection:
        mounted = (
            storage.get("mount") == args.data_root
            and storage.get("uuid") == selection.lower()
        )
        if not mounted:
            storage = {
                "directory": args.data_root,
                "selected_volume": server_storage.selected(selection),
                "action": "create mount point and attach existing filesystem",
            }
    models, recommended, model_fit = assess_models(
        info,
        storage,
        backend,
        getattr(args, "gpu_layers", None),
        gpu_ready=gpu_planning_ready(backend),
    )
    free_gib = storage.get("free_gib", 0)
    model_url = getattr(args, "model_url", None)
    download = None
    if model_url:
        from models import https_url

        https_url(model_url)
        digest = getattr(args, "sha256", None)
        size = getattr(args, "size_bytes", None)
        filename = Path(parse.urlsplit(model_url).path).name
        if (
            not digest
            or not re.fullmatch("[A-Fa-f0-9]{64}", digest)
            or not size
            or not 4 <= size <= 100 * 1024**3
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,190}\.gguf", filename)
        ):
            raise ValueError(
                "Use a direct GGUF URL, verified SHA-256, and exact size in bytes"
            )
        if size + 2 * 1024**3 > free_gib * 1024**3:
            raise ValueError(
                "The selected storage needs model size plus 2 GiB of free space"
            )
        download = {"filename": filename, "size_bytes": size, "sha256": digest.lower()}
    return {
        "hardware": info,
        "recommended_profile": profile(info, args.profile),
        "backend_candidate": backend,
        "model_recommendations": recommended,
        "model_catalog": models,
        "model_fit": model_fit,
        "model_download": download,
        "gpu_layers_override": getattr(args, "gpu_layers", None),
        "directories": [
            str(SOURCE.parent),
            str(ETC),
            args.data_root,
            str(Path(args.data_root) / "models"),
        ],
        "port": getattr(args, "port", None) or config.get("port", 8080),
        "backend_verified": False,
        "managed_install_supported": not reasons,
        "native_manager": host["manager"],
        "install_blockers": reasons,
        "unmounted_volumes": volumes,
        "storage": storage,
        "lan": lan(),
        "existing_services": {
            n: run(["systemctl", "is-active", n])
            for n in ("ollama", "vllm", "automation-llamacpp", "automation-ai-api")
        },
        "planned": [
            "Install exactly one llama.cpp service, not Ollama or vLLM",
            "Reuse selected storage or create the local model directory",
            "Use official upstream llama.cpp source with a recorded Git revision",
            "Download a verified GGUF once, reuse on rerun",
            "Configure localhost-only llama-server and optional LAN Bearer gateway",
            "Benchmark on target machine, never guess tokens per second",
        ],
        "warning": "No host GPU benchmarks are possible without installing and running on target server.",
    }


def print_status(args):
    cfg = None
    try:
        cfg = load_config()
    except (RuntimeError, OSError):
        pass
    try:
        state = disk(args.data_root)
        check_installed_storage(cfg, state)
    except (RuntimeError, OSError) as e:
        state = {"ready": False, "error": str(e)}
    observed = dict(
        line.split("=", 1)
        for line in run(
            [
                "systemctl",
                "show",
                SERVICE.name,
                "--property=LoadState,ActiveState,UnitFileState",
            ]
        ).splitlines()
        if "=" in line
    )
    configured = bool(cfg and cfg.get("_managed") == MARK)
    service = observed.get("ActiveState", "")
    boot = observed.get("UnitFileState", "")
    readiness = None
    if service == "active" and configured:
        from contextlib import redirect_stdout
        from io import StringIO
        from ai_health import check_api

        with redirect_stdout(StringIO()):
            readiness = check_api("llamacpp", port=cfg["port"]) == 0
    result = {
        "storage": state,
        "service": service,
        "service_unit": observed.get("LoadState", "unknown"),
        "boot_state": boot,
        "configured": configured,
        "managed_binary": BIN.is_file(),
        "api_ready": readiness,
        "gateway": run(["systemctl", "is-active", "automation-ai-api"]),
        "config": {k: v for k, v in (cfg or {}).items() if k != "_managed"},
        "gpu": run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
        ),
        "lan": lan(),
    }
    print(json.dumps(result, indent=2))
    return 0


def benchmark_action(args):
    if run(["systemctl", "is-active", "automation-llamacpp"]) != "active":
        raise RuntimeError("Shared llama.cpp service is not active")
    from llama_benchmark import benchmark, concurrency_test

    cfg = load_config()
    target_url = "http://127.0.0.1:" + str(cfg["port"])
    gpu_before = run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    result = benchmark(target_url, cfg["alias"], args.repeats)
    if args.concurrency > 1:
        result["concurrency"] = concurrency_test(
            target_url, cfg["alias"], args.concurrency
        )
    result["gpu_before"] = gpu_before
    result["gpu_after"] = run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    result["hardware"] = inventory()
    result["profile"] = cfg.get("profile")
    target = Path(args.output or "ai-benchmark.json").expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("Saved:", target)
    return 0


def engine_inventory():
    result = []
    for name, executable, services, port in (
        (
            "llama.cpp",
            "llama-server",
            ("automation-llamacpp.service", "llama-server.service"),
            8080,
        ),
        ("Ollama", "ollama", ("ollama.service",), 11434),
        ("vLLM", "vllm", ("vllm.service",), 8000),
    ):
        states = []
        for service in services:
            for scope in ([], ["--user"]):
                states.append(
                    run(
                        [
                            "systemctl",
                            *scope,
                            "show",
                            service,
                            "-p",
                            "ActiveState",
                            "-p",
                            "LoadState",
                            "--value",
                        ]
                    ).splitlines()
                )
        running = any("active" in state for state in states) or bool(
            run(["pgrep", "-x", executable])
        )
        installed = bool(
            shutil.which(executable)
            or any("loaded" in state for state in states)
            or (name == "llama.cpp" and BIN.is_file())
        )
        owned = (
            name == "llama.cpp"
            and SERVICE.is_file()
            and not SERVICE.is_symlink()
            and SERVICE.read_text().startswith(MARK)
            and CFG.is_file()
        )
        result.append(
            {
                "installed": installed or running,
                "owned_service": owned,
                "engine": name,
                "state": "running"
                if running
                else "stopped"
                if installed
                else "unavailable",
                "default_port": port,
                "managed": name == "llama.cpp",
            }
        )
    return result


def managed_service_config():
    cfg = load_config()
    if (
        cfg.get("_managed") != MARK
        or SERVICE.is_symlink()
        or not SERVICE.is_file()
        or SERVICE.read_text() != unit(cfg["data_root"])
    ):
        raise RuntimeError("The llama.cpp service differs from the toolkit definition")
    fragment = run(
        ["systemctl", "show", SERVICE.name, "--property=FragmentPath", "--value"]
    )
    drop_ins = run(
        ["systemctl", "show", SERVICE.name, "--property=DropInPaths", "--value"]
    )
    if fragment != str(SERVICE) or drop_ins:
        raise RuntimeError("Review systemd overrides before managing this service")
    return cfg


def service_control(operation, approved):
    if not approved:
        raise ValueError("Review the managed service action and use --yes")
    managed_service_config()
    action(["systemctl", operation, SERVICE.name], root=True)
    status = run(
        ["systemctl", "show", SERVICE.name, "--property=ActiveState", "--value"]
    )
    print(f"{SERVICE.name}: {status or 'inactive or unavailable'}")
    expected = "inactive" if operation == "stop" else "active"
    return 0 if status == expected else 1


def check_loopback_port(port):
    import socket
    from contextlib import redirect_stdout
    from io import StringIO
    from ai_health import check_api

    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as error:
            detail = str(error)
        else:
            return {"port": port, "state": "free"}
    output = StringIO()
    with redirect_stdout(output):
        healthy = check_api("llamacpp", "127.0.0.1", port) == 0
    return {
        "port": port,
        "state": "healthy" if healthy else "unavailable",
        "detail": output.getvalue().strip() or detail,
    }


def change_context(tokens, approved, *, dry_run):
    from ai_health import runtime_context, smoke_inference
    from gguf_context import trained_context_from_gguf

    previous = managed_service_config()
    if run(["systemctl", "is-active", SERVICE.name]) != "active":
        raise RuntimeError(
            "Start the managed llama.cpp service before changing context"
        )
    # llama-server divides the configured budget between parallel slots.
    parallel = int(previous["parallel"])
    if tokens // parallel < 256:
        raise ValueError("Allow at least 256 context tokens per slot")
    try:
        trained = trained_context_from_gguf(previous["model"])
    except (OSError, ValueError):
        trained = None
    if (
        tokens != previous["context"]
        and tokens > previous["context"]
        and (not trained or (tokens + parallel - 1) // parallel > trained)
    ):
        raise ValueError(
            "The requested context increase exceeds the verified GGUF training limit or that limit is unknown"
        )
    candidate = {**previous, "context": tokens, "context_manual": True}
    launcher_command(candidate)
    if dry_run:
        print(
            json.dumps(
                {
                    "configured_tokens": previous["context"],
                    "requested_tokens": tokens,
                    "parallel_slots": parallel,
                    "target_tokens_per_slot": tokens // parallel,
                    "model_trained_tokens": trained,
                }
            )
        )
        return 0
    if not approved:
        raise ValueError("Review the context plan and use --yes")
    if load_config() != previous:
        raise RuntimeError("The service configuration changed before the context test")
    changed = store_config(candidate)
    try:
        if changed:
            action(["systemctl", "restart", SERVICE.name], root=True)
        if (
            not wait_health(port=candidate["port"])
            or runtime_context(
                "llamacpp", port=candidate["port"], desired=tokens // parallel
            )
            or smoke_inference(
                "llamacpp", candidate["alias"], port=candidate["port"], timeout=60
            )
        ):
            raise RuntimeError(
                "The requested context did not pass readiness, runtime context and generation checks"
            )
    except (Exception, KeyboardInterrupt):
        if changed:
            if load_config() != candidate:
                raise RuntimeError(
                    "The configuration changed during testing; automatic restoration was refused"
                )
            store_config(previous)
            action(["systemctl", "restart", SERVICE.name], root=True)
            if not wait_health(port=previous["port"]):
                raise RuntimeError(
                    "The prior context was restored, but the service did not become ready"
                )
            print("Restored the prior context; the service is ready.")
        raise
    print(f"Verified context: {tokens} configured tokens across {parallel} slot(s).")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("ask", "suggest"):
        from terminal_ai import main as terminal_request

        return terminal_request(argv)
    p = argparse.ArgumentParser(
        prog="bash setup.sh ai server",
        description="Central llama.cpp AI server (dedicated Linux installation)",
        epilog="Terminal AI: use 'ask --help' or 'suggest --help'.",
    )
    p.add_argument(
        "action",
        choices=[
            "hardware",
            "system-details",
            "storage",
            "plan",
            "install",
            "build",
            "test-model",
            "status",
            "models",
            "verify",
            "port-check",
            "runtime-context",
            "context",
            "model-download",
            "switch",
            "benchmark",
            "tune",
            "urls",
            "key-show",
            "key-rotate",
            "doctor",
            "engines",
            "start",
            "stop",
            "restart",
        ],
    )
    p.add_argument(
        "--data-root",
        help="Model directory (defaults to the configured path or /srv/ai)",
    )
    p.add_argument(
        "--mount-uuid",
        help="Mount an explicitly selected existing filesystem at --data-root",
    )
    p.add_argument(
        "--profile",
        choices=["auto", "maximum", "balanced", "low-memory", "multi-user"],
        default="auto",
    )
    p.add_argument(
        "--backend",
        choices=["auto", "cpu", "cuda", "hip", "vulkan", "metal"],
        default="auto",
    )
    p.add_argument(
        "--host",
        choices=("127.0.0.1", "::1", "localhost"),
        default="127.0.0.1",
        help="Loopback host for verify",
    )
    p.add_argument("--port", type=int, metavar="PORT")
    p.add_argument(
        "--context-tokens",
        type=int,
        help="Total context tokens for the managed service",
    )
    p.add_argument(
        "--model",
        help="Existing GGUF path inside the model directory (for switch and install)",
    )
    p.add_argument("--model-choice", choices=list(MODEL_CATALOG), default="general")
    p.add_argument("--model-url", help="Custom HTTPS GGUF, requires --sha256")
    p.add_argument("--sha256", help="Independently verified SHA-256 for model download")
    p.add_argument(
        "--size-bytes", type=int, help="Independently reviewed exact model size"
    )
    p.add_argument("--with-lan-api", action="store_true")
    p.add_argument(
        "--migrate-legacy",
        action="store_true",
        help="Explicitly replace an owned old gateway; never stop foreign engines",
    )
    p.add_argument(
        "--gpu-layers", type=int, help="GPU layer count; omit to keep automatic offload"
    )
    p.add_argument("--update-source", action="store_true")
    p.add_argument(
        "--rebuild", action="store_true", help="Rebuild the installed source checkout"
    )
    p.add_argument(
        "--reconfigure",
        action="store_true",
        help="Approve changing previously tuned settings/model on repeat install",
    )
    p.add_argument("--no-pull", action="store_true")
    p.add_argument(
        "--allow-oversized",
        action="store_true",
        help="Explicit approval to download very large GGUF weights",
    )
    p.add_argument("--skip-smoke", action="store_true")
    p.add_argument("--skip-tune", action="store_true")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--output")
    args = p.parse_args(argv)
    if args.gpu_layers is not None and (
        not 0 <= args.gpu_layers <= 999
        or args.action not in ("plan", "install", "switch")
    ):
        p.error("--gpu-layers 0–999 is valid for plan, install and switch")
    minimum_port = (
        1 if args.action in ("verify", "port-check", "runtime-context") else 1024
    )
    if args.port is not None and not minimum_port <= args.port <= 65535:
        p.error(f"Port must be between {minimum_port} and 65535")
    if args.mount_uuid and args.action not in ("install", "plan"):
        p.error("--mount-uuid is for install and plan")
    if args.context_tokens is not None and args.action != "context":
        p.error("--context-tokens is for context")
    if args.action == "context":
        if args.context_tokens is None or not 256 <= args.context_tokens <= 131072:
            p.error("Choose a context size from 256 to 131072 tokens")
        return change_context(args.context_tokens, args.yes, dry_run=args.dry_run)
    if args.action in ("port-check", "runtime-context"):
        port = args.port or (load_config().get("port", 8080) if CFG.exists() else 8080)
        if args.action == "port-check":
            print(json.dumps(check_loopback_port(port)))
            return 0
        from ai_health import runtime_context

        return runtime_context("llamacpp", port=port)
    if args.action == "storage":
        print(json.dumps({"unmounted_volumes": server_storage.devices()}, indent=2))
        return 0
    if args.action == "hardware":
        print(json.dumps(inventory(), indent=2))
        return 0
    if args.action == "system-details":
        print(json.dumps(desktop_details(), indent=2))
        return 0
    if args.action == "test-model" and not args.dry_run:
        from ai_health import smoke_inference

        if not args.yes:
            raise ValueError("Use --yes to send a short model test prompt")
        cfg = managed_service_config()
        if run(["systemctl", "is-active", SERVICE.name]) != "active":
            raise RuntimeError("Start the configured llama.cpp service before testing")
        print(
            "Testing",
            Path(cfg["model"]).name,
            "with",
            cfg.get("gpu_layers", "auto"),
            "GPU layers",
        )
        return smoke_inference("llamacpp", cfg["alias"], port=cfg["port"], timeout=60)
    if args.action == "build" and not args.dry_run:
        if not args.yes:
            raise ValueError("Use --yes after reviewing the build plan")
        _, reasons = host_support()
        if reasons:
            raise RuntimeError("; ".join(reasons))
        backend = (
            detect_backend(inventory()) if args.backend == "auto" else args.backend
        )
        if backend == "metal":
            raise ValueError("Metal requires a native macOS build")
        if not BIN.is_file() or args.update_source or args.rebuild:
            dependencies(backend, build=True)
        build_backend(backend, args.update_source, rebuild=args.rebuild)
        print("llama-server build ready. Select a model before starting the service.")
        return 0
    if args.action == "verify" and not args.dry_run:
        from contextlib import redirect_stdout
        from io import StringIO
        from ai_health import check_api, model_inventory

        port = args.port or (load_config().get("port", 8080) if CFG.exists() else 8080)
        health = StringIO()
        with redirect_stdout(health):
            status = check_api("llamacpp", args.host, port)
        if status:
            print(health.getvalue(), end="")
            return status
        return model_inventory("llamacpp", args.host, port)
    if args.action == "engines":
        print(json.dumps(engine_inventory(), indent=2))
        return 0
    if args.action in ("start", "stop", "restart") and not args.dry_run:
        return service_control(args.action, args.yes)
    if args.data_root is None:
        args.data_root = load_config()["data_root"] if CFG.exists() else str(ROOT)
    args.data_root = str(server_storage.checked_root(args.data_root))
    if args.action == "plan" or args.dry_run:
        print(json.dumps(make_plan(args), indent=2))
        return 0
    if args.action == "status" or args.action == "doctor":
        return print_status(args)
    if args.action == "models":
        root = Path(args.data_root)
        model_dir = root / "models"
        folders = [root] if model_dir.is_symlink() else [root, model_dir]
        print(
            json.dumps(
                [
                    {"path": str(f), "gib": round(f.stat().st_size / 1024**3, 3)}
                    for folder in folders
                    for f in sorted(folder.glob("*"))
                    if f.suffix.lower() == ".gguf"
                    if f.is_file()
                    and not f.is_symlink()
                    and not re.search(r"-[0-9]{5}-of-[0-9]{5}\.gguf$", f.name, re.I)
                    and gguf_header(f)
                ],
                indent=2,
            )
        )
        return 0
    if args.action == "urls":
        port = load_config().get("port", 8080) if CFG.exists() else 8080
        print(f"Private llama.cpp: http://127.0.0.1:{port}/v1")
        info = lan()
        print(
            "Authenticated LAN API:",
            f"http://{info['ip']}:11435/v1" if info else "LAN not detected",
        )
        return 0
    if args.action == "key-show":
        if not sys.stdout.isatty():
            raise RuntimeError("Display the key only in a private interactive terminal")
        print("Warning: key is secret; avoid screen sharing and shell history.")
        action(["cat", KEY], root=True)
        return 0
    if args.action == "key-rotate":
        if not args.yes:
            p.error(
                "Key rotation requires --yes; existing clients will stop authenticating"
            )
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "key"
            tmp.write_text(secrets.token_urlsafe(48) + "\n")
            if KEY.exists():
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y%m%d%H%M%S"
                )
                action(["cp", "-a", KEY, str(KEY) + ".backup-" + stamp], root=True)
            action(
                [
                    "install",
                    "-D",
                    "-m",
                    "0640",
                    "-o",
                    "root",
                    "-g",
                    "ai-llama",
                    tmp,
                    KEY,
                ],
                root=True,
            )
        action(["systemctl", "restart", "automation-ai-api"], root=True)
        return 0
    if args.action == "benchmark":
        if not 1 <= args.repeats <= 10 or not 1 <= args.concurrency <= 8:
            p.error("repeats must be 1..10 and concurrency 1..8")
        return benchmark_action(args)
    if args.action == "tune":
        if not args.yes:
            p.error("Tuning requires --yes and active installed service")
        if not 1 <= args.repeats <= 10:
            p.error("--repeats must be between 1 and 10")
        return tune_live(args)
    if args.action in ("install", "model-download", "switch") and not args.yes:
        print("No changes. Re-run with --yes after reviewing `ai server plan`.")
        return 4
    if args.action == "install":
        if args.model_url:
            make_plan(args)
        installation(args)
        return 0
    if args.action == "model-download":
        check_installed_storage(
            load_config() if CFG.exists() else None, disk(args.data_root)
        )
        if args.model_url:
            make_plan(args)
        if not Path(args.data_root).is_dir():
            if not args.model_url:
                raise ValueError(
                    "Select a reviewed download URL before creating model storage"
                )
            action(["mkdir", "-p", "--", args.data_root], root=True)
        print(
            "Model:",
            acquire_model(
                args.data_root,
                args.model_choice,
                args.model_url,
                args.sha256,
                args.allow_oversized,
                size_bytes=args.size_bytes,
            ),
        )
        return 0
    if args.action == "switch":
        if not args.model:
            p.error("switch requires --model")
        cfg = managed_service_config()
        selected = model_path(cfg["data_root"], args.model)
        old = dict(cfg)
        cfg["model"] = selected
        if args.gpu_layers is not None:
            if cfg.get("backend") == "cpu" and args.gpu_layers:
                raise ValueError("The current build uses CPU only")
            cfg["gpu_layers"] = str(args.gpu_layers)
        launcher_command(cfg)
        allow_service_read(selected)
        try:
            store_config(cfg)
            action(["systemctl", "restart", "automation-llamacpp"], root=True)
            if not wait_health(port=cfg["port"]):
                raise RuntimeError("New model failed health check")
        except Exception:
            store_config(old)
            action(["systemctl", "restart", "automation-llamacpp"], root=True)
            raise
        print("Switched shared model to:", selected)
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as e:
        print("AI SERVER ERROR:", e, file=sys.stderr)
        raise SystemExit(2)
