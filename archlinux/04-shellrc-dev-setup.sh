#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 04-shellrc-dev-setup.sh
#   - Adds Laravel/PHP dev environment setup for Zsh or Fish users
#   - Composer bin added to PATH conditionally (only if dir exists)
#   - Idempotent, self-documenting, and safe for reruns
##############################################################################

# ─── Library Checks and Bootstrap ──────────────────────────────────────────

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

ensure_supported_platform arch

section "⚡️ Dev Shell RC Setup for $PLATFORM_STRING"

# ─── Detect User Shell ────────────────────────────────────────────────────

CURRENT_SHELL="$(basename "$SHELL")"
log "Detected current shell: $CURRENT_SHELL"

if [[ "$CURRENT_SHELL" == "fish" ]]; then
    SHELL_TYPE="fish"
    SHELL_RC="$HOME/.config/fish/config.fish"
elif [[ "$CURRENT_SHELL" == "zsh" ]]; then
    SHELL_TYPE="zsh"
    SHELL_RC="$HOME/.zshrc"
else
    SHELL_TYPE="none"
fi

# ─── Bail If Unsupported ──────────────────────────────────────────────────

if [[ "$SHELL_TYPE" == "none" ]]; then
    warn "Only Zsh and Fish are supported by this script."
    fail "Detected shell: $CURRENT_SHELL. Please use Zsh or Fish."
fi

# ─── Main Logic ───────────────────────────────────────────────────────────

if [[ "$SHELL_TYPE" == "fish" ]]; then
    section "🐟 Fish shell detected: running Fish dev RC setup"
    setup_fish_devrc "$SHELL_RC"
else
    section "💤 Zsh detected (or default): running Zsh dev RC setup"
    setup_zsh_devrc "$SHELL_RC"
fi

ok "🚀 Developer shell RC setup complete for $SHELL_TYPE! Enjoy productivity!"
exit 0

# ─── Functions for Each Shell ─────────────────────────────────────────────

setup_fish_devrc() {
    local FISHRC="$1"
    local HEADER="# === CUSTOM DEV SHELL SETUP ==="
    local BACKUP="$FISHRC.backup.$(date +%Y%m%d%H%M%S)"

    if [[ -f "$FISHRC" ]]; then
        cp "$FISHRC" "$BACKUP" && ok "🔁 Backup created: $BACKUP"
        if grep -qF "$HEADER" "$FISHRC"; then
            warn "Dev setup already present in config.fish. Skipping."
            return
        fi
    else
        touch "$FISHRC"
        warn "No config.fish found. Created a new one."
    fi

    log "🔧 Appending Composer PATH (conditional) and dev tools to config.fish..."

    cat <<'EOF' >>"$FISHRC"

# === CUSTOM DEV SHELL SETUP ===
if test -d $HOME/.config/composer/vendor/bin
    set -gx PATH $HOME/.config/composer/vendor/bin $PATH
end

# Project cleanup helpers
alias clean-npm 'rm -rf node_modules package-lock.json; and npm install'
alias clean-composer 'rm -rf vendor composer.lock; and composer install'

function vbin
    set bin ./vendor/bin/$argv[1]
    set argv (string trim -- $argv[2..-1])
    if test -x $bin
        $bin $argv
    else
        echo "🔴 '$argv[1]' not found or not executable in vendor/bin"
    end
end

function artisan
    if test -f artisan
        php artisan $argv
    else
        echo "🔴 artisan not found in current directory"
    end
end

alias pint 'vbin pint'
alias sail 'vbin sail'
alias fixer 'vbin php-cs-fixer'
alias pest 'vbin pest'
alias phpunit 'vbin phpunit'

EOF

    ok "✅ Dev shell setup added to config.fish"
    warn "Restart Fish shell or run: source $FISHRC to apply changes."
}

setup_zsh_devrc() {
    local ZSHRC="$1"
    local HEADER="# === CUSTOM DEV SHELL SETUP ==="
    local BACKUP="$ZSHRC.backup.$(date +%Y%m%d%H%M%S)"

    if [[ -f "$ZSHRC" ]]; then
        cp "$ZSHRC" "$BACKUP" && ok "🔁 Backup created: $BACKUP"
        if grep -qF "$HEADER" "$ZSHRC"; then
            warn "Dev setup already present in .zshrc. Skipping."
            return
        fi
    else
        touch "$ZSHRC"
        warn "No .zshrc found. Created a new one."
    fi

    log "🔧 Appending Composer PATH (conditional) and dev tools to .zshrc..."

    cat <<'EOF' >>"$ZSHRC"

# === CUSTOM DEV SHELL SETUP ===
if [[ -d "$HOME/.config/composer/vendor/bin" ]]; then
    export PATH="$HOME/.config/composer/vendor/bin:$PATH"
fi

# Project cleanup helpers
alias clean-npm='rm -rf node_modules package-lock.json && npm install'
alias clean-composer='rm -rf vendor composer.lock && composer install'

vbin() {
    local bin="./vendor/bin/$1"
    shift
    if [[ -x "$bin" ]]; then
        "$bin" "$@"
    else
        echo "🔴 '$1' not found or not executable in vendor/bin"
    fi
}

artisan() {
    if [[ -f artisan ]]; then
        php artisan "$@"
    else
        echo "🔴 artisan not found in current directory"
    fi
}

alias pint='vbin pint'
alias sail='vbin sail'
alias fixer='vbin php-cs-fixer'
alias pest='vbin pest'
alias phpunit='vbin phpunit'

EOF

    ok "✅ Dev shell setup added to .zshrc"
    warn "Restart your shell or run: source $ZSHRC to apply changes."
}

# End of script. Your shell RC is now corporate-cool and dev-turbocharged!
