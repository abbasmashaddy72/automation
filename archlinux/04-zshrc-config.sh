#!/bin/bash
set -euo pipefail

# === CONFIG ===
ZSHRC="$HOME/.zshrc"
BACKUP="$ZSHRC.backup.$(date +%Y%m%d%H%M%S)"
CUSTOM_HEADER="# === CUSTOM DEV SHORTCUTS ==="
INSTALL_IF_MISSING=false
RESTORE=false

# === Logger & Platform Detection ===
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

section "⚙️  Zsh dev shortcuts setup for $PLATFORM_STRING"

ensure_supported_platform arch manjaro

# === Parse Flags ===
for arg in "$@"; do
    case $arg in
        --install-if-missing) INSTALL_IF_MISSING=true ;;
        --restore) RESTORE=true ;;
    esac
done

# === Rollback Logic ===
if [[ "$RESTORE" == true ]]; then
    section "♻️  Restoring previous .zshrc backup..."
    LATEST_BACKUP=$(ls -t "$HOME"/.zshrc.backup.* 2>/dev/null | head -n1 || true)
    if [[ -f "$LATEST_BACKUP" ]]; then
        cp "$LATEST_BACKUP" "$ZSHRC"
        ok "Restored .zshrc from $LATEST_BACKUP"
        exit 0
    else
        fail "No backup .zshrc found to restore!"
    fi
fi

# === Check for zsh ===
if ! command -v zsh &>/dev/null; then
    warn "Zsh is not installed."

    if [[ "$INSTALL_IF_MISSING" == true ]]; then
        section "📦 Installing zsh..."
        sudo pacman -S --noconfirm --needed zsh || fail "Failed to install Zsh via pacman"
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

# === Backup .zshrc, confirm success ===
if [[ -f "$ZSHRC" ]]; then
    cp "$ZSHRC" "$BACKUP" && ok "🔁 Backup created: $BACKUP" || fail "Failed to backup .zshrc!"
else
    touch "$ZSHRC"
    warn "No .zshrc found. Created a new one."
fi

# === Check if already configured ===
if grep -q "$CUSTOM_HEADER" "$ZSHRC"; then
    warn "Shortcuts already added to .zshrc. Skipping."
    exit 0
fi

# === Append Dev Shortcuts, No Duplicates ===
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
