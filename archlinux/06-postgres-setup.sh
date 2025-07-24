#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 06-postgres-setup.sh
#   - Automated, idempotent PostgreSQL setup for all Arch-based distros
#   - Handles install, cluster init, service setup, password setting, uninstall
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

section "🐘 Starting PostgreSQL setup for $PLATFORM_STRING"

### ─── Uninstall Option ────────────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling PostgreSQL..."
    sudo systemctl stop postgresql || warn "Could not stop postgresql"
    sudo systemctl disable postgresql || warn "Could not disable postgresql"
    sudo pacman -Rs --noconfirm postgresql || warn "Could not remove PostgreSQL package"
    sudo rm -rf /var/lib/postgres/data || warn "Could not remove PostgreSQL data directory"
    ok "PostgreSQL uninstalled and cleaned up."
    # End of script. PostgreSQL uninstalled.
    exit 0
fi

### ─── Functions ──────────────────────────────────────────────────────────

install_postgres() {
    if pacman -Qi postgresql &>/dev/null; then
        ok "PostgreSQL already installed."
    else
        log "📦 Installing PostgreSQL..."
        sudo pacman -S --noconfirm --needed postgresql || fail "Failed to install PostgreSQL"
        ok "PostgreSQL installed."
    fi
}

init_postgres_db() {
    if [[ ! -d "/var/lib/postgres/data" || -z "$(ls -A /var/lib/postgres/data 2>/dev/null)" ]]; then
        log "🔧 Initializing PostgreSQL cluster..."
        sudo -u postgres initdb --locale "${LANG:-en_US.UTF-8}" -E UTF8 -D '/var/lib/postgres/data/' || fail "PostgreSQL initdb failed"
        ok "PostgreSQL initialized."
    else
        ok "PostgreSQL data directory already exists. Skipping initdb."
    fi
}

start_postgres_service() {
    log "🚀 Enabling and starting PostgreSQL service..."
    sudo systemctl enable --now postgresql || fail "Failed to enable/start PostgreSQL service"
    sleep 2
    if sudo systemctl is-active --quiet postgresql; then
        ok "PostgreSQL service is running."
    else
        sudo systemctl status postgresql | tee -a "$LOGFILE"
        fail "PostgreSQL service failed to start."
    fi
}

set_postgres_password() {
    # Prompt for password
    while true; do
        read -s -p "🔐 Enter new password for PostgreSQL 'postgres' user (min 8 chars): " POSTGRES_PASSWORD
        echo
        read -s -p "🔁 Confirm password: " POSTGRES_PASSWORD_CONFIRM
        echo
        if [[ "$POSTGRES_PASSWORD" == "$POSTGRES_PASSWORD_CONFIRM" && ${#POSTGRES_PASSWORD} -ge 8 ]]; then
            break
        else
            warn "❌ Passwords do not match or are too short. Please try again."
        fi
    done

    log "🔐 Setting password for 'postgres' user..."
    sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD '${POSTGRES_PASSWORD}';" || fail "Failed to set postgres password"
    ok "Password set for 'postgres' user."
}

show_postgres_version() {
    section "🐘 PostgreSQL Version & Service Status"
    sudo -u postgres psql -V | tee -a "$LOGFILE"
    sudo systemctl status postgresql | tee -a "$LOGFILE"
}

### ─── Execution ──────────────────────────────────────────────────────────

install_postgres
init_postgres_db
start_postgres_service
set_postgres_password
show_postgres_version

ok "🎉 PostgreSQL setup complete. User: postgres"

# End of script. Your PostgreSQL instance is ready for development!
