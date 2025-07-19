#!/bin/bash

set -e

# === CONFIG ===
LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/zshrc_update.log"
ZSHRC="$HOME/.zshrc"
CUSTOM_HEADER="# === CUSTOM DEV SHORTCUTS ==="
INSTALL_IF_MISSING=false

# === COLORS ===
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# === HELPERS ===
log() { echo -e "${BLUE}➤ $1${NC}" | tee -a "$LOGFILE"; }
ok() { echo -e "${GREEN}✔ $1${NC}" | tee -a "$LOGFILE"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}" | tee -a "$LOGFILE"; }
fail() {
    echo -e "${RED}✖ $1${NC}" | tee -a "$LOGFILE"
    exit 1
}

# === CLI OPTIONS ===
for arg in "$@"; do
    case $arg in
    --install-if-missing) INSTALL_IF_MISSING=true ;;
    esac
done

# === INIT ===
mkdir -p "$LOGDIR"
touch "$LOGFILE"

# === Check Zsh Install ===
if ! command -v zsh &>/dev/null; then
    warn "Zsh is not installed on your system."

    if [[ "$INSTALL_IF_MISSING" == true ]]; then
        log "Attempting to install Zsh automatically..."

        # Detect distro
        if [ -f /etc/arch-release ]; then
            sudo pacman -Sy --noconfirm zsh || fail "Failed to install Zsh via pacman"
        elif grep -qi opensuse /etc/os-release; then
            sudo zypper install -y zsh || fail "Failed to install Zsh via zypper"
        else
            fail "Unsupported system. Please install Zsh manually."
        fi

        ok "Zsh installed successfully!"
    else
        echo ""
        echo -e "${YELLOW}💡 Zsh is required but not installed.${NC}"
        echo "Run this script with --install-if-missing to auto-install it:"
        echo ""
        echo "    ./zshrc_config.sh --install-if-missing"
        echo ""
        exit 1
    fi
else
    ok "Zsh is already installed."
fi

# === Set Default Shell ===
CURRENT_SHELL=$(basename "$SHELL")
if [[ "$CURRENT_SHELL" != "zsh" ]]; then
    chsh -s "$(command -v zsh)" "$(whoami)"
    ok "Default shell changed to Zsh"
fi

# === Backup .zshrc ===
if [[ -f "$ZSHRC" ]]; then
    cp "$ZSHRC" "$ZSHRC.backup"
    log "Backup created: $ZSHRC.backup"
else
    warn "No existing .zshrc found. Creating one..."
    touch "$ZSHRC"
fi

# === Skip if already configured ===
if grep -q "$CUSTOM_HEADER" "$ZSHRC"; then
    warn "Custom functions already exist in .zshrc — skipping"
    exit 0
fi

# === Append Functions ===
log "Appending Laravel/PHP dev shortcuts to .zshrc"

cat <<EOL >>"$ZSHRC"

$CUSTOM_HEADER
export PATH="\$HOME/.config/composer/vendor/bin:\$PATH"

alias clean-npm='rm -rf node_modules package-lock.json && npm install'
alias clean-composer='rm -rf vendor composer.lock && composer install'

vbin() {
    local bin="./vendor/bin/$1"
    shift

    if [ -x "$bin" ]; then
        "$bin" "$@"
    else
        echo "🔴 '$1' not found or not executable in vendor/bin"
    fi
}

artisan() {
    if [ -f artisan ]; then
        php artisan "$@"
    else
        echo "🔴 artisan file not found"
    fi
}

# Optional Aliases
alias pint='vbin pint'
alias sail='vbin sail'
alias fixer='vbin php-cs-fixer'
alias pest='vbin pest'
alias phpunit='vbin phpunit'
EOL

ok "Custom aliases and functions added to .zshrc"
