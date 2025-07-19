#!/bin/bash
set -euo pipefail

# === Include Logger ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📦 Starting system package installation..."

# === Install Helpers ===
is_installed_pacman() { pacman -Qi "$1" &>/dev/null; }
is_installed_pamac() { pamac list --installed "$1" &>/dev/null; }

install_with_pacman() {
    log "🔹 Installing $1 (pacman)..."
    sudo pacman -S --needed --noconfirm "$1" && ok "$1 installed" || fail "Failed to install $1 via pacman"
}

install_with_pamac() {
    log "🔹 Installing $1 (pamac)..."
    pamac install --no-confirm "$1" && ok "$1 installed" || fail "Failed to install $1 via pamac"
}

install_package() {
    local package="$1"
    local manager="$2"

    if [[ "$manager" == "pacman" ]]; then
        is_installed_pacman "$package" && ok "$package already installed (pacman)" || install_with_pacman "$package"
    elif [[ "$manager" == "pamac" ]]; then
        is_installed_pamac "$package" && ok "$package already installed (pamac)" || install_with_pamac "$package"
    fi
}

# === Official Repository Packages ===

# --- Browsers ---
pacman_packages=(
    brave-browser                 # Browser: No Add browser
    firefox                       # Browser: Common browser
    firefox-developer-edition     # Browser: Developer-focused browser
)

# --- Development Tools & IDEs ---
pacman_packages+=(
    dbeaver                       # Dev Tool: Database GUI
    intellij-idea-community-edition # IDE: Java development
    keepassxc                     # Dev Tool: Password manager
    meld                          # Dev Tool: Diff/merge tool
    onlyoffice-desktopeditors     # Utility: Office suite
    peek                          # Dev Tool: GIF screen recorder
    pycharm-community-edition     # IDE: Python
    remmina                       # Dev Tool: RDP/VNC client
    thunderbird                   # Utility: Email client
    virtualbox                    # Virtualization
    virtualbox-guest-iso          # Virtualization
    virtualbox-guest-utils        # Virtualization
    vlc                           # Utility: Media player
)

# --- Utilities & CLI Tools ---
pacman_packages+=(
    curl                          # CLI: HTTP tool
    deluge-gtk                    # Utility: Torrent client
    freerdp                       # Utility: Remote desktop
    scrcpy                        # Utility: Android screen mirroring
    tree                          # CLI: Directory tree viewer
    unzip                         # CLI: Archive extractor
    usbmuxd                       # iOS: USB communication
    ventoy                        # Utility: Bootable USB creator
    zip                           # CLI: Archive compressor
)

# --- Mobile / iOS Development ---
pacman_packages+=(
    android-tools                 # Mobile: adb, fastboot
    gvfs-afc                      # iOS: iDevice mounter
    ifuse                         # iOS: FUSE for Apple devices
    libimobiledevice              # iOS: Sync/access utility
)

# === AUR / Pamac Packages ===

# --- AUR Applications ---
pamac_packages=(
    android-studio                # IDE: Android development
    anydesk-bin                   # Utility: Remote desktop
    ferdium                       # Utility: Unified messenger
    google-chrome                 # Browser: Google Chrome
    postman-bin                   # Dev Tool: API testing
    visual-studio-code-bin        # IDE: Code editor
    void-bin                      # Dev Tool: AI terminal
    winscp                        # Utility: SFTP client
)

# === Install Pacman Packages ===
section "📦 Installing official (pacman) packages..."
for package in "${pacman_packages[@]}"; do
    install_package "$package" "pacman"
done

# === Install AUR (Pamac) Packages ===
section "📦 Installing AUR (pamac) packages..."
if command -v pamac &>/dev/null; then
    for package in "${pamac_packages[@]}"; do
        install_package "$package" "pamac"
    done
else
    warn "⚠ pamac is not installed. Skipping AUR packages."
fi

ok "🎉 All system packages installed!"
