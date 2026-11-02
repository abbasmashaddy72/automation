#!/usr/bin/env bash
set -Eeuo pipefail
LARAVEL_TOOLKIT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$LARAVEL_TOOLKIT_DIR/lib/bootstrap.sh"
laravel_main provision "$@"
