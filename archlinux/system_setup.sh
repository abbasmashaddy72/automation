#!/bin/bash

set -e

LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/system_setup.log"
mkdir -p "$LOGDIR"

# === Colors ===
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}➤ $1${NC}" | tee -a "$LOGFILE"; }
ok() { echo -e "${GREEN}✔ $1${NC}" | tee -a "$LOGFILE"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}" | tee -a "$LOGFILE"; }
fail() {
    echo -e "${RED}✖ $1${NC}" | tee -a "$LOGFILE"
    exit 1
}

log "🔧 Starting system setup for Arch/Manjaro..."

# === Update Pacman Mirrors ===
log "📡 Updating pacman mirrors..."
sudo pacman-mirrors --fasttrack || warn "Mirror update failed (non-fatal)"

# === fstrim.timer ===
log "🧼 Checking fstrim.timer status..."
if sudo systemctl is-enabled fstrim.timer &>/dev/null; then
    ok "fstrim.timer is enabled"
else
    warn "fstrim.timer is not enabled (tip: sudo systemctl enable --now fstrim.timer)"
fi

# === Swappiness ===
SWAPPINESS_VALUE=10
log "⚙️ Checking current swappiness..."
CURRENT=$(cat /proc/sys/vm/swappiness)
echo "Current: $CURRENT" | tee -a "$LOGFILE"

if [[ "$CURRENT" -ne "$SWAPPINESS_VALUE" ]]; then
    log "Updating swappiness to $SWAPPINESS_VALUE..."
    echo "vm.swappiness=$SWAPPINESS_VALUE" | sudo tee /etc/sysctl.d/99-swappiness.conf >/dev/null
    sudo sysctl -p /etc/sysctl.d/99-swappiness.conf || warn "Failed to apply swappiness"
    ok "Swappiness updated"
else
    ok "Swappiness already set to $SWAPPINESS_VALUE"
fi

# === Install UFW + GUFW ===
log "🛡️ Installing firewall (UFW + GUFW)..."
sudo pacman -S --noconfirm ufw gufw || fail "UFW install failed"

log "🔐 Enabling UFW..."
sudo ufw enable || fail "Failed to enable UFW"
sudo systemctl enable --now ufw || fail "Failed to enable UFW systemd service"
sudo ufw status verbose || warn "Could not check UFW status"

# === GRUB Update (Auto) ===
GRUB_CONF="/etc/default/grub"
log "🛠 Updating GRUB config (quiet splash)..."
if grep -q "GRUB_CMDLINE_LINUX_DEFAULT" "$GRUB_CONF"; then
    sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/' "$GRUB_CONF"
else
    echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' | sudo tee -a "$GRUB_CONF" >/dev/null
fi

log "🔄 Regenerating GRUB config..."
if command -v update-grub &>/dev/null; then
    sudo update-grub
elif command -v grub-mkconfig &>/dev/null; then
    sudo grub-mkconfig -o /boot/grub/grub.cfg
else
    warn "GRUB update command not found!"
fi
ok "GRUB updated"

# === Language Tools ===
log "📘 Installing language tools..."
sudo pacman -S --noconfirm aspell-en libmythes mythes-en languagetool || warn "Language tools install failed"

ok "✅ System setup completed successfully!"
