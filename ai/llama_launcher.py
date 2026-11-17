#!/usr/bin/env python3
"""Exec a single trusted local llama-server process from root-owned JSON settings.

No shell, never interpolate user input, and refuse missing storage/mismatched paths.
"""

from __future__ import annotations
import json, os
from pathlib import Path
import subprocess
import sys

CONFIG = Path("/etc/automation-ai/llamacpp.json")


def command(config):
    root = Path(config["data_root"]).resolve(strict=True)
    model = Path(config["model"]).resolve(strict=True)
    binary = Path(config["binary"]).resolve(strict=True)
    mount = Path(config.get("storage_mount", str(root)))
    if (
        not mount.is_absolute()
        or (mount != root and mount not in root.parents)
        or not root.is_dir()
        or root == Path("/")
    ):
        raise ValueError("AI data volume is not mounted")
    if "storage_mount" not in config:
        if not os.path.ismount(mount):
            raise ValueError("AI data volume is not mounted")
    else:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--target", str(root), "-o", "TARGET,UUID"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        fields = result.stdout.strip().split()
        expected = config.get("storage_uuid")
        if (
            result.returncode
            or not fields
            or fields[0] != str(mount)
            or (
                expected
                and [field.lower() for field in fields[1:]] != [expected.lower()]
            )
        ):
            raise ValueError(
                "Mounted AI filesystem UUID differs from the configured volume"
            )
    if (
        root not in model.parents
        or model.suffix.lower() != ".gguf"
        or not model.is_file()
    ):
        raise ValueError("Model must be a GGUF inside the dedicated data volume")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("llama-server binary unavailable")
    with model.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("Model header is not GGUF")
    values = {
        k: int(config[k])
        for k in ("context", "threads", "batch", "ubatch", "parallel", "port")
    }
    if not (
        256 <= values["context"] <= 131072
        and 1 <= values["parallel"] <= 8
        and 1 <= values["threads"] <= 256
        and 16 <= values["ubatch"] <= values["batch"] <= 8192
        and 1024 <= values["port"] <= 65535
    ):
        raise ValueError("Out-of-range llama-server settings")
    layers = str(config.get("gpu_layers", "auto"))
    if layers not in ("auto", "all") and not (
        layers.isdecimal() and int(layers) <= 999
    ):
        raise ValueError("Invalid GPU layers")
    alias = str(config.get("alias", "shared-ai"))
    if not alias.replace("-", "").replace("_", "").isalnum() or len(alias) > 64:
        raise ValueError("Invalid model alias")
    return [
        str(binary),
        "--model",
        str(model),
        "--alias",
        alias,
        "--host",
        "127.0.0.1",
        "--port",
        str(values["port"]),
        "--ctx-size",
        str(values["context"]),
        "--threads",
        str(values["threads"]),
        "--batch-size",
        str(values["batch"]),
        "--ubatch-size",
        str(values["ubatch"]),
        "--parallel",
        str(values["parallel"]),
        "--n-gpu-layers",
        layers,
        "--cont-batching",
        "--metrics",
        "--no-webui",
        "--flash-attn",
        str(config.get("flash_attn", "auto")),
    ]


def main():
    cfg = json.loads(CONFIG.read_text())
    cmd = command(cfg)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as e:
        print("llama-server launch rejected:", e, file=sys.stderr)
        raise SystemExit(78)
