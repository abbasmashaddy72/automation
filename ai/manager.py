#!/usr/bin/env python3
"""AI CLI of original Automation Toolkit. Exactly one managed inference engine: llama.cpp.

Historic GGUF verification/import tools stay available; no Ollama/vLLM/Jan
install, service, model pull or inference entry point is reachable through CLI.
"""

from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path
import sys

from dedicated_server import main as server_main


def dispatch(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a and a[0] in ("--help", "-h", "help"):
        print(
            "Usage: bash setup.sh ai server {hardware|storage|plan|install|status|models|model-download|switch|benchmark|tune|urls|key-show|key-rotate}"
        )
        print(
            "Or: bash setup.sh ai llamacpp {model-search|model-files|gguf-list|gguf-download|...}"
        )
        return 0
    if a and a[0] in ("ollama", "vllm", "jan"):
        print(
            "This release manages llama.cpp only. Existing other-engine data is not deleted.",
            file=sys.stderr,
        )
        return 3
    if a and a[0] in ("server", "dedicated"):
        return server_main(a[1:])
    if not a or a[0] == "list":
        print("Managed inference engine: llama.cpp (one shared server)")
        print("Use: bash setup.sh ai server plan")
        print("Use: bash setup.sh ai server install --with-lan-api --yes")
        print("GGUF tools: bash setup.sh ai llamacpp model-search/gguf-list/...")
        return 0
    if a[0] == "hardware":
        return server_main(["hardware", *a[1:]])
    if a[0] == "install":
        p = argparse.ArgumentParser(prog="setup.sh ai install")
        p.add_argument("--backends", default="llamacpp")
        p.add_argument("--yes", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        opts = p.parse_args(a[1:])
        name = opts.backends.strip().lower()
        if name != "llamacpp":
            p.error("Only --backends llamacpp is accepted; no other engine installed")
        return server_main(
            [
                "install",
                *(["--yes"] if opts.yes else []),
                *(["--dry-run"] if opts.dry_run else []),
            ]
        )
    if a[0] != "llamacpp":
        print("Unknown AI backend. Use `ai server` or `ai llamacpp`.", file=sys.stderr)
        return 2
    # Keep exact GGUF artifact model/search/migration capability without the old
    # multiple-engine service manager or old installer entry points.
    action = a[1] if len(a) > 1 else "status"
    rest = a[2:]
    if action == "--check":
        action = "check"
    simple = {
        "status": "status",
        "check": "plan",
        "doctor": "doctor",
        "install": "install",
        "update": "install",
        "repair": "install",
        "models": "models",
        "list-models": "models",
        "benchmark": "benchmark",
        "tune": "tune",
        "key-show": "key-show",
        "key-rotate": "key-rotate",
        "model-download": "model-download",
        "model-select": "switch",
        "service-status": "status",
        "smoke": "benchmark",
    }
    if action in simple:
        return server_main(
            [simple[action], *(flag for flag in rest if flag != "--non-interactive")]
        )
    if action == "gguf-context":
        from gguf_context import trained_context_from_gguf

        p = argparse.ArgumentParser(prog="bash setup.sh ai llamacpp gguf-context")
        p.add_argument("file", type=Path)
        opts = p.parse_args(rest)
        print(json.dumps({"trained_context": trained_context_from_gguf(opts.file)}))
        return 0
    p = argparse.ArgumentParser(prog=f"setup.sh ai llamacpp {action}")
    p.add_argument("--root", type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--model")
    p.add_argument("--url")
    p.add_argument("--sha256")
    p.add_argument("--size-bytes", type=int)
    p.add_argument("--revision")
    p.add_argument("--quant")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--rank", choices=["downloads", "likes", "trending"])
    p.add_argument("--scope", choices=["hub", "warm"], default="hub")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--legacy-root", type=Path)
    p.add_argument("--ignore-legacy-state", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    opts = p.parse_args(rest)
    opts.action = action
    opts.backend = "llamacpp"
    if action in ("model-search", "model-files"):
        import models

        if action == "model-search":
            if not opts.query:
                p.error("--query required")
            result = models.search(
                opts.query,
                backend="llamacpp",
                limit=opts.limit,
                rank=opts.rank,
                scope=opts.scope,
                offset=opts.offset,
            )
        else:
            result = models.model_files(
                opts.model, opts.revision, backend="llamacpp", quant=opts.quant
            )
        print(json.dumps(result, indent=2))
        return 0
    if action in (
        "gguf-download",
        "gguf-list",
        "gguf-legacy-list",
        "gguf-legacy-import",
        "gguf-resolve",
        "gguf-remove",
    ):
        import gguf

        # These are archive-safe, explicit GGUF receipt operations; runtime
        # selection uses `ai server switch --model` only.
        opts.executable = None
        opts.model_alias = None
        opts.context = None
        opts.cpu_threads = None
        opts.cpu_quota = None
        opts.port = None
        opts.key_file = None
        return gguf.main(opts)
    print("Unsupported action in llama.cpp-only toolkit:", action, file=sys.stderr)
    return 2


def main(argv=None):
    try:
        return dispatch(argv)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print("AI error:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
