#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 01-system-setup.sh
#
# Purpose
# -------
# Modular, robust system setup for Arch-based distros:
# - Mirrors refresh (where supported)
# - Full system upgrade
# - SSD trim timer (fstrim)
# - vm.swappiness tuning
# - Firewall setup:
#     * If firewalld exists → UFW is NOT required and will be skipped.
#     * If firewalld does not exist → use UFW (with nftables manager check).
# - GRUB cmdline tweak + config regen (only if GRUB exists)
# - Language tools install
# - Optional AUR enable for Pamac (if present)
# - Optional fingerprint support (fprintd)
#
# Safety / Reliability
# --------------------
# - Skips cleanly when a component isn't present
# - Stores backups + install state so you can rollback via --uninstall
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./01-system-setup.sh
#   ./01-system-setup.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (helpful diagnostics on failure)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
    echo "❌ Error on line $1 while running: $2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Library bootstrap
### ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
    echo "Logger library not found at: $LIBDIR/lib-logger.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
    echo "Platform library not found at: $LIBDIR/lib-platform.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-platform.sh"

# Keep this broad: most Arch-based distros should pass if lib-platform supports them.
ensure_supported_platform arch cachyos manjaro garuda endeavouros

section "🛠 Starting System Setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (for uninstall + backups)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL="y" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0              Run setup
  $0 --uninstall  Rollback changes made by this script

Backups + state:
  /var/lib/arch-dev-setup/01-system-setup/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/01-system-setup"
STATE_PKGS="$STATE_DIR/installed-packages.txt"
STATE_SWAPPINESS="$STATE_DIR/swappiness.prev"
STATE_FSTRIM="$STATE_DIR/fstrim.prev"
BACKUP_GRUB="$STATE_DIR/grub.default.bak"
BACKUP_PAMAC="$STATE_DIR/pamac.conf.bak"

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to begin..."
if ! sudo -v; then
    fail "❌ Failed to authenticate sudo."
