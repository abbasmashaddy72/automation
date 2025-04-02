#!/bin/bash

set -euo pipefail

# === Setup ===
LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/git_setup.log"
mkdir -p "$LOGDIR"

timestamp() { date '+%F %T'; }
log() { echo "$(timestamp) | $*" | tee -a "$LOGFILE"; }
log_error() {
    echo "$(timestamp) | ❌ ERROR: $*" | tee -a "$LOGFILE"
    exit 1
}

log "📦 Starting Git setup..."

# === Prompt for Git Details ===
read -rp "👤 Enter your Git username: " git_username
git_username=$(echo "$git_username" | xargs) # trim spaces
[[ -z "$git_username" ]] && log_error "Git username cannot be empty."

read -rp "📧 Enter your Git email: " git_email
git_email=$(echo "$git_email" | xargs)
[[ -z "$git_email" ]] && log_error "Git email cannot be empty."

# === Install Git + Credential Manager ===
log "🧩 Installing git and git-credential-manager..."
sudo pacman -S --noconfirm --needed git git-credential-manager || log_error "Git installation failed"

# === Configure Git ===
log "🔐 Setting up Git Credential Helper..."
git config --global credential.helper store || log_error "Failed to configure Git credential helper"

log "✍️ Setting Git username and email..."
git config --global user.name "$git_username" || log_error "Failed to set Git username"
git config --global user.email "$git_email" || log_error "Failed to set Git email"

# === Summary ===
log "✅ Git setup complete!"
git config --list | tee -a "$LOGFILE"
