#!/bin/bash

set -euo pipefail

# === Setup ===
LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/install_packages.log"
mkdir -p "$LOGDIR"

timestamp() { date '+%F %T'; }
log() { echo "$(timestamp) | $*" | tee -a "$LOGFILE"; }
log_error() {
    echo "$(timestamp) | ❌ ERROR: $*" | tee -a "$LOGFILE"
    exit 1
}

log "📦 Starting package installation..."

# === Install Helpers ===
is_installed_pacman() {
    pacman -Qi "$1" &>/dev/null
}

is_installed_pamac() {
    pamac list --installed "$1" &>/dev/null
}

install_with_pacman() {
    log "🔹 Installing $1 with pacman..."
    sudo pacman -S --needed --noconfirm "$1" || log_error "Failed to install $1 via pacman"
}

install_with_pamac() {
    log "🔹 Installing $1 with pamac..."
    pamac install --no-confirm "$1" || log_error "Failed to install $1 via pamac"
}

install_package() {
    local package=$1
    local manager=$2

    if [[ "$manager" == "pacman" ]]; then
        if is_installed_pacman "$package"; then
            log "✅ $package already installed (pacman)."
        else
            install_with_pacman "$package"
        fi
    elif [[ "$manager" == "pamac" ]]; then
        if is_installed_pamac "$package"; then
            log "✅ $package already installed (pamac)."
        else
            install_with_pamac "$package"
        fi
    fi
}

# === Package Lists ===

pacman_packages=(
    android-tools
    brave-browser
    curl
    dbeaver
    deluge-gtk
    firefox
    firefox-developer-edition
    freerdp
    gvfs-afc
    ifuse
    intellij-idea-community-edition
    keepassxc
    libimobiledevice
    meld
    onlyoffice-desktopeditors
    peek
    pycharm-community-edition
    remmina
    scrcpy
    thunderbird
    tree
    unzip
    usbmuxd
    ventoy
    virtualbox
    virtualbox-guest-iso
    virtualbox-guest-utils
    vlc
    zip
)

pamac_packages=(
    android-studio
    anydesk-bin
    ferdium
    google-chrome
    postman-bin
    visual-studio-code-bin
    void-bin
    winscp
)

# === Install Packages ===

log "---------------------------------------------"
log "📦 Installing Pacman packages"
log "---------------------------------------------"
for package in "${pacman_packages[@]}"; do
    install_package "$package" "pacman"
done

log "---------------------------------------------"
log "📦 Installing Pamac (AUR) packages"
log "---------------------------------------------"

if command -v pamac &>/dev/null; then
    for package in "${pamac_packages[@]}"; do
        install_package "$package" "pamac"
    done
else
    log_error "Pamac is not installed. Skipping AUR packages."
fi

log "🎉 Package installation complete!"