fi
sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### UX helpers
### ─────────────────────────────────────────────────────────────────────────
prompt_yn() {
    # Usage: prompt_yn "Question?" "y|n"
    # Returns 0 for yes, 1 for no
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply
    
    while true; do
        if [[ "$default" == "y" ]]; then
            read -r -p "$prompt [Y/n]: " reply
            reply="${reply:-y}"
        else
            read -r -p "$prompt [y/N]: " reply
            reply="${reply:-n}"
        fi
        
        case "${reply,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

pkg_installed() {
    pacman -Q "$1" &>/dev/null
}

record_installed_pkgs() {
    # Record only packages that were NOT installed before this script ran.
    # This makes uninstall safe: we remove only what this script added.
    local pkgs=("$@")
    local p
    for p in "${pkgs[@]}"; do
        if ! pkg_installed "$p"; then
            echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
        fi
    done
}

backup_once() {
    # backup_once <src> <dest>
    local src="$1"
    local dest="$2"
    if [[ -f "$src" && ! -f "$dest" ]]; then
        sudo cp -a "$src" "$dest"
        ok "Backup created: $dest"
    fi
}

restore_if_exists() {
    # restore_if_exists <backup> <target>
    local backup="$1"
    local target="$2"
    if [[ -f "$backup" ]]; then
        sudo cp -a "$backup" "$target"
        ok "Restored: $target (from backup)"
    else
        warn "No backup found for: $target (expected: $backup)"
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Firewall policy: if firewalld exists, UFW is NOT required
### ─────────────────────────────────────────────────────────────────────────
firewall_service_active_or_enabled() {
    local svc="$1"
    systemctl is-active --quiet "$svc" 2>/dev/null || systemctl is-enabled --quiet "$svc" 2>/dev/null
}

firewalld_present() {
    pacman -Q firewalld &>/dev/null
}

should_skip_ufw_due_to_firewalld() {
    # Policy:
    # - If firewalld exists, we do NOT install/enable UFW.
    # - If firewalld is active/enabled, we definitely skip UFW.
    if firewalld_present; then
        if firewall_service_active_or_enabled firewalld.service; then
            ok "firewalld is present and active/enabled → skipping UFW (not required)."
        else
            ok "firewalld is installed → skipping UFW per policy."
            warn "If you want UFW instead, remove/disable firewalld first (or add a flag later)."
        fi
        return 0
    fi
    return 1
}

### ─────────────────────────────────────────────────────────────────────────
### Modular setup functions
### ─────────────────────────────────────────────────────────────────────────
update_mirrors() {
    log "📡 Updating pacman mirrors (if supported by this distro)..."
    
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
    fi
    
    if [[ "${ID:-}" == "cachyos" ]]; then
        if command -v cachyos-rate-mirrors &>/dev/null; then
            if sudo cachyos-rate-mirrors && sudo pacman -Sy; then
                ok "Mirrors updated via cachyos-rate-mirrors."
            else
                warn "CachyOS mirror update failed. Continuing anyway."
            fi
        else
            warn "cachyos-rate-mirrors not found. Skipping mirror refresh."
        fi
        return 0
    fi
    
    # Manjaro-family distros usually have pacman-mirrors; vanilla Arch often doesn't.
    local MIRROR_CMD=""
    if command -v pacman-mirrors &>/dev/null; then
        MIRROR_CMD="pacman-mirrors"
        elif command -v pacman_mirrors &>/dev/null; then
        MIRROR_CMD="pacman_mirrors"
    fi
    
    if [[ -n "$MIRROR_CMD" ]]; then
        if sudo "$MIRROR_CMD" --fasttrack && sudo pacman -Sy; then
            ok "Mirrors updated successfully."
        else
            warn "Mirror refresh attempted but failed. Continuing anyway."
        fi
    else
        warn "No mirror tool detected (normal on vanilla Arch). Skipping mirror refresh."
    fi
}

full_system_upgrade() {
    log "⬆️ Performing full system upgrade..."
    sudo pacman -Syu --noconfirm
    ok "System fully upgraded."
}

setup_fstrim() {
    log "🧼 SSD trim: checking fstrim.timer status..."
    
    if ! command -v systemctl &>/dev/null; then
        warn "systemctl not found (unexpected). Skipping fstrim."
        return 0
    fi
    
    # Record previous enablement state once (for uninstall)
    if [[ ! -f "$STATE_FSTRIM" ]]; then
        if systemctl is-enabled fstrim.timer &>/dev/null; then
            echo "enabled" | sudo tee "$STATE_FSTRIM" >/dev/null
        else
            echo "disabled" | sudo tee "$STATE_FSTRIM" >/dev/null
        fi
    fi
    
    if systemctl is-enabled fstrim.timer &>/dev/null; then
        ok "fstrim.timer is already enabled."
    else
        log "Enabling fstrim.timer..."
        sudo systemctl enable --now fstrim.timer && ok "fstrim.timer enabled." || warn "Failed to enable fstrim.timer."
    fi
}

tune_swappiness() {
    local desired="${SWAPPINESS_VALUE:-10}"
    local current
    current="$(< /proc/sys/vm/swappiness)"
    
    log "⚙️ vm.swappiness current=$current desired=$desired"
    
    # Save prior value once for uninstall rollback
    if [[ ! -f "$STATE_SWAPPINESS" ]]; then
        echo "$current" | sudo tee "$STATE_SWAPPINESS" >/dev/null
    fi
    
    if [[ "$current" -ne "$desired" ]]; then
        log "Updating swappiness to $desired..."
        echo "vm.swappiness=$desired" | sudo tee /etc/sysctl.d/99-swappiness.conf >/dev/null
        sudo sysctl -p /etc/sysctl.d/99-swappiness.conf >/dev/null || warn "Failed to apply swappiness immediately."
        ok "Swappiness updated to $desired"
    else
        ok "Swappiness already set to $desired"
    fi
}

install_ufw() {
    log "🛡️ Firewall: UFW setup..."
    
    # Policy: if firewalld exists, UFW is not required.
    if should_skip_ufw_due_to_firewalld; then
        return 0
    fi
    
    # Check nftables manager service conflicts (UFW can work with nft backend,
    # but managing nftables.service alongside UFW is asking for rule conflicts).
    if firewall_service_active_or_enabled nftables.service; then
        warn "nftables.service is active/enabled. UFW may conflict with it."
        
        if prompt_yn "Disable nftables.service to proceed with UFW?" "n"; then
            sudo systemctl disable --now nftables.service || warn "Could not disable nftables.service (continuing)"
        else
            warn "Skipping UFW because nftables.service was not disabled."
            return 0
        fi
    fi
    
    log "Installing UFW (+ GUFW)..."
    record_installed_pkgs ufw gufw
    sudo pacman -S --noconfirm --needed ufw gufw
    ok "UFW + GUFW installed."
}

enable_ufw() {
    # Policy: if firewalld exists, do NOT enable UFW.
    if should_skip_ufw_due_to_firewalld; then
        return 0
    fi
    
    if ! command -v ufw &>/dev/null; then
        warn "ufw command not found. Skipping enable step."
        return 0
    fi
    
    log "🔐 Firewall: checking UFW status..."
    if sudo ufw status 2>/dev/null | grep -q "Status: active"; then
        ok "UFW is already enabled."
    else
        log "Enabling UFW..."
        sudo ufw --force enable || warn "ufw enable failed."
        
        # Enable ufw service if present
        if systemctl list-unit-files | grep -q '^ufw\.service'; then
            sudo systemctl enable --now ufw || warn "Could not enable ufw.service."
        fi
        
        ok "UFW enable attempted."
    fi
    
    sudo ufw status verbose || warn "Could not retrieve UFW status."
}

configure_grub() {
    local grub_conf="/etc/default/grub"
    
    # If GRUB isn't present, don't pretend it is.
    if [[ ! -f "$grub_conf" ]]; then
        warn "GRUB config not found at $grub_conf. Skipping GRUB tweaks."
        return 0
    fi
    
    if ! command -v grub-mkconfig &>/dev/null && ! command -v update-grub &>/dev/null; then
        warn "GRUB update tools not found. Skipping GRUB tweaks."
        return 0
    fi
    
    log "🛠 GRUB: ensuring quiet splash is set..."
    backup_once "$grub_conf" "$BACKUP_GRUB"
    
    if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$grub_conf"; then
        if ! grep -q 'quiet splash' "$grub_conf"; then
            sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/' "$grub_conf"
            ok "GRUB_CMDLINE_LINUX_DEFAULT set to: quiet splash"
        else
            ok "GRUB already contains: quiet splash"
        fi
    else
        echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"' | sudo tee -a "$grub_conf" >/dev/null
        ok "Appended GRUB_CMDLINE_LINUX_DEFAULT to GRUB config."
    fi
    
    log "🔄 Regenerating GRUB configuration..."
    if command -v update-grub &>/dev/null; then
        sudo update-grub || warn "update-grub failed."
    else
        sudo grub-mkconfig -o /boot/grub/grub.cfg || warn "grub-mkconfig failed."
    fi
    
    ok "GRUB update step complete."
}

install_language_tools() {
    log "📘 Installing language tools (spellcheck + thesaurus)..."
    local pkgs=(aspell-en libmythes mythes-en languagetool)
    
    record_installed_pkgs "${pkgs[@]}"
    sudo pacman -S --noconfirm --needed "${pkgs[@]}" || warn "Failed to install some language tools."
    ok "Language tools install step complete."
}

enable_aur_support() {
    # Only applies if pamac exists; vanilla Arch may not have it.
    local pamac_conf="/etc/pamac.conf"
    
    if [[ ! -f "$pamac_conf" ]]; then
        warn "Pamac config not found ($pamac_conf). Skipping AUR enable step."
        return 0
    fi
    
    log "📦 Pamac: enabling AUR support in $pamac_conf..."
    backup_once "$pamac_conf" "$BACKUP_PAMAC"
    
    # Un-comment keys if commented
    sudo sed -Ei 's/^#(EnableAUR)/\1/' "$pamac_conf" || true
    sudo sed -Ei 's/^#(CheckAURUpdates)/\1/' "$pamac_conf" || true
    
    # Ensure boolean true
    sudo sed -Ei 's/^(EnableAUR\s*=).*/\1 true/' "$pamac_conf" || true
    sudo sed -Ei 's/^(CheckAURUpdates\s*=).*/\1 true/' "$pamac_conf" || true
    
    ok "Pamac AUR support enabled."
}

install_fprintd_optional() {
    log "🧤 Optional: Fingerprint support (fprintd)"
    if prompt_yn "Install fingerprint support (fprintd)?" "n"; then
        record_installed_pkgs fprintd
        sudo pacman -S --noconfirm --needed fprintd || warn "Failed to install fprintd."
        ok "fprintd install step complete."
    else
        log "Skipping fprintd."
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall (Rollback) Mode
### ─────────────────────────────────────────────────────────────────────────
uninstall_firewall() {
    log "🧯 Uninstall: firewall rollback..."
    
    # If firewalld exists, we never required UFW; just ensure UFW is disabled if present.
    if command -v ufw &>/dev/null; then
        sudo ufw --force disable || true
    fi
    if systemctl list-unit-files | grep -q '^ufw\.service'; then
        sudo systemctl disable --now ufw || true
    fi
    
    ok "Firewall uninstall step complete."
}

uninstall_restore_grub() {
    local grub_conf="/etc/default/grub"
    
    if [[ -f "$grub_conf" ]]; then
        log "🧯 Uninstall: restoring GRUB config if backup exists..."
        restore_if_exists "$BACKUP_GRUB" "$grub_conf"
        
        if command -v update-grub &>/dev/null; then
            sudo update-grub || warn "update-grub failed during uninstall."
            elif command -v grub-mkconfig &>/dev/null; then
            sudo grub-mkconfig -o /boot/grub/grub.cfg || warn "grub-mkconfig failed during uninstall."
        fi
    else
        warn "GRUB config not found. Nothing to restore."
    fi
}

uninstall_restore_pamac() {
    local pamac_conf="/etc/pamac.conf"
    if [[ -f "$pamac_conf" ]]; then
        log "🧯 Uninstall: restoring Pamac config if backup exists..."
        restore_if_exists "$BACKUP_PAMAC" "$pamac_conf"
    else
        warn "Pamac config not found. Nothing to restore."
    fi
}

uninstall_restore_swappiness() {
    log "🧯 Uninstall: restoring vm.swappiness..."
    
    sudo rm -f /etc/sysctl.d/99-swappiness.conf || true
    
    if [[ -f "$STATE_SWAPPINESS" ]]; then
        local prev
        prev="$(sudo cat "$STATE_SWAPPINESS" 2>/dev/null || echo "")"
        if [[ -n "$prev" ]]; then
            sudo sysctl -w "vm.swappiness=$prev" >/dev/null || warn "Failed to restore swappiness runtime value."
            ok "Swappiness restored to $prev"
            return 0
        fi
    fi
    
    warn "No previous swappiness recorded. Leaving runtime value unchanged."
}

uninstall_restore_fstrim() {
    log "🧯 Uninstall: restoring fstrim.timer enablement state..."
    
    if [[ -f "$STATE_FSTRIM" ]]; then
        local prev
        prev="$(sudo cat "$STATE_FSTRIM" 2>/dev/null || echo "")"
        case "$prev" in
            enabled)
                sudo systemctl enable --now fstrim.timer >/dev/null 2>&1 || warn "Failed to re-enable fstrim.timer."
                ok "fstrim.timer restored to enabled."
            ;;
            disabled)
                sudo systemctl disable --now fstrim.timer >/dev/null 2>&1 || warn "Failed to disable fstrim.timer."
                ok "fstrim.timer restored to disabled."
            ;;
            *)
                warn "Unknown stored fstrim state: $prev"
            ;;
        esac
    else
        warn "No stored fstrim state. Leaving as-is."
    fi
}

