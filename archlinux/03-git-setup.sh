#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 03-git-setup.sh
#
# Purpose
# -------
# Automated, idempotent Git setup for Arch-based distros:
# - Installs Git
# - Installs OpenSSH + xclip
# - Backs up existing ~/.gitconfig
# - Restores config with --uninstall
# - Configures Git username/email
# - Generates GitHub SSH key
# - Configures ssh-agent
# - Configures ~/.ssh/config
# - Auto converts GitHub HTTPS → SSH
# - Makes SSH auth persistent across reboots
#
# Supported Distros
# -----------------
# - Arch Linux
# - EndeavourOS
# - CachyOS
# - Garuda
# - Manjaro
#
# Usage
# -----
# ./03-git-setup.sh
# ./03-git-setup.sh --uninstall
##############################################################################

##############################################################################
# Error Handler
##############################################################################
on_err() {
    local line="$1"
    local cmd="$2"

    # Ignore intentional GitHub SSH exit code 1
    # GitHub returns exit code 1 even on SUCCESS
    if [[ "$cmd" == *"ssh -o StrictHostKeyChecking=accept-new -T git@github.com"* ]]; then
        return
    fi

    echo "❌ Error on line $line while running: $cmd" >&2
}

trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

##############################################################################
# Paths
##############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

##############################################################################
# Load Libraries
##############################################################################
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

if [[ ! -f "$LIBDIR/lib-aur-helper.sh" ]]; then
    echo "AUR helper library not found at: $LIBDIR/lib-aur-helper.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-aur-helper.sh"

ensure_supported_platform arch cachyos manjaro garuda endeavouros

section "🔧 Git setup for $PLATFORM_STRING"

##############################################################################
# Variables
##############################################################################
DO_UNINSTALL="n"

STATE_DIR="/var/lib/arch-dev-setup/03-git-setup"
BACKUP_DIR="$STATE_DIR/backups"
STATE_PKGS="$STATE_DIR/installed-packages.txt"
STATE_LAST_BACKUP="$STATE_DIR/last-backup.path"

GITCONFIG="$HOME/.gitconfig"

SSH_DIR="$HOME/.ssh"
SSH_KEY="$SSH_DIR/id_ed25519"
SSH_PUB="$SSH_KEY.pub"
SSH_CONFIG="$SSH_DIR/config"

##############################################################################
# Parse Arguments
##############################################################################
for arg in "$@"; do
    case "$arg" in
        --uninstall)
            DO_UNINSTALL="y"
        ;;
        -h|--help)
cat <<EOF
Usage:
  $0              Configure Git + GitHub SSH
  $0 --uninstall  Restore previous ~/.gitconfig

State directory:
  /var/lib/arch-dev-setup/03-git-setup/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

##############################################################################
# Sudo Authentication
##############################################################################
log "🔐 Please enter your sudo password to begin..."

if ! sudo -v; then
    fail "❌ Failed to authenticate sudo."
fi

sudo mkdir -p "$BACKUP_DIR" >/dev/null 2>&1 || true
sudo touch "$STATE_PKGS" >/dev/null 2>&1 || true

##############################################################################
# Helpers
##############################################################################
prompt_yn() {
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
            n|no) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

is_installed_pkg() {
    pacman -Q "$1" &>/dev/null
}

record_installed_pkgs() {
    local pkgs=("$@")
    local p

    for p in "${pkgs[@]}"; do
        if ! is_installed_pkg "$p"; then
            echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
        fi
    done
}

##############################################################################
# Backup Git Config
##############################################################################
backup_gitconfig_if_present() {
    if [[ -f "$GITCONFIG" ]]; then
        local ts
        local backup_path

        ts="$(date +%Y%m%d%H%M%S)"
        backup_path="$BACKUP_DIR/.gitconfig.backup.$ts"

        sudo cp -a "$GITCONFIG" "$backup_path"

        echo "$backup_path" | sudo tee "$STATE_LAST_BACKUP" >/dev/null

        sudo chown "$USER:$USER" "$backup_path" >/dev/null 2>&1 || true

        ok "Backed up existing ~/.gitconfig to: $backup_path"
    else
        ok "No existing ~/.gitconfig found (nothing to back up)."
    fi
}

