#!/bin/bash
set -euo pipefail

# === Include Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

section "📦 System package installation for $PLATFORM_STRING"

ensure_supported_platform arch manjaro

# === Command-Line Flags ===
SILENT="${SILENT:-0}"
DEBUG="${DEBUG:-0}"

# --- Track package install results ---
declare -a installed_packages already_present failed_packages

# === Install Helpers ===
is_installed_pacman() { pacman -Qi "$1" &>/dev/null; }
is_installed_pamac() { pamac list --installed "$1" &>/dev/null; }

install_with_pacman() {
    if sudo pacman -S --needed --noconfirm "$1"; then
        installed_packages+=("$1")
        ok "$1 installed (pacman)"
    else
        failed_packages+=("$1")
        warn "Failed to install $1 via pacman"
    fi
}

install_with_pamac() {
    if pamac install --no-confirm "$1"; then
        installed_packages+=("$1")
        ok "$1 installed (pamac)"
    else
        failed_packages+=("$1")
        warn "Failed to install $1 via pamac"
    fi
}

install_package() {
    local package="$1"
    local manager="$2"
    if [[ "$manager" == "pacman" ]]; then
        if is_installed_pacman "$package"; then
            already_present+=("$package")
            [[ "$DEBUG" == "1" ]] && ok "$package already installed (pacman)"
        else
            install_with_pacman "$package"
        fi
    elif [[ "$manager" == "pamac" ]]; then
        if is_installed_pamac "$package"; then
            already_present+=("$package")
            [[ "$DEBUG" == "1" ]] && ok "$package already installed (pamac)"
        else
            install_with_pamac "$package"
        fi
    fi
}

# === Official Repository Packages ===
pacman_packages=(
    # Browsers
    brave-browser                 # Browser: Chromium-based alternative
    firefox                       # Browser: Mainstream open-source browser
    firefox-developer-edition     # Browser: Developer-focused browser

    # IDEs and Dev Tools
    dbeaver                       # Dev Tool: Database GUI
    intellij-idea-community-edition # IDE: Java development
    keepassxc                     # Dev Tool: Password manager
    meld                          # Dev Tool: Diff/merge tool
    onlyoffice-desktopeditors     # Utility: Office suite
    peek                          # Dev Tool: GIF screen recorder
    pycharm-community-edition     # IDE: Python
    remmina                       # Dev Tool: RDP/VNC client
    thunderbird                   # Utility: Email client
    virtualbox                    # Virtualization: Hypervisor
    virtualbox-guest-iso          # Virtualization: Guest ISO support
    virtualbox-guest-utils        # Virtualization: Guest utils
    vlc                           # Utility: Media player

    # Utilities & CLI Tools
    curl                          # CLI: HTTP tool
    deluge-gtk                    # Utility: Torrent client
    freerdp                       # Utility: Remote desktop protocol
    scrcpy                        # Utility: Android screen mirroring
    tree                          # CLI: Directory tree viewer
    unzip                         # CLI: Archive extractor
    usbmuxd                       # iOS: USB communication
    ventoy                        # Utility: Bootable USB creator
    zip                           # CLI: Archive compressor

    # Mobile / iOS Development
    android-tools                 # Mobile: adb, fastboot
    gvfs-afc                      # iOS: iDevice mounter
    ifuse                         # iOS: FUSE for Apple devices
    libimobiledevice              # iOS: Sync/access utility
)

# === AUR / Pamac Packages ===
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

# === Package Parameterization ===
if [[ $# -gt 0 ]]; then
    # If args provided, install only those packages (find in either array)
    section "🎯 Installing requested packages: $*"
    targets=("$@")
    for pkg in "${targets[@]}"; do
        if [[ " ${pacman_packages[*]} " == *" $pkg "* ]]; then
            install_package "$pkg" "pacman"
        elif [[ " ${pamac_packages[*]} " == *" $pkg "* ]]; then
            install_package "$pkg" "pamac"
        else
            warn "Unknown package: $pkg"
        fi
    done
else
    # Default: install everything
    section "📦 Installing official (pacman) packages..."
    for package in "${pacman_packages[@]}"; do
        install_package "$package" "pacman"
    done

    section "📦 Installing AUR (pamac) packages..."
    if command -v pamac &>/dev/null; then
        for package in "${pamac_packages[@]}"; do
            install_package "$package" "pamac"
        done
    else
        warn "⚠ pamac is not installed. Skipping AUR packages."
    fi
fi

# === Final Summary ===
section "📊 Installation Summary"

[[ ${#installed_packages[@]} -gt 0 ]] && log "🟢 Newly installed: ${installed_packages[*]}"
[[ ${#already_present[@]} -gt 0 ]] && log "🟡 Already present: ${already_present[*]}"
[[ ${#failed_packages[@]} -gt 0 ]] && warn "🔴 Failed to install: ${failed_packages[*]}"

ok "🎉 All requested system packages processed for $PLATFORM_STRING!"

