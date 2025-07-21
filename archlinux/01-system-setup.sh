#!/bin/bash
set -euo pipefail

# === Include Logging & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/../lib/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
if [[ ! -f "$SCRIPT_DIR/../lib/lib-platform.sh" ]]; then
    echo "Platform library not found! Exiting." >&2
    exit 1
fi

source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

# === Require Supported Platform ASAP ===
ensure_supported_platform arch manjaro

# Use PLATFORM_STRING only after platform check
section "🔧 Starting System Setup for $PLATFORM_STRING"
log "Detected platform: $PLATFORM_STRING"

# === Functions for Modular Steps ===

update_mirrors() {
    log "📡 Updating pacman mirrors..."
    if sudo pacman-mirrors --fasttrack && sudo pacman -Sy; then
        ok "Mirrors updated successfully."
    else
        fail "Mirror update failed."
    fi
}

full_system_upgrade() {
    log "⬆️ Performing full system upgrade..."
    if sudo pacman -Syu --noconfirm; then
        ok "System fully upgraded."
    else
        fail "System upgrade failed."
    fi
}

setup_fstrim() {
    log "🧼 Checking fstrim.timer status..."
    if systemctl is-enabled fstrim.timer &>/dev/null; then
        ok "fstrim.timer is enabled"
    else
        log "Enabling fstrim.timer..."
        sudo systemctl enable --now fstrim.timer && ok "fstrim.timer enabled" || warn "Failed to enable fstrim.timer"
    fi
}

tune_swappiness() {
    SWAPPINESS_VALUE=${SWAPPINESS_VALUE:-10}
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
}

install_ufw() {
    log "🛡️ Installing UFW and GUFW..."
    if sudo pacman -S --noconfirm --needed ufw gufw; then
        ok "UFW and GUFW installed"
    else
        fail "Failed to install UFW/GUFW"
    fi
}

enable_ufw() {
    log "🔐 Checking UFW status..."
    if sudo ufw status | grep -q "Status: active"; then
        ok "UFW is already enabled"
    else
        log "Enabling and starting UFW..."
        if sudo ufw enable && sudo systemctl enable --now ufw; then
            ok "UFW enabled and running"
        else
            fail "Failed to start or enable UFW"
        fi
    fi
    sudo ufw status verbose || warn "Could not retrieve UFW status"
}

configure_grub() {
    GRUB_CONF="/etc/default/grub"
    log "🛠 Ensuring quiet splash is set in GRUB..."
    if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_CONF"; then
        if ! grep -q 'quiet splash' "$GRUB_CONF"; then
            sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/' "$GRUB_CONF"
            log "Set quiet splash in GRUB config"
        else
            ok "GRUB already set to quiet splash"
        fi
    else
        echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' | sudo tee -a "$GRUB_CONF" >/dev/null
        log "Appended quiet splash to GRUB config"
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
}

install_language_tools() {
    log "📘 Installing language tools: aspell, mythes, languagetool..."
    if sudo pacman -S --noconfirm --needed aspell-en libmythes mythes-en languagetool; then
        ok "Language tools installed"
    else
        warn "Failed to install some language tools"
    fi
}

# === Execute Modular Steps ===

update_mirrors
full_system_upgrade
setup_fstrim
tune_swappiness
install_ufw
enable_ufw
configure_grub
install_language_tools

ok "🎉 System setup completed successfully!"
