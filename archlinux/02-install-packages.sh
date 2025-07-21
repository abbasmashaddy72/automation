#!/bin/bash

# === Configurable Debug and Verbosity ===
DEBUG="${DEBUG:-0}"
SILENT="${SILENT:-0}"

# === Optional Debug Mode (prints every command) ===
[[ "$DEBUG" == "1" ]] && set -x

# === Safe Bash Settings ===
set -euo pipefail

# === Trap to Show Last Failing Command (for diagnostics) ===
trap 'echo -e "\n❌ Script failed at line $LINENO while running: $BASH_COMMAND (exit code: $?)" >&2' ERR

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

# === Interactive Sudo Prompt ===
echo "🔐 Please enter your sudo password to begin..."
if ! sudo -v; then
    echo "❌ Failed to authenticate sudo." >&2
    exit 1
fi

# === Arrays for tracking ===
declare -a installed_packages already_present failed_packages

# === Install Helpers ===
is_installed_pacman() { pacman -Qi "$1" &>/dev/null; }
is_installed_pamac() {
    local pkg="$1"
    pacman -Q "$pkg" &>/dev/null
}

install_with_pacman() {
    local pkg="$1"
    echo "📦 Installing $pkg via pacman..."
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
    echo "📦 Installing $pkg via pamac..."

    pamac install --no-confirm "$pkg" >/dev/null 2>&1

    if pacman -Q "$pkg" &>/dev/null; then
        installed_packages+=("$pkg")
        ok "$pkg installed (verified via pacman)"
    else
        failed_packages+=("$pkg")
        warn "❌ $pkg failed to install via pamac (not found via pacman)"
    fi
}

install_package() {
    local package="$1"
    local manager="$2"

    if [[ "$manager" == "pacman" ]]; then
        if is_installed_pacman "$package"; then
            already_present+=("$package")
            if [[ "${DEBUG:-}" == "1" ]]; then
                ok "$package already installed (pacman)"
            fi
        else
            install_with_pacman "$package"
        fi
    elif [[ "$manager" == "pamac" ]]; then
        if is_installed_pamac "$package"; then
            already_present+=("$package")
            if [[ "${DEBUG:-}" == "1" ]]; then
                ok "$package already installed (pamac)"
            fi
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

if (( ${#installed_packages[@]:-0} > 0 )); then
    log "🟢 Newly installed: ${installed_packages[*]}"
fi

if (( ${#already_present[@]:-0} > 0 )); then
    log "🟡 Already present: ${already_present[*]}"
fi

if (( ${#failed_packages[@]:-0} > 0 )); then
    warn "🔴 Failed to install: ${failed_packages[*]}"
fi

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