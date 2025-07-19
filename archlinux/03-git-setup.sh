#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📦 Starting Git setup..."

# === Prompt for Git Details ===
read -rp "👤 Enter your Git username: " git_username
git_username=$(echo "$git_username" | xargs) # Trim whitespace
[[ -z "$git_username" ]] && fail "Git username cannot be empty."

read -rp "📧 Enter your Git email: " git_email
git_email=$(echo "$git_email" | xargs)
[[ -z "$git_email" ]] && fail "Git email cannot be empty."

# === Install Git and Credential Manager ===
log "🧩 Installing git and git-credential-manager..."
if command -v pamac &>/dev/null; then
    pamac install --no-confirm --needed git git-credential-manager || fail "Git installation failed via pamac"
else
    sudo pacman -S --noconfirm --needed git || fail "Git installation failed via pacman"
    warn "git-credential-manager not available via pacman. You may install it manually if needed."
fi
ok "Git installed"

# === Git Configuration ===
log "🔐 Configuring Git credential helper..."
git config --global credential.helper store || fail "Failed to set credential.helper"

log "✍️ Setting Git username and email..."
git config --global user.name "$git_username" || fail "Failed to set user.name"
git config --global user.email "$git_email" || fail "Failed to set user.email"

# === Summary ===
section "🔍 Git configuration summary:"
git config --list | tee -a "$LOGFILE"

ok "🎉 Git setup complete!"
