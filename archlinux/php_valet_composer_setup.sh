#!/bin/bash

set -e

LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/php_valet_composer_setup.log"
mkdir -p "$LOGDIR"

echo "📦 Starting PHP, Composer, and Valet setup..." | tee -a "$LOGFILE"

# ===== Error Handling =====
log_error() {
    echo "[❌ ERROR] $1" | tee -a "$LOGFILE"
    exit 1
}

log_ok() {
    echo "[✅] $1" | tee -a "$LOGFILE"
}

# ===== PHP Packages =====
php_packages=(
    php php-apcu php-intl php-mbstring php-openssl php-pdo php-pdo-mysql
    php-tokenizer php-redis php-json php-xml php-zip php-xdebug php-iconv
    php-sqlite php-gd php-fpm
)

echo "📦 Installing PHP and required extensions..." | tee -a "$LOGFILE"

for pkg in "${php_packages[@]}"; do
    if pacman -Qi "$pkg" &>/dev/null; then
        log_ok "$pkg is already installed."
        continue
    fi

    if sudo pacman -S --noconfirm --needed "$pkg"; then
        log_ok "Installed $pkg"
    else
        echo "Skipped $pkg (not found or failed)" | tee -a "$LOGFILE"
    fi
done

log_ok "Finished installing PHP packages (some may be missing)."

# ===== NVM (Node Version Manager) via pacman =====
echo "📦 Installing NVM via pacman..." | tee -a "$LOGFILE"
if ! pacman -Qi nvm &>/dev/null; then
    sudo pacman -S --noconfirm nvm || log_error "Failed to install nvm"
else
    log_ok "nvm is already installed via pacman."
fi

# ===== Node.js & NPM =====
echo "📦 Installing Node.js and NPM..." | tee -a "$LOGFILE"
if ! sudo pacman -S --noconfirm nodejs npm; then
    log_error "Failed to install Node.js and NPM"
fi
log_ok "Node.js and NPM installed."

# ===== Composer (via pacman) =====
echo "📦 Installing Composer from official repo..." | tee -a "$LOGFILE"
if ! sudo pacman -S --noconfirm composer; then
    log_error "Failed to install Composer"
fi
log_ok "Composer installed via pacman."

# ===== Composer bin path in .zshrc =====
ZSHRC="$HOME/.zshrc"
COMPOSER_PATH_LINE='export PATH="$HOME/.config/composer/vendor/bin:$PATH"'

echo "🔧 Adding Composer vendor bin to PATH..." | tee -a "$LOGFILE"
if ! grep -q 'composer/vendor/bin' "$ZSHRC"; then
    echo "$COMPOSER_PATH_LINE" >>"$ZSHRC"
    log_ok "Added composer vendor bin to .zshrc"
else
    echo "ℹ️ Composer vendor bin already exists in .zshrc" | tee -a "$LOGFILE"
fi

# ===== Install Valet =====
echo "🚀 Installing Valet for Linux..." | tee -a "$LOGFILE"
export COMPOSER_HOME="$HOME/.config/composer"
export PATH="$HOME/.config/composer/vendor/bin:$PATH"

if ! composer global require cpriego/valet-linux; then
    log_error "Failed to require valet-linux via Composer"
fi
log_ok "Valet installed globally."

# ===== Valet Dependencies =====
valet_dependencies=(nss jq xsel networkmanager)

echo "📦 Installing dependencies for Valet..." | tee -a "$LOGFILE"
if ! sudo pacman -S --noconfirm "${valet_dependencies[@]}"; then
    log_error "Failed to install Valet dependencies"
fi
log_ok "Valet dependencies installed."

# ===== Enable & Check PHP-FPM =====
echo "🛠️ Enabling and checking php-fpm.service..." | tee -a "$LOGFILE"
if ! systemctl list-units --all | grep -q "php-fpm.service"; then
    log_error "php-fpm.service not found — is PHP FPM installed correctly?"
fi

sudo systemctl enable --now php-fpm.service
if ! systemctl is-active --quiet php-fpm.service; then
    log_error "php-fpm service failed to start"
fi
log_ok "php-fpm is running and enabled."

# ===== Final Checks =====
echo "🧪 Verifying Composer and Valet..." | tee -a "$LOGFILE"

if ! command -v composer &>/dev/null; then
    log_error "Composer is not available in PATH"
fi

if ! command -v valet &>/dev/null; then
    log_error "Valet is not available in PATH"
fi

log_ok "Composer and Valet verified."

echo "🎉 PHP, Composer, and Valet setup completed successfully!" | tee -a "$LOGFILE"

# ===== PHP Local Performance Tweaks =====
CUSTOM_INI_PATH="/etc/php/conf.d/custom.ini"

echo "⚙️ Writing PHP custom.ini for performance..." | tee -a "$LOGFILE"
sudo tee "$CUSTOM_INI_PATH" >/dev/null <<EOF
; Performance tweaks for local development

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

log_ok "custom.ini written to $CUSTOM_INI_PATH"

echo "🔄 Restarting php-fpm to apply changes..." | tee -a "$LOGFILE"
sudo systemctl restart php-fpm.service || log_error "Failed to restart php-fpm"
log_ok "php-fpm restarted with new PHP config."
