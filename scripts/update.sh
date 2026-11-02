#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
case "${1:-}" in
    --full-check) shift; exec python3 "$ROOT/scripts/full_update.py" --check "$@" ;;
    --full-apply) shift; exec python3 "$ROOT/scripts/full_update.py" --apply "$@" ;;
esac
exec python3 "$ROOT/scripts/patch_manager.py" "$@"
