#!/bin/bash

# === Include Logger & Platform Detection ===
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

section "📦 System package installation for $PLATFORM_STRING"
ensure_supported_platform arch manjaro

# === Temporary NOPASSWD sudo ===
echo "🔐 Requesting temporary sudo elevation (NOPASSWD enabled for duration)..."
echo "%wheel ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/99-temp-nopasswd > /dev/null
trap 'echo "⚠️ Reverting temporary sudo rule..." && sudo rm -f /etc/sudoers.d/99-temp-nopasswd' EXIT

# === Keep sudo alive in the background ===
(sudo -v; while true; do sleep 60; sudo -nv; kill -0 "$$" || exit; done 2>/dev/null) &

# === Now safe to enable strict bash behavior ===
set -euo pipefail

# === Optional debug mode ===
if [[ "${DEBUG:-0}" == "1" ]]; then
    set -x
fi

# === Command-Line Flags ===
SILENT="${SILENT:-0}"
DEBUG="${DEBUG:-0}"

declare -a installed_packages already_present failed_packages

# === Install Helpers ===
is_installed_pacman() { pacman -Qi "$1" &>/dev/null; }
is_installed_pamac() { pamac list --installed "$1" &>/dev/null; }

install_with_pacman() {
    local pkg="$1"
    if sudo pacman -S --needed --noconfirm "$pkg"; then
        installed_packages+=("$pkg")
        ok "$pkg installed (pacman)"
    else
        failed_packages+=("$pkg")
        warn "Failed to install $pkg via pacman"
    fi
}

install_with_pamac() {
    local pkg="$1"
    if pamac install --no-confirm "$pkg"; then
        installed_packages+=("$pkg")
        ok "$pkg installed (pamac)"
    else
        failed_packages+=("$pkg")
        warn "Failed to install $pkg via pamac"
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
    else
        failed_packages+=("$package")
        warn "Unknown package manager: $manager for $package"
    fi
}

# === Official Repository Packages ===
pacman_packages=(
    # Browsers
    brave-browser                       # Browser: Chromium-based alternative
    firefox                             # Browser: Mainstream open-source browser
    firefox-developer-edition           # Browser: Developer-focused browser

    # IDEs and Dev Tools
    dbeaver                             # Dev Tool: Database GUI
    intellij-idea-community-edition     # IDE: Java development
    keepassxc                           # Dev Tool: Password manager
    meld                                # Dev Tool: Diff/merge tool
    onlyoffice-desktopeditors           # Utility: Office suite
    peek                                # Dev Tool: GIF screen recorder
    pycharm-community-edition           # IDE: Python
    remmina                             # Dev Tool: RDP/VNC client
    thunderbird                         # Utility: Email client
    virtualbox                          # Virtualization: Hypervisor
    virtualbox-guest-iso                # Virtualization: Guest ISO support
    virtualbox-guest-utils              # Virtualization: Guest utils
    vlc                                 # Utility: Media player

    # Utilities & CLI Tools
    curl                                # CLI: HTTP tool
    deluge-gtk                          # Utility: Torrent client
    freerdp                             # Utility: Remote desktop protocol
    scrcpy                              # Utility: Android screen mirroring
    tree                                # CLI: Directory tree viewer
    unzip                               # CLI: Archive extractor
    usbmuxd                             # iOS: USB communication
    ventoy                              # Utility: Bootable USB creator
    zip                                 # CLI: Archive compressor
    ttf-jetbrains-mono                  # Font: JetBrains Mono Font
    ttf-hack-nerd                       # Font: Hack Nerd Font
    base-devel                          # Base: Essential development tools

    # Mobile / iOS Development
    android-tools                       # Mobile: adb, fastboot
    gvfs-afc                            # iOS: iDevice mounter
    ifuse                               # iOS: FUSE for Apple devices
    libimobiledevice                    # iOS: Sync/access utility
)

# === AUR / Pamac Packages ===
pamac_packages=(
    android-studio                      # IDE: Android development
    anydesk-bin                         # Utility: Remote desktop
    ferdium                             # Utility: Unified messenger
    google-chrome                       # Browser: Google Chrome
    postman-bin                         # Dev Tool: API testing
    visual-studio-code-bin              # IDE: Code editor
    void-bin                            # Dev Tool: AI terminal
    winscp                              # Utility: SFTP client
    tiny-rdm-bin                        # Utility: Redis GUI
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
            failed_packages+=("$pkg")
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

# === VirtualBox group handling ===
if [[ " ${installed_packages[*]} " == *" virtualbox "* ]] || \
   [[ " ${installed_packages[*]} " == *" virtualbox-guest-utils "* ]] || \
   [[ " ${installed_packages[*]} " == *" virtualbox-guest-iso "* ]]; then

    if ! groups "$USER" | grep -qw vboxusers; then
        sudo usermod -aG vboxusers "$USER"
        warn "Added $USER to vboxusers group for VirtualBox USB support."
        warn "You MUST log out and log in for this to take effect."
    else
        ok "$USER is already in the vboxusers group."
    fi
fi

ok "🎉 All requested system packages processed for $PLATFORM_STRING!"