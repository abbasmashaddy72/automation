#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/../lib/lib-logger.sh" ]]; then
    echo "Logger library not found at ../lib/lib-logger.sh! Exiting." >&2
    exit 1
fi
if [[ ! -f "$SCRIPT_DIR/../lib/lib-platform.sh" ]]; then
    echo "Platform library not found at ../lib/lib-platform.sh! Exiting." >&2
    exit 1
fi

source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

# === Distro Check ===
ensure_supported_platform arch manjaro
section "🚀 Starting full system setup for $PLATFORM_STRING"

# === Logging Setup ===
LOGDIR="$HOME/logs/setup"
mkdir -p "$LOGDIR"

START_TIME=$(date +%s)

# === Scripts to run, in order ===
SCRIPTS=(
    01-system-setup.sh
    02-install-packages.sh
    03-git-setup.sh
    04-zshrc-config.sh
    05-mariadb-setup.sh
    06-postgres-setup.sh
    07-php-valet-setup.sh
    08-project-sites-setup.sh
    09-taskbar-setup.sh
    10-usb-udev-rules.sh
    11-ollama-openwebui-setup.sh
)

# === Handle --exclude flags ===
EXCLUDE=()
for arg in "$@"; do
    case "$arg" in
        --exclude=*) IFS=, read -ra EXCLUDE <<< "${arg#*=}" ;;
    esac
done
if [[ -n "${EXCLUDE[*]:-}" ]]; then
    log "Excluding scripts: ${EXCLUDE[*]}"
fi

declare -A RESULTS

run_script() {
    local script="$1"
    if [[ -f "$script" ]]; then
        log "▶️ Running $script..."
        if bash "$script" 2>&1 | tee -a "$LOGDIR/$(basename "$script").log"; then
            RESULTS["$script"]="✅ Success"
            ok "$script completed"
        else
            RESULTS["$script"]="❌ Failed"
            fail "$script FAILED (see $LOGDIR/$(basename "$script").log)"
        fi
    else
        RESULTS["$script"]="❌ Not found"
        fail "$script not found!"
    fi
}

# === Run scripts in order ===
for script in "${SCRIPTS[@]}"; do
    skip=0
    for excl in "${EXCLUDE[@]}"; do
        [[ "$script" == "$excl" ]] && skip=1 && break
    done
    if [[ $skip -eq 0 ]]; then
        run_script "$script"
    else
        log "⏩ Skipped $script"
        RESULTS["$script"]="⏩ Skipped"
    fi
done

# === Summary ===
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

# === Summary Table ===
echo
section "✅ SETUP SUMMARY"
printf "%-30s %s\n" "Script" "Status"
printf "%-30s %s\n" "------" "------"
for script in "${SCRIPTS[@]}"; do
    printf "%-30s %s\n" "$script" "${RESULTS[$script]:-❓ Unknown}"
done

log "🕒 Total setup time: ${MINUTES}m ${SECONDS}s"

log "📝 Next steps:"
echo "- Review logs in $LOGDIR if any script failed"
echo "- Log out/log in if your group or shell was changed"
echo "- For any failed script, rerun with: ./run_all.sh --exclude=... to skip others"

ok "🎉 All requested setup scripts have finished!"
