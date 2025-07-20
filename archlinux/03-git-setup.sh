#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

section "📦 Starting Git setup for $PLATFORM_STRING"

# === Distro check: Only run on supported systems ===
ensure_supported_platform arch manjaro

# === Check Git Installation (Pacman first) ===
if ! command -v git &>/dev/null; then
    log "🔹 Installing git (pacman preferred)..."
    if sudo pacman -S --noconfirm --needed git; then
        ok "Git installed via pacman"
    elif command -v pamac &>/dev/null; then
        pamac install --no-confirm --needed git || fail "Git installation failed via pamac"
        ok "Git installed via pamac"
    else
        fail "Git installation failed: pacman and pamac both unavailable"
    fi
else
    ok "Git already installed"
fi

# === Prompt for Git Details ===
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

# === Backup Existing .gitconfig ===
GITCONFIG="$HOME/.gitconfig"
if [[ -f "$GITCONFIG" ]]; then
    backup="$GITCONFIG.backup.$(date +%Y%m%d%H%M%S)"
    cp "$GITCONFIG" "$backup"
    ok "Backed up existing .gitconfig to $backup"
fi

# === Git Credential Manager (Pacman preferred, fallback to pamac) ===
if ! git config --global credential.helper | grep -q 'manager'; then
    log "🧩 Installing git-credential-manager (pacman preferred)..."
    if sudo pacman -S --noconfirm --needed git-credential-manager &>/dev/null; then
        ok "git-credential-manager installed via pacman"
    elif command -v pamac &>/dev/null; then
        pamac install --no-confirm --needed git-credential-manager || warn "Failed to install git-credential-manager via pamac"
        ok "git-credential-manager installed via pamac"
    else
        warn "git-credential-manager not available via pacman or pamac. Consider manual install if needed."
    fi

    # Try to set if installed
    if command -v git-credential-manager &>/dev/null; then
        git config --global credential.helper manager || warn "Failed to set credential.helper to manager"
    else
        git config --global credential.helper store || warn "Falling back to credential.helper store"
    fi
else
    ok "Git credential manager already configured"
fi

# === Git Configuration ===
log "✍️ Setting Git username and email..."
git config --global user.name "$git_username" || fail "Failed to set user.name"
git config --global user.email "$git_email" || fail "Failed to set user.email"

# === Summary ===
section "🔍 Git configuration summary:"
git config --list | tee -a "$LOGFILE"

ok "🎉 Git setup complete!"

warn "To rollback your git config: mv $backup $GITCONFIG" || true
