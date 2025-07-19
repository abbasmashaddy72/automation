#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "🐘 Starting PostgreSQL setup..."

# === Install PostgreSQL ===
log "📦 Installing PostgreSQL..."
sudo pacman -S --noconfirm --needed postgresql || fail "Failed to install PostgreSQL"
ok "PostgreSQL installed."

# === Prompt for postgres password securely ===
while true; do
    read -s -p "🔐 Enter new password for PostgreSQL 'postgres' user: " POSTGRES_PASSWORD
    echo
    read -s -p "🔁 Confirm password: " POSTGRES_PASSWORD_CONFIRM
    echo
    if [[ "$POSTGRES_PASSWORD" == "$POSTGRES_PASSWORD_CONFIRM" && -n "$POSTGRES_PASSWORD" ]]; then
        break
    else
        warn "❌ Passwords do not match or were empty. Please try again."
    fi
done

# === Initialize database if not already present ===
if [ ! -d "/var/lib/postgres/data" ]; then
    log "🔧 Initializing PostgreSQL cluster..."
    sudo -u postgres initdb --locale "$LANG" -E UTF8 -D '/var/lib/postgres/data/' || fail "PostgreSQL initdb failed"
    ok "PostgreSQL initialized."
else
    ok "PostgreSQL data directory already exists. Skipping initdb."
fi

# === Enable and Start PostgreSQL ===
log "🚀 Enabling and starting PostgreSQL service..."
sudo systemctl enable --now postgresql || fail "Failed to enable/start PostgreSQL service"

# === Check service status ===
sleep 2
if sudo systemctl is-active --quiet postgresql; then
    ok "PostgreSQL service is running."
else
    sudo systemctl status postgresql | tee -a "$LOGFILE"
    fail "PostgreSQL service failed to start."
fi

# === Set password for postgres user ===
log "🔐 Setting password for 'postgres' user..."
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD '${POSTGRES_PASSWORD}';" || fail "Failed to set postgres password"

ok "🎉 PostgreSQL setup complete. User: postgres"
