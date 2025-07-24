#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 05-mariadb-setup.sh
#   - Automated, idempotent MariaDB setup for all Arch-based systems
#   - Handles install, secure config, backups, and uninstall logic
#   - Requires: lib-logger.sh and lib-platform.sh in ../lib/
##############################################################################

### ─── Library Checks and Bootstrap ────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
    fail "Platform library not found! Exiting."
fi
source "$LIBDIR/lib-platform.sh"

ensure_supported_platform arch

section "📦 Starting MariaDB setup for $PLATFORM_STRING"

### ─── Uninstall/Cleanup Option ────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling MariaDB..."
    sudo systemctl stop mariadb || warn "Could not stop mariadb"
    sudo systemctl disable mariadb || warn "Could not disable mariadb"
    sudo pacman -Rs --noconfirm mariadb || warn "Could not remove MariaDB package"
    sudo rm -rf /var/lib/mysql || warn "Could not remove MariaDB data directory"
    ok "MariaDB uninstalled and cleaned up."
    # End of script. MariaDB uninstalled.
    exit 0
fi

### ─── Connectivity Check ─────────────────────────────────────────────────

if ! ping -c1 -W1 archlinux.org &>/dev/null; then
    fail "No internet connection detected. Cannot proceed with MariaDB installation."
fi

### ─── Install MariaDB (Idempotent) ───────────────────────────────────────

if pacman -Qi mariadb &>/dev/null; then
    ok "MariaDB already installed."
else
    log "📥 Installing MariaDB..."
    sudo pacman -S --needed --noconfirm mariadb || fail "Failed to install MariaDB."
    ok "MariaDB installed."
fi

### ─── Initialize Database (if not already initialized) ───────────────────

if [[ ! -d /var/lib/mysql/mysql ]]; then
    log "🛠️ Initializing MariaDB data directory..."
    sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql || fail "MariaDB initialization failed."
    ok "MariaDB initialized."
else
    ok "MariaDB data directory already initialized."
fi

### ─── Enable + Start Service (idempotent) ────────────────────────────────

log "🚀 Enabling and starting mariadb.service..."
sudo systemctl enable --now mariadb || fail "Failed to enable/start mariadb.service"

### ─── Verify Service ─────────────────────────────────────────────────────

log "🔍 Verifying service status..."
if sudo systemctl is-active --quiet mariadb; then
    ok "MariaDB is running."
else
    sudo systemctl status mariadb | tee -a "$LOGFILE"
    fail "MariaDB service is not running."
fi

### ─── Show Installed Version ─────────────────────────────────────────────

mariadb_version=$(mysql --version 2>/dev/null || true)
[[ -n "$mariadb_version" ]] && log "MariaDB version: $mariadb_version"

### ─── Secure Installation (Interactive) ─────────────────────────────────

section "🛡️ Secure MariaDB Installation"

read -rsp "🔑 Enter new MariaDB root password: " mariadb_pass; echo
read -rsp "🔑 Confirm password: " mariadb_pass_confirm; echo
if [[ -z "$mariadb_pass" || "$mariadb_pass" != "$mariadb_pass_confirm" || ${#mariadb_pass} -lt 8 ]]; then
    fail "Password validation failed. Must not be empty, must match, and must be at least 8 characters."
fi
export MARIADB_ROOT_PASSWORD="$mariadb_pass"

if command -v mariadb-secure-installation &>/dev/null; then
    log "🔒 Running mariadb-secure-installation..."
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
        warn "⚠️ mariadb-secure-installation failed or partially succeeded."
    else
        ok "✅ mariadb-secure-installation completed."
    fi
else
    warn "mariadb-secure-installation not found, skipping secure setup."
fi

### ─── Enforce Root Password Manually (Always) ────────────────────────────

log "🔐 Enforcing root password manually via SQL (in case secure-installation didn’t apply it)..."
alter_root_sql=$(cat <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${mariadb_pass}');
FLUSH PRIVILEGES;
EOF
)

if echo "$alter_root_sql" | sudo mariadb -u root; then
    ok "✅ Root password enforced successfully after secure-installation."
else
    fail "❌ Failed to set root password. Please verify manually."
fi

### ─── Final Summary ─────────────────────────────────────────────────────

ok "🎉 MariaDB setup completed successfully!"

section "✅ MariaDB Final Status"
sudo systemctl status mariadb | tee -a "$LOGFILE"
mysql --version | tee -a "$LOGFILE"

# End of script. Your MariaDB is now locked down and ready for action!
