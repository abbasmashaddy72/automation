#!/bin/bash

set -e

LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/mariadb_setup.log"
mkdir -p "$LOGDIR"

log() { echo "$(date '+%F %T') | $1" | tee -a "$LOGFILE"; }
log_error() {
    echo "$(date '+%F %T') | ❌ ERROR: $1" | tee -a "$LOGFILE"
    exit 1
}

log "📦 Starting MariaDB setup..."

# === Install MariaDB ===
log "Installing MariaDB..."
if ! sudo pacman -S --needed --noconfirm mariadb; then
    log_error "Failed to install MariaDB."
fi

# === Initialize MariaDB ===
log "Initializing MariaDB..."
if ! sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql; then
    log_error "Failed to initialize MariaDB."
fi

# === Enable & Start Service ===
log "Enabling MariaDB systemd service..."
if ! sudo systemctl enable --now mariadb; then
    log_error "Failed to enable and start MariaDB service."
fi

# === Verify Service ===
log "Checking if MariaDB service is running..."
if ! sudo systemctl is-active --quiet mariadb; then
    sudo systemctl status mariadb | tee -a "$LOGFILE"
    log_error "MariaDB service is not active."
fi
log "✅ MariaDB service is active."

# === Secure MariaDB (semi-auto) ===
log "🛡️ Running secure MariaDB installation..."

echo -e "\n⚠️ NOTE: The next step is interactive. Please complete the MariaDB secure setup manually."
echo "    You can automate this later using expect, but it's safer to run it once manually."

if ! sudo mariadb-secure-installation; then
    log_error "Secure installation failed."
fi

log "🎉 MariaDB setup completed successfully!"
