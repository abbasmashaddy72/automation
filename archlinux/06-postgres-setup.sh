#!/bin/bash

set -euo pipefail

# === Setup ===
LOGFILE="$HOME/logs/postgres_setup.log"
mkdir -p "$(dirname "$LOGFILE")"

timestamp() { date '+%F %T'; }
log() { echo "$(timestamp) | $*" | tee -a "$LOGFILE"; }
log_error() { echo "$(timestamp) | ❌ $*" | tee -a "$LOGFILE"; exit 1; }

log "📦 Installing PostgreSQL..."
sudo pacman -S --noconfirm --needed postgresql || log_error "Failed to install PostgreSQL"

# === Prompt for postgres password securely ===
while true; do
    read -s -p "🔐 Enter new password for PostgreSQL 'postgres' user: " POSTGRES_PASSWORD
    echo
    read -s -p "🔁 Confirm password: " POSTGRES_PASSWORD_CONFIRM
    echo
    if [[ "$POSTGRES_PASSWORD" == "$POSTGRES_PASSWORD_CONFIRM" && -n "$POSTGRES_PASSWORD" ]]; then
        break
    else
        echo "❌ Passwords do not match or were empty. Try again."
    fi
done

# === Initialize DB if needed ===
if [ ! -d "/var/lib/postgres/data" ]; then
    log "🔧 Initializing PostgreSQL cluster..."
    sudo -u postgres initdb --locale "$LANG" -E UTF8 -D '/var/lib/postgres/data/' || log_error "initdb failed"
else
    log "✅ PostgreSQL data directory already exists. Skipping initdb."
fi

# === Enable and start PostgreSQL ===
log "🚀 Enabling and starting PostgreSQL service..."
sudo systemctl enable --now postgresql || log_error "Failed to start PostgreSQL service"

# === Wait and verify ===
sleep 2
sudo systemctl is-active --quiet postgresql && log "✅ PostgreSQL service is running." || log_error "PostgreSQL failed to start"

# === Set postgres password ===
log "🔐 Setting postgres user password..."
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD '${POSTGRES_PASSWORD}';" || log_error "Failed to set postgres password"

log "🎉 PostgreSQL setup complete. User: postgres"
