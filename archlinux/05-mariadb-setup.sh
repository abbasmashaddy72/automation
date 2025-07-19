#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📦 Starting MariaDB setup..."

# === 1. Install MariaDB ===
log "📥 Installing MariaDB..."
if ! sudo pacman -S --needed --noconfirm mariadb; then
    fail "Failed to install MariaDB."
fi
ok "MariaDB installed."

# === 2. Initialize Database ===
log "🛠️ Initializing MariaDB data directory..."
if ! sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql; then
    fail "MariaDB initialization failed."
fi
ok "MariaDB initialized."

# === 3. Enable + Start Service ===
log "🚀 Enabling and starting mariadb.service..."
if ! sudo systemctl enable --now mariadb; then
    fail "Failed to enable/start mariadb.service"
fi

# === 4. Verify Service ===
log "🔍 Verifying service status..."
if ! sudo systemctl is-active --quiet mariadb; then
    sudo systemctl status mariadb | tee -a "$LOGFILE"
    fail "MariaDB service is not running."
fi
ok "MariaDB is running."

# === 5. Secure Installation (Interactive) ===
section "🛡️ Secure MariaDB Installation (manual step)"

echo -e "\n${YELLOW}⚠️  NOTE: The following step is interactive.${NC}"
echo -e "   It's recommended to complete it manually the first time.\n"

if ! sudo mariadb-secure-installation; then
    fail "Secure installation failed."
fi

ok "🎉 MariaDB setup completed successfully!"
