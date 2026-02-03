#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 24-node-runtime-setup.sh
#
# Purpose
# -------
# Clean Node.js runtime install for Arch-based distros.
#
# Installs (repo-checked)
# -----------------------
# ✅ nodejs + npm (primary)
# ✅ nvm (optional, if available)
#
# Notes (important)
# -----------------
# - On Arch, nvm typically needs shell init lines to be usable.
#   This script installs nvm but does NOT modify your shell files.
#
# Usage
# -----
#   ./24-node-runtime-setup.sh
#   ./24-node-runtime-setup.sh --uninstall
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
##############################################################################

on_err() { echo "❌ Error on line $1 while running: $2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
    fail "Platform library not found! Exiting."
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-platform.sh"

ensure_supported_platform arch cachyos manjaro garuda endeavouros
section "🟢 Node Runtime Setup for $PLATFORM_STRING"

log "🔐 Please enter your sudo password to begin..."
sudo -v || fail "❌ Failed to authenticate sudo."

have_cmd() { command -v "$1" &>/dev/null; }
is_installed_pkg() { pacman -Qi "$1" &>/dev/null; }
repo_has_pkg() { pacman -Si "$1" &>/dev/null; }

install_pkg_if_available() {
    local pkg="$1"
    
    if is_installed_pkg "$pkg"; then
        ok "$pkg already installed."
        return 0
    fi
    
    if ! repo_has_pkg "$pkg"; then
        warn "Skipping '$pkg' (not available in pacman repos on this system)."
        return 0
    fi
    
    log "Installing $pkg..."
    sudo pacman -S --noconfirm --needed "$pkg" || fail "Failed to install $pkg"
    ok "Installed $pkg"
}

##############################################################################
# Uninstall mode
##############################################################################
if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling Node runtime (best-effort)"
    
    declare -a remove_pkgs=(
        nodejs
        npm
        nvm
    )
    
    sudo pacman -Rs --noconfirm "${remove_pkgs[@]}" >/dev/null 2>&1 \
    || warn "Could not remove some packages (deps in use or not installed)."
    
    ok "Uninstall complete."
    exit 0
fi

##############################################################################
# Install Node stack
##############################################################################
install_node_stack() {
    section "📥 Installing Node.js + npm (repo-checked)"
    install_pkg_if_available "nodejs"
    install_pkg_if_available "npm"
    
    section "🧩 Optional: Installing nvm (repo-checked)"
    if repo_has_pkg "nvm"; then
        install_pkg_if_available "nvm"
        warn "nvm installed. You still need shell init to use it (this script won't touch your rc files)."
    else
        warn "nvm not available in repos on this system. Skipping."
    fi
}

final_checks() {
    section "🧪 Verifying Node runtime"
    have_cmd node || fail "node not found in PATH"
    have_cmd npm || fail "npm not found in PATH"
    
    node -v | tee -a "$LOGFILE"
    npm -v | tee -a "$LOGFILE"
    
    ok "Node runtime verified."
}

install_node_stack
final_checks

ok "🎉 Node runtime setup completed."