##############################################################################
# Restore Git Config
##############################################################################
restore_gitconfig_from_state() {
    if [[ ! -f "$STATE_LAST_BACKUP" ]]; then
        warn "No recorded backup found."
        return 1
    fi

    local backup_path

    backup_path="$(sudo cat "$STATE_LAST_BACKUP" 2>/dev/null || true)"

    if [[ -z "$backup_path" || ! -f "$backup_path" ]]; then
        warn "Backup path invalid or missing."
        return 1
    fi

    sudo cp -a "$backup_path" "$GITCONFIG"

    sudo chown "$USER:$USER" "$GITCONFIG" >/dev/null 2>&1 || true

    ok "Restored ~/.gitconfig from: $backup_path"

    return 0
}

##############################################################################
# Uninstall
##############################################################################
uninstall_remove_recorded_packages() {
    if [[ ! -f "$STATE_PKGS" ]]; then
        warn "No recorded package file found."
        return 0
    fi

    mapfile -t pkgs < <(
        sudo sort -u "$STATE_PKGS" | sed '/^\s*$/d'
    )

    if [[ ${#pkgs[@]} -eq 0 ]]; then
        ok "No packages recorded by this script."
        return 0
    fi

    section "🧯 Packages installed by this script"

    printf '  - %s\n' "${pkgs[@]}"

    if prompt_yn "Remove these packages?" "n"; then
        local to_remove=()
        local p

        for p in "${pkgs[@]}"; do
            if is_installed_pkg "$p"; then
                to_remove+=("$p")
            fi
        done

        if [[ ${#to_remove[@]} -gt 0 ]]; then
            sudo pacman -Rns --noconfirm "${to_remove[@]}" || \
                warn "Some package removals failed."

            ok "Package removal attempted."
        else
            ok "No recorded packages currently installed."
        fi
    fi
}

run_uninstall() {
    section "🧯 Uninstall Mode"

    restore_gitconfig_from_state || true

    if prompt_yn "Remove SSH keys?" "n"; then
        rm -f "$SSH_KEY" "$SSH_PUB"
        ok "SSH keys removed."
    fi

    uninstall_remove_recorded_packages

    ok "✅ Uninstall complete."
}

##############################################################################
# Detect AUR Helper
##############################################################################
AUR_HELPER="$(detect_aur_helper)"

if [[ "$AUR_HELPER" == "none" ]]; then
    warn "No AUR helper detected."
else
    ok "AUR helper selected: $AUR_HELPER"
fi

##############################################################################
# Install Packages
##############################################################################
install_required_packages() {
    local packages=(
        git
        openssh
        xclip
    )

    log "📦 Installing required packages..."

    record_installed_pkgs "${packages[@]}"

    sudo pacman -S --noconfirm --needed "${packages[@]}" || \
        fail "Package installation failed."

    ok "Required packages installed."
}

##############################################################################
# Prompt Git User Details
##############################################################################
prompt_git_user_details() {
    local git_username
    local git_email

    while true; do
        read -r -p "👤 Enter your Git username: " git_username

        git_username="$(echo "$git_username" | xargs)"

        [[ -n "$git_username" ]] && break

        warn "Git username cannot be empty."
    done

    while true; do
        read -r -p "📧 Enter your Git email: " git_email

        git_email="$(echo "$git_email" | xargs)"

        if [[ "$git_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
            break
        fi

        warn "Invalid email address."
    done

    export GIT_USER_NAME="$git_username"
    export GIT_USER_EMAIL="$git_email"
}

##############################################################################
# Configure Git
##############################################################################
configure_git() {
    log "✍️ Setting Git username and email..."

    git config --global user.name "$GIT_USER_NAME" || \
        fail "Failed to set user.name"

    git config --global user.email "$GIT_USER_EMAIL" || \
        fail "Failed to set user.email"

    # Convert GitHub HTTPS → SSH
    git config --global url."git@github.com:".insteadOf \
        "https://github.com/"

    ok "Git identity configured."
}

##############################################################################
# Generate SSH Key
##############################################################################
generate_ssh_key() {
    mkdir -p "$SSH_DIR"
    chmod 700 "$SSH_DIR"

    if [[ -f "$SSH_KEY" ]]; then
        ok "SSH key already exists."
        return 0
    fi

    log "🔑 Generating SSH key..."

    ssh-keygen \
        -t ed25519 \
        -C "$GIT_USER_EMAIL" \
        -f "$SSH_KEY" \
        -N ""

    ok "SSH key generated."
}

##############################################################################
# Setup SSH Agent
##############################################################################
setup_ssh_agent() {
    log "🚀 Configuring ssh-agent..."

    if [[ -z "${SSH_AUTH_SOCK:-}" ]]; then
        eval "$(ssh-agent -s)" >/dev/null
    fi

    if ! ssh-add -l >/dev/null 2>&1; then
        ssh-add "$SSH_KEY" >/dev/null 2>&1 || \
            fail "Failed to add SSH key to ssh-agent"
    fi

    ok "SSH agent configured."
}

##############################################################################
# Configure SSH
##############################################################################
configure_ssh() {
    touch "$SSH_CONFIG"

    if ! grep -q "Host github.com" "$SSH_CONFIG"; then
        cat >> "$SSH_CONFIG" <<EOF

Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes

EOF
    fi

    chmod 600 "$SSH_CONFIG"

    ok "SSH config updated."
}

##############################################################################
# Persist SSH Agent
##############################################################################
configure_ssh_persistence() {
    local bashrc="$HOME/.bashrc"

    if ! grep -q "Auto-start ssh-agent" "$bashrc"; then
        cat >> "$bashrc" <<'EOF'

# Auto-start ssh-agent
if [ -z "$SSH_AUTH_SOCK" ]; then
    eval "$(ssh-agent -s)" >/dev/null
    ssh-add ~/.ssh/id_ed25519 >/dev/null 2>&1
fi

EOF
    fi

    ok "SSH agent auto-start configured."
}

##############################################################################
# Show Public Key
##############################################################################
show_public_key() {
    section "🔑 GitHub SSH Public Key"

    echo
    cat "$SSH_PUB"
    echo

    if command -v xclip &>/dev/null; then
        xclip -selection clipboard < "$SSH_PUB"
        ok "SSH public key copied to clipboard."
    fi

    echo
    echo "👉 Add this SSH key to GitHub:"
    echo "https://github.com/settings/keys"
    echo
}

##############################################################################
# Test GitHub SSH
##############################################################################
test_github_ssh() {
    log "🔍 Testing GitHub SSH authentication..."

    local output
    local ssh_exit

    set +e

    output="$(ssh \
        -o StrictHostKeyChecking=accept-new \
        -T git@github.com 2>&1)"

    ssh_exit=$?

    set -e

    echo "$output" | tee -a "$LOGFILE" >/dev/null || true

    # SUCCESS
    if echo "$output" | grep -qi "successfully authenticated"; then
        ok "GitHub SSH authentication successful."
        return 0
    fi

    # GitHub intentionally returns exit code 1 on success
    if [[ $ssh_exit -eq 1 ]] && \
       echo "$output" | grep -qi "successfully authenticated"; then
        ok "GitHub SSH authentication successful."
        return 0
    fi

    # Authentication incomplete
    warn "GitHub authentication not complete yet."
    warn "Add your SSH key to GitHub first."

    echo
    echo "GitHub SSH output:"
    echo "--------------------------------------------------"
    echo "$output"
    echo "--------------------------------------------------"
    echo

    return 1
}

##############################################################################
# Retry GitHub SSH Authentication
##############################################################################
retry_github_ssh_auth() {
    while true; do
        echo

        if prompt_yn "Re-check GitHub SSH authentication now?" "y"; then
            echo

            if test_github_ssh; then
                ok "GitHub SSH authentication verified successfully."
                break
            else
                warn "GitHub SSH authentication still not ready."
                warn "Make sure your SSH public key was added correctly:"
                echo "https://github.com/settings/keys"
            fi
        else
            warn "Skipping GitHub SSH re-check."
            break
        fi
    done
}

##############################################################################
# Main
##############################################################################
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

install_required_packages

backup_gitconfig_if_present

prompt_git_user_details

configure_git

generate_ssh_key

setup_ssh_agent

configure_ssh

configure_ssh_persistence

show_public_key

if ! test_github_ssh; then
    retry_github_ssh_auth
fi

section "🔍 Git configuration summary:"

git config --global --list | tee -a "$LOGFILE" || true

echo
ok "🎉 Git setup complete!"
echo

echo "You can now use GitHub without passwords:"
echo
echo "  git clone git@github.com:user/repo.git"
echo "  git pull"
echo "  git push"
echo
echo "⚠️ IMPORTANT:"
echo "Add the SSH public key above to:"
echo "https://github.com/settings/keys"
echo