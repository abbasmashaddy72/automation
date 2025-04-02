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
    dbeaver
    deluge-gtk
    firefox-developer-edition
    firefox
    handbrake
    keepassxc
    libreoffice-fresh
    meld
    virtualbox
    pycharm-community-edition
    scrcpy
    remmina
    vlc
    timeshift
    android-tools
    mariadb
    tree
    zip
    unzip
    brave-browser
    ventoy
    curl
    cpu-checker
    kvm-ok
    linux-headers
    virtualbox-guest-utils
    libimobiledevice
    ifuse
    usbmuxd
    gvfs-afc
)

pamac_packages=(
    android-studio
    anydesk
    docker-desktop
    ferdium-bin
    google-chrome
    visual-studio-code-bin
    winscp
    balena-etcher
    sublime-text-4
    woeusb
)

# === Zed.dev Installer ===
install_zed() {
    if ! command -v zed &>/dev/null; then
        log "🧪 Installing Zed.dev..."
        curl -fsSL https://zed.dev/install.sh | sh || log_error "Zed.dev installation failed"
        log "✅ Zed.dev installed successfully"
    else
        log "✅ Zed.dev already installed"
    fi
}

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

# === Zed.dev ===
install_zed

log "🎉 Package installation complete!"
