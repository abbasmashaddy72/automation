#!/bin/bash

set -e

# === Defaults ===
INSTALL_ALL=false
CATEGORY_DEV=false
CATEGORY_BROWSERS=false
CATEGORY_IDES=false
CATEGORY_TOOLS=false
CATEGORY_MEDIA=false

# === Helpers ===
log() { echo -e "\033[1;34m➤ $1\033[0m"; }
ok() { echo -e "\033[1;32m✔ $1\033[0m"; }
warn() { echo -e "\033[1;33m⚠ $1\033[0m"; }
fail() {
    echo -e "\033[1;31m✖ $1\033[0m"
    exit 1
}

execute_command() {
    log "$2"
    eval "$1" && ok "$2" || fail "$2"
}

# === Parse CLI Flags ===
for arg in "$@"; do
    case $arg in
    --all) INSTALL_ALL=true ;;
    --dev) CATEGORY_DEV=true ;;
    --browsers) CATEGORY_BROWSERS=true ;;
    --ides) CATEGORY_IDES=true ;;
    --tools) CATEGORY_TOOLS=true ;;
    --media) CATEGORY_MEDIA=true ;;
    --help)
        echo "Usage: ./install-script.sh [--all|--dev|--browsers|--ides|--tools|--media]"
        exit 0
        ;;
    esac
done

# === Update Repos ===
execute_command "sudo zypper --non-interactive ref" "Refreshing repository metadata"
execute_command "sudo zypper --non-interactive update" "System upgrade"

# === Swappiness Optimization ===
SWAPPINESS_VALUE=10
CURRENT=$(cat /proc/sys/vm/swappiness)
[[ "$CURRENT" -ne "$SWAPPINESS_VALUE" ]] &&
    execute_command "echo 'vm.swappiness=$SWAPPINESS_VALUE' | sudo tee -a /etc/sysctl.conf && sudo sysctl -p" "Optimizing swappiness to $SWAPPINESS_VALUE"

# === Add External Repos ===
log "Adding external repositories..."
REPO_LIST=(
    "http://dl.google.com/linux/chrome/rpm/stable/x86_64 google-chrome"
    "https://brave-browser-rpm-release.s3.brave.com/brave-browser.repo brave-browser"
    "https://download.opensuse.org/repositories/home:deltafox/openSUSE_Tumbleweed/home:deltafox.repo ferdium"
    "https://download.opensuse.org/repositories/home:cabelo:innovators/openSUSE_Tumbleweed/home:cabelo:innovators.repo pycharm"
    "https://download.opensuse.org/repositories/home:ahjolinna/openSUSE_Tumbleweed/home:ahjolinna.repo firefox-dev"
    "https://download.opensuse.org/repositories/home:ecsos/openSUSE_Tumbleweed/home:ecsos.repo android-filezilla-dbeaver"
    "https://download.sublimetext.com/rpm/stable/x86_64/sublime-text.repo sublime-text"
)

for entry in "${REPO_LIST[@]}"; do
    IFS=' ' read -r url name <<<"$entry"
    sudo zypper --non-interactive addrepo --check --refresh "$url" "$name"
done

# === Import GPG Keys ===
execute_command "sudo rpm --import https://dl.google.com/linux/linux_signing_key.pub" "Import Google Chrome key"
execute_command "sudo rpm --import https://brave-browser-rpm-release.s3.brave.com/brave-core.asc" "Import Brave key"
execute_command "sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc" "Import VSCode key"
execute_command "sudo rpm --import https://download.sublimetext.com/sublimehq-rpm-pub.gpg" "Import Sublime key"

# === Refresh Again After Adding Repos ===
execute_command "sudo zypper --non-interactive ref" "Refreshing repositories (post-add)"

# === Remove Discover ===
execute_command "sudo zypper --non-interactive rm discover" "Removing Discover"

# === Install Core Apps ===
log "Installing required packages..."

COMMON_PACKAGES=(
    zsh git curl htop unzip jq xsel wget
    php8 php8-bcmath php8-curl php8-fpm php8-gd php8-mbstring
    php8-mysql php8-openssl php8-pdo php8-pear php8-devel
    php8-zip php8-intl php8-posix php8-fileinfo php8-exif php8-imagick
    nginx mariadb mariadb-client nodejs20 mozilla-nss-tools
    power-profiles-daemon
)

BROWSER_PACKAGES=(google-chrome-stable brave-browser firefox-dev)
IDE_PACKAGES=(code pycharm-community sublime-text android-studio)
DEV_TOOLS=(peek remmina filezilla dbeaver meld deluge keepassxc ferdium)

TO_INSTALL=("${COMMON_PACKAGES[@]}")

if $INSTALL_ALL || $CATEGORY_BROWSERS; then TO_INSTALL+=("${BROWSER_PACKAGES[@]}"); fi
if $INSTALL_ALL || $CATEGORY_IDES; then TO_INSTALL+=("${IDE_PACKAGES[@]}"); fi
if $INSTALL_ALL || $CATEGORY_TOOLS; then TO_INSTALL+=("${DEV_TOOLS[@]}"); fi

execute_command "sudo zypper --non-interactive install ${TO_INSTALL[*]}" "Installing software packages"

# === Composer Setup ===
log "Installing Composer..."
execute_command "php -r \"copy('https://getcomposer.org/installer', 'composer-setup.php');\"" "Download Composer installer"
execute_command "php composer-setup.php" "Install Composer"
execute_command "sudo mv composer.phar /usr/local/bin/composer" "Move Composer globally"
rm composer-setup.php

# === Powerline Fonts ===
log "Installing Powerline Fonts..."
git clone https://github.com/powerline/fonts.git --depth=1
(cd fonts && ./install.sh)
rm -rf fonts

# === Valet Setup ===
log "Installing Valet for Linux..."
export PATH="$HOME/.composer/vendor/bin:$PATH"
composer global require cpriego/valet-linux
valet install

# === Start Services ===
log "Enabling services..."
sudo systemctl enable --now mariadb php-fpm nginx

# === Secure MariaDB ===
log "Securing MariaDB (automated attempt)..."
sudo mysql -e "UPDATE mysql.user SET Password=PASSWORD('root') WHERE User='root';"
sudo mysql -e "DELETE FROM mysql.user WHERE User='';"
sudo mysql -e "DROP DATABASE IF EXISTS test;"
sudo mysql -e "FLUSH PRIVILEGES;"
ok "MariaDB secured."

# === Done ===
ok "Setup complete! 🎉"
