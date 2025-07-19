#!/bin/bash
set -euo pipefail

# === CONFIG ===
ZSHRC="$HOME/.zshrc"
CUSTOM_HEADER="# === CUSTOM DEV SHORTCUTS ==="
INSTALL_IF_MISSING=false

# === Logger Setup ===
LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/zshrc_config.log"
mkdir -p "$LOGDIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

# === Parse Flags ===
for arg in "$@"; do
    case $arg in
        --install-if-missing) INSTALL_IF_MISSING=true ;;
    esac
done

# === Check for zsh ===
if ! command -v zsh &>/dev/null; then
    warn "Zsh is not installed."

    if [[ "$INSTALL_IF_MISSING" == true ]]; then
        section "📦 Installing zsh..."

        if [[ -f /etc/arch-release ]]; then
            sudo pacman -S --noconfirm zsh || fail "Failed to install Zsh via pacman"
        elif grep -qi opensuse /etc/os-release; then
            sudo zypper install -y zsh || fail "Failed to install Zsh via zypper"
        else
            fail "Unsupported distro. Please install Zsh manually."
        fi

        ok "Zsh installed."
    else
        echo -e "${YELLOW}💡 Zsh is not installed. Run this script with:${NC}"
        echo -e "   ${BLUE}$0 --install-if-missing${NC}"
        exit 1
    fi
else
    ok "Zsh is already installed."
fi

# === Set as default shell ===
CURRENT_SHELL=$(basename "$SHELL")
if [[ "$CURRENT_SHELL" != "zsh" ]]; then
    chsh -s "$(command -v zsh)" "$USER" || warn "Failed to change default shell. Try: chsh -s $(which zsh)"
    ok "Shell set to Zsh for $USER"
fi

# === Backup .zshrc ===
if [[ -f "$ZSHRC" ]]; then
    cp "$ZSHRC" "$ZSHRC.backup"
    log "🔁 Backup created: $ZSHRC.backup"
else
    touch "$ZSHRC"
    warn "No .zshrc found. Created a new one."
fi

# === Skip if already configured ===
if grep -q "$CUSTOM_HEADER" "$ZSHRC"; then
    warn "Shortcuts already added to .zshrc. Skipping."
    exit 0
fi

# === Append Dev Shortcuts ===
log "🔧 Adding Laravel/PHP developer shortcuts to .zshrc..."

cat <<'EOF' >>"$ZSHRC"

# === CUSTOM DEV SHORTCUTS ===
export PATH="$HOME/.config/composer/vendor/bin:$PATH"

# Project cleanup helpers
alias clean-npm='rm -rf node_modules package-lock.json && npm install'
alias clean-composer='rm -rf vendor composer.lock && composer install'

# vendor/bin runner
vbin() {
    local bin="./vendor/bin/$1"
    shift
    if [[ -x "$bin" ]]; then
        "$bin" "$@"
    else
        echo "🔴 '$1' not found or not executable in vendor/bin"
    fi
}

# Laravel Artisan wrapper
artisan() {
    if [[ -f artisan ]]; then
        php artisan "$@"
    else
        echo "🔴 artisan not found in current directory"
    fi
}

# Common PHP dev tools
alias pint='vbin pint'
alias sail='vbin sail'
alias fixer='vbin php-cs-fixer'
alias pest='vbin pest'
alias phpunit='vbin phpunit'

EOF

ok "✅ Laravel/PHP shortcuts added to .zshrc"

# === Prompt to Reload ===
read -rp "⏎ Reload .zshrc now to apply changes? [y/N]: " reload_now
if [[ "$reload_now" =~ ^[Yy]$ ]]; then
    log "🔄 Reloading .zshrc..."
    exec zsh
else
    warn "You must reload your shell manually to use the new shortcuts."
fi
