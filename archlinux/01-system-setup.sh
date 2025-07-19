#!/bin/bash
set -euo pipefail

# === Include Logging ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "🔧 Starting System Setup for Arch/Manjaro"

# === Update Pacman Mirrors ===
log "📡 Updating pacman mirrors..."
if ! sudo pacman-mirrors --fasttrack; then
    warn "Mirror update failed (non-fatal)"
fi

# === fstrim.timer ===
log "🧼 Checking fstrim.timer status..."
if systemctl is-enabled fstrim.timer &>/dev/null; then
    ok "fstrim.timer is enabled"
else
    warn "fstrim.timer is not enabled. You can run: sudo systemctl enable --now fstrim.timer"
fi

# === Swappiness Tuning ===
SWAPPINESS_VALUE=10
CURRENT=$(< /proc/sys/vm/swappiness)
log "⚙️ Current swappiness: $CURRENT"

if [[ "$CURRENT" -ne "$SWAPPINESS_VALUE" ]]; then
    log "Updating swappiness to $SWAPPINESS_VALUE..."
    echo "vm.swappiness=$SWAPPINESS_VALUE" | sudo tee /etc/sysctl.d/99-swappiness.conf >/dev/null
    if sudo sysctl -p /etc/sysctl.d/99-swappiness.conf; then
        ok "Swappiness updated to $SWAPPINESS_VALUE"
    else
        warn "Failed to apply new swappiness value"
    fi
else
    ok "Swappiness already set to $SWAPPINESS_VALUE"
fi

# === UFW Firewall ===
log "🛡️ Installing UFW and GUFW..."
if sudo pacman -S --noconfirm --needed ufw gufw; then
    ok "UFW and GUFW installed"
else
    fail "Failed to install UFW/GUFW"
fi

log "🔐 Enabling and starting UFW..."
if sudo ufw enable && sudo systemctl enable --now ufw; then
    ok "UFW enabled and running"
else
    fail "Failed to start or enable UFW"
fi

sudo ufw status verbose || warn "Could not retrieve UFW status"

# === GRUB Configuration ===
GRUB_CONF="/etc/default/grub"
log "🛠 Ensuring quiet splash is set in GRUB..."
if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_CONF"; then
    sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/' "$GRUB_CONF"
else
    echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' | sudo tee -a "$GRUB_CONF" >/dev/null
fi

log "🔄 Regenerating GRUB configuration..."
if command -v update-grub &>/dev/null; then
    sudo update-grub
elif command -v grub-mkconfig &>/dev/null; then
    sudo grub-mkconfig -o /boot/grub/grub.cfg
else
    warn "No GRUB update command found — please update manually"
fi
ok "GRUB configuration updated"

# === Language Tools ===
log "📘 Installing language tools: aspell, mythes, languagetool..."
if sudo pacman -S --noconfirm --needed aspell-en libmythes mythes-en languagetool; then
    ok "Language tools installed"
else
    warn "Failed to install some language tools"
fi

ok "🎉 System setup completed successfully!"
