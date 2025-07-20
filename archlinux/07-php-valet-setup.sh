#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

section "📦 PHP, Composer, and Valet Setup for $PLATFORM_STRING"
ensure_supported_platform arch manjaro

# === Uninstall Option ===
if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling PHP, Composer, Valet..."
    sudo systemctl stop php-fpm || warn "php-fpm was not running"
    sudo systemctl disable php-fpm || warn "php-fpm was not enabled"
    sudo pacman -Rs --noconfirm composer php php-fpm || warn "Could not remove PHP/Composer"
    composer global remove cpriego/valet-linux || warn "Could not remove Valet"
    sudo rm -f /etc/php/conf.d/custom.ini || warn "Could not remove custom PHP ini"
    ok "PHP, Composer, and Valet have been uninstalled."
    exit 0
fi

# === Helper: Parse PHP Version Argument (default: php) ===
PHP_VERSION="${1:-php}"
PHP_FPM_SERVICE="${PHP_VERSION}-fpm"
if [[ "$PHP_VERSION" != "php" ]]; then
    PHP_FPM_SERVICE="php${PHP_VERSION/./}-fpm"
fi

# === Modular Steps ===

install_php() {
    section "📥 Installing PHP and extensions ($PHP_VERSION)"
    local pkgs=(
        $PHP_VERSION
        ${PHP_VERSION}-apcu
        ${PHP_VERSION}-fpm
        ${PHP_VERSION}-gd
        ${PHP_VERSION}-iconv
        ${PHP_VERSION}-intl
        ${PHP_VERSION}-json
        ${PHP_VERSION}-mbstring
        ${PHP_VERSION}-openssl
        ${PHP_VERSION}-pdo-mysql
        ${PHP_VERSION}-redis
        ${PHP_VERSION}-sqlite
        ${PHP_VERSION}-tokenizer
        ${PHP_VERSION}-xdebug
        ${PHP_VERSION}-xml
        ${PHP_VERSION}-zip
        ${PHP_VERSION}-pdo
    )
    for pkg in "${pkgs[@]}"; do
        if pacman -Qi "$pkg" &>/dev/null; then
            ok "$pkg already installed."
        else
            sudo pacman -S --needed --noconfirm "$pkg" || warn "❌ Failed or skipped: $pkg"
            ok "Installed $pkg"
        fi
    done
}

install_nvm_node() {
    log "📥 Installing NVM, Node.js & npm..."
    sudo pacman -S --noconfirm --needed nvm nodejs npm || fail "Failed to install NVM, Node.js, NPM"
    ok "NVM, Node.js, NPM installed"
}

install_composer() {
    if command -v composer &>/dev/null; then
        ok "Composer already installed"
    else
        log "📥 Installing Composer..."
        sudo pacman -S --noconfirm --needed composer || fail "Failed to install Composer"
        ok "Composer installed"
    fi
}

add_composer_bin_to_path() {
    ZSHRC="$HOME/.zshrc"
    COMPOSER_LINE='export PATH="$HOME/.config/composer/vendor/bin:$PATH"'
    log "🔧 Ensuring Composer bin is in PATH..."

    if ! grep -Fxq "$COMPOSER_LINE" "$ZSHRC"; then
        # Backup .zshrc first!
        backup="$ZSHRC.backup.$(date +%Y%m%d%H%M%S)"
        cp "$ZSHRC" "$backup" && ok "Backed up .zshrc to $backup"
        echo "$COMPOSER_LINE" >>"$ZSHRC"
        ok "Composer bin path added to .zshrc"
    else
        warn "Composer bin path already exists in .zshrc"
    fi
}

install_valet() {
    export COMPOSER_HOME="$HOME/.config/composer"
    export PATH="$HOME/.config/composer/vendor/bin:$PATH"
    if command -v valet &>/dev/null; then
        ok "Valet already installed"
    else
        composer global require cpriego/valet-linux || fail "Failed to install valet-linux"
        ok "Valet installed globally"
    fi
}

install_valet_deps() {
    local valet_deps=(nss jq xsel networkmanager)
    log "📥 Installing Valet dependencies..."
    sudo pacman -S --noconfirm --needed "${valet_deps[@]}" || fail "Failed to install Valet dependencies"
    ok "Valet dependencies installed"
}

enable_php_fpm() {
    section "🛠 Enabling $PHP_FPM_SERVICE"
    if systemctl list-units --all | grep -q "$PHP_FPM_SERVICE.service"; then
        sudo systemctl enable --now "$PHP_FPM_SERVICE.service" || fail "$PHP_FPM_SERVICE service failed"
        ok "$PHP_FPM_SERVICE is active"
    else
        fail "$PHP_FPM_SERVICE.service not found. Was $PHP_FPM_SERVICE installed?"
    fi
}

write_custom_php_ini() {
    section "⚙️ Writing local PHP performance settings"
    CUSTOM_INI="/etc/php/conf.d/custom.ini"
    sudo tee "$CUSTOM_INI" >/dev/null <<EOF
; Local development PHP optimizations

opcache.enable=1
opcache.enable_cli=1
opcache.memory_consumption=128
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=10000
opcache.revalidate_freq=0
opcache.fast_shutdown=1

realpath_cache_size=4096K
realpath_cache_ttl=600

memory_limit=512M
max_execution_time=300
upload_max_filesize=64M
post_max_size=64M
EOF
    ok "Wrote performance config to $CUSTOM_INI"
}

final_checks() {
    section "🧪 Verifying tools in PATH"
    command -v composer &>/dev/null || fail "Composer is not available in PATH"
    command -v valet &>/dev/null || fail "Valet is not available in PATH"
    php -v | tee -a "$LOGFILE"
    valet --version | tee -a "$LOGFILE"
    ok "Composer, Valet, and PHP verified"
}

restart_php_fpm() {
    log "🔄 Restarting $PHP_FPM_SERVICE..."
    sudo systemctl restart "$PHP_FPM_SERVICE.service" || fail "Failed to restart $PHP_FPM_SERVICE"
    ok "$PHP_FPM_SERVICE restarted successfully"
}

# === Main Flow ===
install_php
install_nvm_node
install_composer
add_composer_bin_to_path
install_valet
install_valet_deps
enable_php_fpm
write_custom_php_ini
restart_php_fpm
final_checks

ok "🎉 PHP ($PHP_VERSION) + Composer + Valet setup completed!"
