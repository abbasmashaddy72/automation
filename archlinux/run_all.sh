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

# === Execute all setup scripts in order ===

run_script "./system_setup.sh"
run_script "./install_packages.sh"
run_script "./git_setup.sh"
run_script "./zshrc_config.sh"
run_script "./mariadb_setup.sh"
run_script "./setup_postgres.sh"
run_script "./php_valet_composer_setup.sh"
run_script "./setup_project_sites.sh"
run_script "./task_bar_setup.sh"
run_script "./udev_rules_setup.sh"
run_script "./setup-ollama-openwebui.sh"

log "🎉 All setup scripts executed successfully!"
