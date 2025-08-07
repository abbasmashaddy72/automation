#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 07-php-valet-valkey-setup.sh
#   - Automated, idempotent setup for PHP, Composer, Valet, and Valkey on Arch
#   - Handles install, validation, custom PHP config, Valet park, and uninstall
#   - Requires: lib-logger.sh and lib-platform.sh in ../lib/
##############################################################################

### ─── Library Checks and Bootstrap ────────────────────────────────────────

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

ensure_supported_platform arch cachyos

section "📦 PHP, Composer, Valet, and Valkey Setup for $PLATFORM_STRING"

### ─── Uninstall Option ────────────────────────────────────────────────────

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
    # End of script. PHP stack uninstalled.
    exit 0
fi

### ─── Install PHP and Extensions ─────────────────────────────────────────

install_php() {
    section "📥 Installing PHP and extensions"
    local pkgs=(
        php             # Core PHP interpreter
        php-apcu        # APCu cache
        php-fpm         # FastCGI Process Manager
        php-gd          # Image manipulation
        php-iconv       # Character encoding conversion
        php-intl        # Intl (locale, formatting)
        php-json        # JSON support
        php-mbstring    # Multibyte string
        php-openssl     # OpenSSL functions
        php-pdo-mysql   # PDO MySQL/MariaDB
        php-redis       # Redis extension (works with Valkey)
        php-sqlite      # SQLite support
        php-tokenizer   # Tokenizer
        php-xdebug      # Debugger/profiler
        php-xml         # XML parsing
        php-zip         # Zip archives
        php-pdo         # PDO base
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

### ─── Install Node, NVM ──────────────────────────────────────────────────

install_nvm_node() {
    log "📥 Installing NVM, Node.js & npm..."
    sudo pacman -S --noconfirm --needed nvm nodejs npm || fail "Failed to install NVM, Node.js, NPM"
    ok "NVM, Node.js, NPM installed"
}

### ─── Install Composer ───────────────────────────────────────────────────

install_composer() {
    if command -v composer &>/dev/null; then
        ok "Composer already installed"
    else
        log "📥 Installing Composer..."
        sudo pacman -S --noconfirm --needed composer || fail "Failed to install Composer"
        ok "Composer installed"
    fi
}

### ─── Install Valet ──────────────────────────────────────────────────────

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

### ─── Install Valet Dependencies ─────────────────────────────────────────

install_valet_deps() {
    local valet_deps=(nss jq xsel networkmanager)
    log "📥 Installing Valet dependencies..."
    sudo pacman -S --noconfirm --needed "${valet_deps[@]}" || fail "Failed to install Valet dependencies"
    ok "Valet dependencies installed"
}

### ─── Enable PHP-FPM ─────────────────────────────────────────────────────

enable_php_fpm() {
    section "🛠 Enabling php-fpm"
    sudo systemctl enable --now php-fpm.service || fail "php-fpm service failed to start or enable"
    ok "php-fpm is active and enabled"
}

### ─── Write Custom PHP INI ───────────────────────────────────────────────

write_custom_php_ini() {
    section "⚙️ Writing local PHP performance settings"

    # Prompt for custom values with default fallbacks
    read -p "Enter max upload size (default: 64M): " upload_max_filesize
    upload_max_filesize="${upload_max_filesize:-64M}"

    read -p "Enter max post size (default: 64M): " post_max_size
    post_max_size="${post_max_size:-64M}"

    read -p "Enter memory limit (default: 512M): " memory_limit
    memory_limit="${memory_limit:-512M}"

    read -p "Enter max execution time (default: 300): " max_execution_time
    max_execution_time="${max_execution_time:-300}"

    # Set the file path for the custom PHP configuration
    CUSTOM_INI="/etc/php/conf.d/custom.ini"

    # Write the configuration values to the custom PHP INI file
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

memory_limit=$memory_limit
max_execution_time=$max_execution_time
upload_max_filesize=$upload_max_filesize
post_max_size=$post_max_size
EOF
    ok "Wrote performance config to $CUSTOM_INI"
}

### ─── Write Custom Nginx Upload Size Configuration ───────────────────────

write_custom_nginx_upload_conf() {
    section "⚙️ Writing custom Nginx upload size configuration"

    # Prompt for custom Nginx upload size
    read -p "Enter Nginx max body size (default: 1024M): " nginx_max_body_size
    nginx_max_body_size="${nginx_max_body_size:-1024M}"

    # Path to the Nginx configuration directory for custom files
    NGINX_CONF_DIR="/etc/nginx/conf.d"
    CUSTOM_NGINX_CONF="$NGINX_CONF_DIR/custom_upload.conf"

    # Write custom Nginx config to the new file
    sudo tee "$CUSTOM_NGINX_CONF" >/dev/null <<EOF
# Custom Nginx configuration for handling file uploads

client_max_body_size $nginx_max_body_size;
EOF

    ok "Created custom Nginx configuration: $CUSTOM_NGINX_CONF"
}

### ─── Write Custom PHP-FPM Configuration ─────────────────────────────────

write_custom_php_fpm_conf() {
    section "⚙️ Writing custom PHP-FPM upload size and memory limit configuration"

    # Prompt for custom PHP settings
    read -p "Enter PHP upload_max_filesize (default: 1024M): " upload_max_filesize
    upload_max_filesize="${upload_max_filesize:-1024M}"

    read -p "Enter PHP post_max_size (default: 1024M): " post_max_size
    post_max_size="${post_max_size:-1024M}"

    read -p "Enter PHP memory_limit (default: 1024M): " memory_limit
    memory_limit="${memory_limit:-1024M}"

    # Path to the PHP-FPM configuration directory
    PHP_FPM_CONF_DIR="/etc/php/php-fpm.d"
    CUSTOM_PHP_FPM_CONF="$PHP_FPM_CONF_DIR/custom_upload.conf"

    # Create a new PHP-FPM pool configuration for custom values
    sudo tee "$CUSTOM_PHP_FPM_CONF" >/dev/null <<EOF
; Custom PHP-FPM configuration for upload size and memory limits

php_admin_value[upload_max_filesize] = $upload_max_filesize
php_admin_value[post_max_size] = $post_max_size
php_admin_value[memory_limit] = $memory_limit
EOF

    ok "Created custom PHP-FPM configuration: $CUSTOM_PHP_FPM_CONF"
}

### ─── Enable Extra PHP Extensions ────────────────────────────────────────

enable_extra_php_extensions() {
    section "📎 Enabling additional PHP extensions"
    local extensions=(bcmath gd intl iconv mbstring pdo pdo_mysql sqlite3 zip)
    for ext in "${extensions[@]}"; do
        ini_file="/etc/php/conf.d/zz-$ext.ini"
        if [[ ! -f "$ini_file" ]]; then
            echo "extension=$ext" | sudo tee "$ini_file" >/dev/null
            ok "Enabled $ext via $ini_file"
        else
            warn "$ext already enabled"
        fi
    done
}

### ─── Install and Enable Valkey (Redis Replacement) ──────────────────────

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

### ─── Restart PHP-FPM ────────────────────────────────────────────────────

restart_php_fpm() {
    log "🔄 Restarting php-fpm..."
    sudo systemctl restart php-fpm.service || fail "Failed to restart php-fpm"
    ok "php-fpm restarted successfully"
}

### ─── Initialize Valet ───────────────────────────────────────────────────

valet_install() {
    section "🚀 Running valet install"
    valet install || fail "Valet install failed"
    ok "Valet installed and initialized successfully"
}

### ─── Final Tool Checks ──────────────────────────────────────────────────

final_checks() {
    section "🧪 Verifying tools in PATH"
    command -v composer &>/dev/null || fail "Composer is not available in PATH"
    command -v valet &>/dev/null || fail "Valet is not available in PATH"
    php -v | tee -a "$LOGFILE"
    valet --version | tee -a "$LOGFILE"
    ok "Composer, Valet, and PHP verified"
}

### ─── PHP Info Site Setup (Optional) ─────────────────────────────────────

create_phpinfo_site() {
    local target_folder="${1:-Local}"
    local base_dir="${PROJECT_SITES_DIR:-$HOME/Documents/Project-Sites}"
    local info_dir="$base_dir/$target_folder/info"
    local info_index="$info_dir/index.php"

    section "📝 Setting up PHP info page in $info_dir"
    if [[ ! -d "$info_dir" ]]; then
        mkdir -p "$info_dir" && ok "Created $info_dir"
    else
        warn "$info_dir already exists."
    fi

    if [[ ! -f "$info_index" ]]; then
        cat > "$info_index" <<EOF
<?php
phpinfo();
EOF
        ok "Created $info_index"
    else
        warn "$info_index already exists."
    fi

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

### ─── MAIN FLOW ──────────────────────────────────────────────────────────

install_php
install_nvm_node
install_composer
install_valet
install_valet_deps
enable_php_fpm
write_custom_php_ini
write_custom_nginx_upload_conf
write_custom_php_fpm_conf
enable_extra_php_extensions
restart_php_fpm
valet_install
install_valkey
final_checks

create_phpinfo_site "Local"
check_phpinfo_site

ok "🎉 PHP + Composer + Valet + Valkey setup completed!"

# End of script. Your PHP stack is ready for local development!
