#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

section "📦 Starting MariaDB setup for $PLATFORM_STRING"
ensure_supported_platform arch manjaro

# === Uninstall/Cleanup Option ===
if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling MariaDB..."
    sudo systemctl stop mariadb || warn "Could not stop mariadb"
    sudo systemctl disable mariadb || warn "Could not disable mariadb"
    sudo pacman -Rs --noconfirm mariadb || warn "Could not remove MariaDB package"
    sudo rm -rf /var/lib/mysql || warn "Could not remove MariaDB data directory"
    ok "MariaDB uninstalled and cleaned up."
    exit 0
fi

# === Check Internet Access ===
if ! ping -c1 -W1 archlinux.org &>/dev/null; then
    fail "No internet connection detected. Cannot proceed with MariaDB installation."
fi

# === Install MariaDB (idempotent) ===
if pacman -Qi mariadb &>/dev/null; then
    ok "MariaDB already installed."
else
    log "📥 Installing MariaDB..."
    if ! sudo pacman -S --needed --noconfirm mariadb; then
        fail "Failed to install MariaDB."
    fi
    ok "MariaDB installed."
fi

# === Initialize Database Only If Not Already Initialized ===
if [[ ! -d /var/lib/mysql/mysql ]]; then
    log "🛠️ Initializing MariaDB data directory..."
    if ! sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql; then
        fail "MariaDB initialization failed."
    fi
    ok "MariaDB initialized."
else
    ok "MariaDB data directory already initialized."
fi

# === Enable + Start Service (idempotent) ===
log "🚀 Enabling and starting mariadb.service..."
sudo systemctl enable --now mariadb || fail "Failed to enable/start mariadb.service"

# === Verify Service ===
log "🔍 Verifying service status..."
if sudo systemctl is-active --quiet mariadb; then
    ok "MariaDB is running."
else
    sudo systemctl status mariadb | tee -a "$LOGFILE"
    fail "MariaDB service is not running."
fi

# === Show Installed Version ===
mariadb_version=$(mysql --version 2>/dev/null || true)
[[ -n "$mariadb_version" ]] && log "MariaDB version: $mariadb_version"

# === Secure Installation (Interactive, with Password Validation) ===
section "🛡️ Secure MariaDB Installation"

read -rsp "🔑 Enter new MariaDB root password: " mariadb_pass; echo
read -rsp "🔑 Confirm password: " mariadb_pass_confirm; echo
if [[ -z "$mariadb_pass" || "$mariadb_pass" != "$mariadb_pass_confirm" || ${#mariadb_pass} -lt 8 ]]; then
    fail "Password validation failed. Must not be empty, must match, and must be at least 8 characters."
fi

export MARIADB_ROOT_PASSWORD="$mariadb_pass"

# Run mariadb-secure-installation in non-interactive mode if possible (for modern MariaDB)
if command -v mariadb-secure-installation &>/dev/null; then
    # For MariaDB 10.5+ we can use env variable or expect script
    log "🔒 Securing MariaDB installation..."
    if ! sudo mariadb-secure-installation <<EOF
Y
$mariadb_pass
$mariadb_pass
Y
Y
Y
Y
EOF
    then
        warn "Automatic secure installation failed, please run 'sudo mariadb-secure-installation' manually."
        exit 1
    fi
else
    warn "mariadb-secure-installation not found, skipping secure setup."
fi

ok "🎉 MariaDB setup completed successfully!"

# === Service/Version Recap ===
section "✅ MariaDB Final Status"
sudo systemctl status mariadb | tee -a "$LOGFILE"
mysql --version | tee -a "$LOGFILE"
