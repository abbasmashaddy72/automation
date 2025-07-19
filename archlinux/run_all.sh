#!/bin/bash

set -euo pipefail

LOGDIR="$HOME/logs/setup"
mkdir -p "$LOGDIR"

log() {
    echo "$(date '+%F %T') | $*"
}

error() {
    echo "$(date '+%F %T') | ❌ ERROR: $*" >&2
    exit 1
}

run_script() {
    local script="$1"
    if [[ -f "$script" ]]; then
        log "▶️ Running $script..."
        bash "$script" 2>&1 | tee -a "$LOGDIR/$(basename "$script").log"
    else
        error "$script not found!"
    fi
}

# === Execute all scripts in numeric order ===
for script in ./*.sh; do
    [[ "$(basename "$script")" == "run-all.sh" ]] && continue
    run_script "$script"
done

log "🎉 All setup scripts executed successfully!"
