#!/bin/bash
set -euo pipefail

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

ensure_supported_platform arch manjaro
section "📦 PHP, Composer, Valet, and Valkey Setup for $PLATFORM_STRING"

# === Uninstall Option ===
if [[ "${1:-}" == "--uninstall" ]]; then
    section "🧹 Uninstalling PHP, Composer, Valet, and Valkey..."
    sudo systemctl stop php-fpm || warn "php-fpm was not running"
    sudo systemctl disable php-fpm || warn "php-fpm was not enabled"
    sudo systemctl stop valkey || warn "valkey was not running"
    sudo systemctl disable valkey || warn "valkey was not enabled"
    sudo pacman -Rs --noconfirm composer php php-fpm valkey || warn "Could not remove PHP/Composer/Valkey"
    composer global remove cpriego/valet-linux || warn "Could not remove Valet"
    sudo rm -f /etc/php/conf.d/custom.ini || warn "Could not remove custom PHP ini"
    ok "PHP, Composer, Valet, and Valkey have been uninstalled."
    exit 0
fi

# === Install PHP and Extensions ===
install_php() {
    section "📥 Installing PHP and extensions"
    local pkgs=(
        php             # Core PHP language interpreter
        php-apcu        # In-memory user data cache (APCu)
        php-fpm         # PHP FastCGI Process Manager (service for Nginx/Valet)
        php-gd          # Image manipulation library (GD)
        php-iconv       # Character encoding conversion (iconv)
        php-intl        # Internationalization, locale, number formatting (intl)
        php-json        # JSON encode/decode support
        php-mbstring    # Multibyte string handling (UTF-8 etc.)
        php-openssl     # OpenSSL functions (HTTPS, encryption)
        php-pdo-mysql   # PDO driver for MySQL/MariaDB databases
        php-redis       # Redis support (Valkey is a drop-in replacement)
        php-sqlite      # SQLite database support
        php-tokenizer   # Tokenizer support (for parsing, e.g. Blade, Composer)
        php-xdebug      # Debugger and profiler (Xdebug)
        php-xml         # XML parsing and handling
        php-zip         # Zip archive support
        php-pdo         # PDO database abstraction layer (base)
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

# === Install Node, NVM ===
install_nvm_node() {
    log "📥 Installing NVM, Node.js & npm..."
    sudo pacman -S --noconfirm --needed nvm nodejs npm || fail "Failed to install NVM, Node.js, NPM"
    ok "NVM, Node.js, NPM installed"
}

# === Install Composer ===
install_composer() {
    if command -v composer &>/dev/null; then
        ok "Composer already installed"
    else
        log "📥 Installing Composer..."
        sudo pacman -S --noconfirm --needed composer || fail "Failed to install Composer"
        ok "Composer installed"
    fi
}

# === Add Composer Bin to PATH ===
add_composer_bin_to_path() {
    ZSHRC="$HOME/.zshrc"
    COMPOSER_LINE='export PATH="$HOME/.config/composer/vendor/bin:$PATH"'
    log "🔧 Ensuring Composer bin is in PATH..."

    if ! grep -Fxq "$COMPOSER_LINE" "$ZSHRC"; then
        backup="$ZSHRC.backup.$(date +%Y%m%d%H%M%S)"
        cp "$ZSHRC" "$backup" && ok "Backed up .zshrc to $backup"
        echo "$COMPOSER_LINE" >>"$ZSHRC"
        ok "Composer bin path added to .zshrc"
    else
        warn "Composer bin path already exists in .zshrc"
    fi
}

# === Install Valet ===
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

# === Install Valet Dependencies ===
install_valet_deps() {
    local valet_deps=(nss jq xsel networkmanager)
    log "📥 Installing Valet dependencies..."
    sudo pacman -S --noconfirm --needed "${valet_deps[@]}" || fail "Failed to install Valet dependencies"
    ok "Valet dependencies installed"
}

# === Enable PHP-FPM ===
enable_php_fpm() {
    section "🛠 Enabling php-fpm"
    sudo systemctl enable --now php-fpm.service || fail "php-fpm service failed to start or enable"
    ok "php-fpm is active and enabled"
}

# === Write Custom PHP INI ===
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

# === Install and Enable Valkey (Redis replacement) ===
install_valkey() {
    section "🟠 Installing Valkey (Redis replacement)"
    if pacman -Qi valkey &>/dev/null; then
        ok "Valkey already installed."
    else
        sudo pacman -S --needed --noconfirm valkey || fail "Failed to install Valkey"
        ok "Valkey installed"
    fi
    sudo systemctl enable --now valkey || warn "Could not enable/start Valkey"
    sudo systemctl status valkey --no-pager || warn "Valkey service status check failed."
}

# === Restart PHP-FPM ===
restart_php_fpm() {
    log "🔄 Restarting php-fpm..."
    sudo systemctl restart php-fpm.service || fail "Failed to restart php-fpm"
    ok "php-fpm restarted successfully"
}

# === Initialize Valet ===
valet_install() {
    section "🚀 Running valet install"
    valet install || fail "Valet install failed"
    ok "Valet installed and initialized successfully"
}

# === Final Tool Checks ===
final_checks() {
    section "🧪 Verifying tools in PATH"
    command -v composer &>/dev/null || fail "Composer is not available in PATH"
    command -v valet &>/dev/null || fail "Valet is not available in PATH"
    php -v | tee -a "$LOGFILE"
    valet --version | tee -a "$LOGFILE"
    ok "Composer, Valet, and PHP verified"
}

# === PHP Info Site Setup (Optional, can move to another script) ===
create_phpinfo_site() {
    local target_folder="${1:-Local}"
    local base_dir="${PROJECT_SITES_DIR:-$HOME/Documents/Project-Sites}"
    local info_dir="$base_dir/$target_folder/info"
    local info_index="$info_dir/index.php"

    section "📝 Setting up PHP info page in $info_dir"

    # Create directory structure
    if [[ ! -d "$info_dir" ]]; then
        mkdir -p "$info_dir" && ok "Created $info_dir"
    else
        warn "$info_dir already exists."
    fi

    # Create index.php if not exists
    if [[ ! -f "$info_index" ]]; then
        cat > "$info_index" <<EOF
<?php
phpinfo();
EOF
        ok "Created $info_index"
    else
        warn "$info_index already exists."
    fi

    # Run valet park inside the parent directory
    pushd "$base_dir/$target_folder" >/dev/null
    valet park || warn "Could not run 'valet park' in $base_dir/$target_folder"
    popd >/dev/null
    ok "Ran 'valet park' in $base_dir/$target_folder"
}

check_phpinfo_site() {
    local url="http://info.test"
    section "🌐 Checking $url availability with curl"
    sleep 2
    if curl --silent --fail "$url" | grep -q 'phpinfo'; then
        ok "PHP info site is live and working at $url"
    else
        warn "PHP info site at $url did not return expected output. (Did you run 'valet park' in the parent folder? Wait a few seconds and retry if you just parked.)"
    fi
}

# === MAIN FLOW ===
install_php
install_nvm_node
install_composer
add_composer_bin_to_path
install_valet
install_valet_deps
enable_php_fpm
write_custom_php_ini
restart_php_fpm
valet_install
install_valkey
final_checks

# After valet park in Local, create PHP info site and check it
create_phpinfo_site "Local"
check_phpinfo_site

ok "🎉 PHP + Composer + Valet + Valkey setup completed!"