uninstall_remove_recorded_packages() {
    if [[ ! -f "$STATE_PKGS" ]]; then
        warn "No recorded package list found at $STATE_PKGS. Skipping package removal."
        return 0
    fi
    
    mapfile -t pkgs < <(sudo sort -u "$STATE_PKGS" | sed '/^\s*$/d' || true)
    
    if [[ ${#pkgs[@]} -eq 0 ]]; then
        warn "Recorded package list is empty. Nothing to remove."
        return 0
    fi
    
    log "🧯 Uninstall: packages installed by this script:"
    printf '  - %s\n' "${pkgs[@]}"
    
    if prompt_yn "Remove these packages now? (safe: only ones this script added)" "n"; then
        local to_remove=()
        local p
        for p in "${pkgs[@]}"; do
            if pkg_installed "$p"; then
                to_remove+=("$p")
            fi
        done
        
        if [[ ${#to_remove[@]} -gt 0 ]]; then
            sudo pacman -Rns --noconfirm "${to_remove[@]}" || warn "Package removal had issues (some may be in use)."
            ok "Package removal step complete."
        else
            ok "None of the recorded packages are installed. Nothing to remove."
        fi
    else
        log "Skipping package removal."
    fi
}

run_uninstall() {
    section "🧯 Running uninstall rollback"
    uninstall_firewall
    uninstall_restore_grub
    uninstall_restore_pamac
    uninstall_restore_swappiness
    uninstall_restore_fstrim
    uninstall_remove_recorded_packages
    ok "✅ Uninstall complete. (Rollback done where backups/state existed.)"
}

### ─────────────────────────────────────────────────────────────────────────
### Main
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

update_mirrors
full_system_upgrade
setup_fstrim
tune_swappiness
install_ufw
enable_ufw
configure_grub
install_language_tools
enable_aur_support
install_fprintd_optional

ok "🎉 System setup completed successfully!"
