#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📦 PHP, Composer, and Valet Setup"

# === PHP Packages ===
php_packages=(
    php
    php-apcu
    php-fpm
    php-gd
    php-iconv
    php-intl
    php-json
    php-mbstring
    php-openssl
    php-pdo-mysql
    php-redis
    php-sqlite
    php-tokenizer
    php-xdebug
    php-xml
    php-zip
    php-pdo
)

log "📥 Installing PHP and extensions..."
for pkg in "${php_packages[@]}"; do
    if pacman -Qi "$pkg" &>/dev/null; then
        ok "$pkg is already installed."
    else
        sudo pacman -S --needed --noconfirm "$pkg" || warn "❌ Failed or skipped: $pkg"
        ok "Installed $pkg"
    fi
done

# === Install NVM ===
log "📥 Installing NVM..."
if ! pacman -Qi nvm &>/dev/null; then
    sudo pacman -S --noconfirm nvm || fail "Failed to install nvm"
else
    ok "nvm already installed"
fi

# === Node.js & NPM ===
log "📥 Installing Node.js & npm..."
sudo pacman -S --noconfirm nodejs npm || fail "Failed to install Node.js & NPM"
ok "Node.js and NPM installed"

# === Composer ===
log "📥 Installing Composer..."
sudo pacman -S --noconfirm composer || fail "Failed to install Composer"
ok "Composer installed"

# === Add Composer bin to PATH in .zshrc ===
ZSHRC="$HOME/.zshrc"
COMPOSER_LINE='export PATH="$HOME/.config/composer/vendor/bin:$PATH"'
log "🔧 Ensuring Composer bin is in PATH..."

if ! grep -q 'composer/vendor/bin' "$ZSHRC"; then
    echo "$COMPOSER_LINE" >>"$ZSHRC"
    ok "Composer bin path added to .zshrc"
else
    warn "Composer bin path already exists in .zshrc"
fi

# === Install Valet for Linux ===
section "🚀 Installing Valet"

export COMPOSER_HOME="$HOME/.config/composer"
export PATH="$HOME/.config/composer/vendor/bin:$PATH"

composer global require cpriego/valet-linux || fail "Failed to install valet-linux"
ok "Valet installed globally"

# === Valet Dependencies ===
valet_deps=(nss jq xsel networkmanager)
log "📥 Installing Valet dependencies..."
sudo pacman -S --noconfirm "${valet_deps[@]}" || fail "Failed to install Valet dependencies"
ok "Valet dependencies installed"

# === Enable php-fpm ===
section "🛠 Enabling php-fpm"
if systemctl list-units --all | grep -q "php-fpm.service"; then
    sudo systemctl enable --now php-fpm.service || fail "php-fpm service failed"
    ok "php-fpm is active"
else
    fail "php-fpm.service not found. Was php-fpm installed?"
fi

# === Final Checks ===
section "🧪 Verifying tools in PATH"
command -v composer &>/dev/null || fail "Composer is not available in PATH"
command -v valet &>/dev/null || fail "Valet is not available in PATH"
ok "Composer and Valet available"

# === PHP Custom Config ===
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

log "🔄 Restarting php-fpm..."
sudo systemctl restart php-fpm.service || fail "Failed to restart php-fpm"
ok "php-fpm restarted successfully"

ok "🎉 PHP + Composer + Valet setup completed!"
