#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 03-git-setup.sh
#   - Automated, idempotent Git setup for any Arch-based system
#   - Handles install (repo & AUR), backup, config, and credentials
#   - Supports --rollback flag to restore previous config
##############################################################################

### ─── Library Load and Platform Detection ────────────────────────────────

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

if [[ ! -f "$LIBDIR/lib-aur-helper.sh" ]]; then
    fail "AUR helper library not found! Exiting."
fi
source "$LIBDIR/lib-aur-helper.sh"

ensure_supported_platform arch

### ─── Rollback Logic ─────────────────────────────────────────────────────

GITCONFIG="$HOME/.gitconfig"
if [[ "${1:-}" == "--rollback" ]]; then
    section "⏪ Rolling back .gitconfig to last backup..."
    latest_backup=$(ls -1t "$GITCONFIG".backup.* 2>/dev/null | head -n1 || true)
    if [[ -f "$latest_backup" ]]; then
        cp -f "$latest_backup" "$GITCONFIG"
        ok "Restored $GITCONFIG from $latest_backup"
        section "🔍 Current Git configuration after rollback:"
        git config --list | tee -a "$LOGFILE"
        ok "🎉 Rollback complete!"
        exit 0
    else
        fail "No backup found to rollback!"
    fi
fi

### ─── AUR Helper Selection ───────────────────────────────────────────────

AUR_HELPER="$(detect_aur_helper)"
if [[ "$AUR_HELPER" == "none" ]]; then
    section "🔄 No AUR helper found! Installing yay for AUR support..."
    sudo pacman -S --needed --noconfirm yay || fail "Failed to install yay!"
    AUR_HELPER="yay"
fi
ok "AUR helper selected: $AUR_HELPER"

section "📦 Starting Git setup for $PLATFORM_STRING"

### ─── Install Git (repo first, then AUR helper if needed) ────────────────

install_git() {
    if command -v git &>/dev/null; then
        ok "Git already installed"
        return 0
    fi
    log "🔹 Installing git (pacman preferred)..."
    if sudo pacman -S --noconfirm --needed git; then
        ok "Git installed via pacman"
        return 0
    fi
    aur_install git && ok "Git installed via $AUR_HELPER" && return 0
    fail "Git installation failed: pacman and $AUR_HELPER both unavailable"
}
install_git

### ─── Prompt for User Details ────────────────────────────────────────────

prompt_git_user_details() {
    while true; do
        read -rp "👤 Enter your Git username: " git_username
        git_username=$(echo "$git_username" | xargs)
        [[ -n "$git_username" ]] && break
        warn "Git username cannot be empty."
    done
    while true; do
        read -rp "📧 Enter your Git email: " git_email
        git_email=$(echo "$git_email" | xargs)
        if [[ "$git_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
            break
        fi
        warn "Invalid or empty email. Please enter a valid email address."
    done
    export git_username git_email
}
prompt_git_user_details

### ─── Backup Existing Config ─────────────────────────────────────────────

backup=""
if [[ -f "$GITCONFIG" ]]; then
    backup="$GITCONFIG.backup.$(date +%Y%m%d%H%M%S)"
    cp "$GITCONFIG" "$backup"
    ok "Backed up existing .gitconfig to $backup"
fi

### ─── Install Git Credential Manager ─────────────────────────────────────

install_credential_manager() {
    if git config --global credential.helper | grep -q 'manager'; then
        ok "Git credential manager already configured"
        return
    fi

    log "🧩 Installing git-credential-manager (repo preferred, fallback to AUR)..."
    if sudo pacman -S --noconfirm --needed git-credential-manager &>/dev/null; then
        ok "git-credential-manager installed via pacman"
    else
        aur_install git-credential-manager && ok "git-credential-manager installed via $AUR_HELPER"
    fi

    # Configure Git to use it, else fallback
    if command -v git-credential-manager &>/dev/null; then
        git config --global credential.helper manager || warn "Failed to set credential.helper to manager"
    else
        git config --global credential.helper store || warn "Falling back to credential.helper store"
    fi
}
install_credential_manager

### ─── Set Git Username and Email ─────────────────────────────────────────

log "✍️ Setting Git username and email..."
git config --global user.name "$git_username" || fail "Failed to set user.name"
git config --global user.email "$git_email" || fail "Failed to set user.email"

### ─── Summary and Success ────────────────────────────────────────────────

section "🔍 Git configuration summary:"
git config --list | tee -a "$LOGFILE"

ok "🎉 Git setup complete!"

# End of script. Go forth and commit with confidence!
