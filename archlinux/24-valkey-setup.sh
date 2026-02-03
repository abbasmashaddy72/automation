#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 23-valkey-setup.sh
#
# Purpose
# -------
# Separate, idempotent Valkey setup for Arch-based distros:
# - Installs Valkey (pacman)
# - Enables + starts service
# - Verifies service + basic CLI ping (best-effort)
# - Supports --uninstall rollback
#
# Safety / Reliability
# --------------------
# - Skips cleanly when components aren’t present
# - Tracks packages installed by this script for safe removal
# - Does not delete any data directories by default
# - Stores state under /var/lib/arch-dev-setup/23-valkey-setup/
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./23-valkey-setup.sh
#   ./23-valkey-setup.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
    echo "❌ Error on line $1 while running: $2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Library checks and bootstrap
### ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
    echo "Logger library not found at: $LIBDIR/lib-logger.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
    echo "Platform library not found at: $LIBDIR/lib-platform.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-platform.sh"

ensure_supported_platform arch cachyos manjaro garuda endeavouros

section "🟠 Valkey setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (for uninstall + tracking)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL="y" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0              Install + start Valkey
  $0 --uninstall  Stop/disable Valkey and remove packages installed by this script

State directory:
  /var/lib/arch-dev-setup/23-valkey-setup/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/23-valkey-setup"
STATE_PKGS="$STATE_DIR/installed-packages.txt"

sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true
sudo touch "$STATE_PKGS" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to continue..."
if ! sudo -v; then
    fail "❌ Failed to authenticate sudo."
fi

### ─────────────────────────────────────────────────────────────────────────
### Helpers
### ─────────────────────────────────────────────────────────────────────────
prompt_yn() {
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply=""
    while true; do
        if [[ "$default" == "y" ]]; then
            read -r -p "$prompt [Y/n]: " reply
            reply="${reply:-y}"
        else
            read -r -p "$prompt [y/N]: " reply
            reply="${reply:-n}"
        fi
        case "${reply,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

is_installed_pkg() { pacman -Q "$1" &>/dev/null; }

record_installed_pkgs() {
    local pkgs=("$@")
    local p
    for p in "${pkgs[@]}"; do
        if ! is_installed_pkg "$p"; then
            echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
        fi
    done
}

service_exists() {
    local svc="$1"
    systemctl list-unit-files | grep -q "^${svc}\.service"
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall mode
### ─────────────────────────────────────────────────────────────────────────
uninstall_remove_recorded_packages() {
    if [[ ! -f "$STATE_PKGS" ]]; then
        warn "No recorded packages file found. Skipping package removal."
        return 0
    fi
    
    mapfile -t pkgs < <(sudo sort -u "$STATE_PKGS" | sed '/^\s*$/d' || true)
    if [[ ${#pkgs[@]} -eq 0 ]]; then
        ok "No packages were recorded as installed by this script."
        return 0
    fi
    
    section "🧯 Uninstall: packages installed by this script"
    printf '  - %s\n' "${pkgs[@]}"
    
    if prompt_yn "Remove these packages now? (safe: only ones this script added)" "n"; then
        local to_remove=()
        local p
        for p in "${pkgs[@]}"; do
            if is_installed_pkg "$p"; then
                to_remove+=("$p")
            fi
        done
        
        if [[ ${#to_remove[@]} -gt 0 ]]; then
            sudo pacman -Rns --noconfirm "${to_remove[@]}" || warn "Some removals failed (deps in use/required)."
            ok "Package removal attempted."
        else
            ok "None of the recorded packages are currently installed."
        fi
    else
        log "Skipping package removal."
    fi
}

run_uninstall() {
    section "🧹 Uninstalling Valkey (best-effort rollback)"
    
    # Stop/disable service if it exists
    if service_exists valkey; then
        sudo systemctl stop valkey 2>/dev/null || true
        sudo systemctl disable valkey 2>/dev/null || true
        ok "valkey.service stop/disable attempted."
    else
        warn "valkey.service not found. Skipping service stop/disable."
    fi
    
    uninstall_remove_recorded_packages
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Install + enable Valkey
### ─────────────────────────────────────────────────────────────────────────
install_valkey() {
    section "📦 Installing Valkey (Redis replacement)"
    
    if is_installed_pkg valkey; then
        ok "Valkey already installed."
        return 0
    fi
    
    record_installed_pkgs valkey
    sudo pacman -S --needed --noconfirm valkey || fail "Failed to install Valkey"
    ok "Valkey installed."
}

enable_valkey() {
    section "🛠 Enabling and starting Valkey service"
    
    if service_exists valkey; then
        sudo systemctl enable --now valkey || warn "Could not enable/start valkey.service"
    else
        warn "valkey.service unit not found (package may use a different unit name)."
        warn "Check units: systemctl list-unit-files | grep -i valkey"
        return 0
    fi
    
    sudo systemctl status valkey --no-pager || warn "Valkey service status check failed."
}

### ─────────────────────────────────────────────────────────────────────────
### Basic checks
### ─────────────────────────────────────────────────────────────────────────
final_checks() {
    section "🧪 Verifying Valkey"
    
    if systemctl is-active --quiet valkey 2>/dev/null; then
        ok "Valkey is running."
    else
        warn "Valkey is NOT running (check: journalctl -u valkey -e)"
    fi
    
    # CLI name can vary; valkey usually ships valkey-cli, but be defensive.
    if command -v valkey-cli &>/dev/null; then
        ok "valkey-cli found."
        
        # Best-effort ping; do not fail the whole script if ping fails (auth/bind might differ).
        if valkey-cli ping 2>/dev/null | grep -qi pong; then
            ok "valkey-cli ping: PONG"
        else
            warn "valkey-cli ping did not return PONG (service may be secured/bound differently)."
        fi
        elif command -v redis-cli &>/dev/null; then
        warn "valkey-cli not found, but redis-cli exists. Trying redis-cli ping..."
        if redis-cli ping 2>/dev/null | grep -qi pong; then
            ok "redis-cli ping: PONG"
        else
            warn "redis-cli ping did not return PONG."
        fi
    else
        warn "Neither valkey-cli nor redis-cli found in PATH."
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Main
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

install_valkey
enable_valkey
final_checks

ok "🎉 Valkey setup completed!"
