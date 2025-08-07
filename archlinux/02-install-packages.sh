#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 02-install-packages.sh
#   - One unified, self-documenting installer for all your dev tools and basics
#   - Works on ANY Arch-based distro (Arch, Manjaro, Garuda, CachyOS, AxOS, etc)
#   - Handles all dependencies non-interactively; picks best AUR helper
#   - Maintains clear logs, handles idempotency, and is ultra-maintainable
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

if [[ ! -f "$LIBDIR/lib-aur-helper.sh" ]]; then
    fail "AUR helper library not found! Exiting."
fi
source "$LIBDIR/lib-aur-helper.sh"

ensure_supported_platform arch cachyos

section "📦 Universal Package Installation for $PLATFORM_STRING"

### ─── Sudo Password Prompt Upfront ────────────────────────────────────────

echo "🔐 Please enter your sudo password to begin..."
if ! sudo -v; then
    fail "❌ Failed to authenticate sudo."
fi

### ─── Detect and/or Install AUR Helper ────────────────────────────────────

AUR_HELPER="$(detect_aur_helper)"
if [[ "$AUR_HELPER" == "none" ]]; then
    section "🔄 No AUR helper found! Installing yay for AUR support..."
    sudo pacman -S --needed --noconfirm yay || fail "Failed to install yay!"
    AUR_HELPER="yay"
fi
ok "AUR helper selected: $AUR_HELPER"

### ─── Unified Package List (Official and AUR) ─────────────────────────────

all_packages=(
    # --- Browsers ---
    brave-browser                       # Chromium-based alternative
    firefox                             # Mainstream open-source browser
    firefox-developer-edition           # Developer-focused browser
    google-chrome                       # Google Chrome

    # --- IDEs ---
    intellij-idea-community-edition     # Java IDE
    pycharm-community-edition           # Python IDE
    android-studio                      # Android development IDE
    visual-studio-code-bin              # Code editor

    # --- Database & Data Tools ---
    dbeaver                             # Database GUI
    postman-bin                         # API testing tool
    tiny-rdm-bin                        # Redis GUI

    # --- Office & Communication ---
    onlyoffice-desktopeditors           # Office suite
    thunderbird                         # Email client
    ferdium                             # Unified messenger

    # --- Security & Passwords ---
    keepassxc                           # Password manager

    # --- File/Sync/Remote Tools ---
    winscp                              # SFTP client
    remmina                             # RDP/VNC client
    freerdp                             # Remote desktop protocol
    anydesk-bin                         # Remote desktop

    # --- Utility Apps ---
    meld                                # Diff/merge tool
    peek                                # GIF screen recorder
    vlc                                 # Media player
    void-bin                            # AI terminal

    # --- Virtualization ---
    virtualbox                          # Hypervisor
    virtualbox-guest-iso                # Guest ISO support
    virtualbox-guest-utils              # Guest utils

    # --- Fonts ---
    ttf-jetbrains-mono                  # JetBrains Mono Font
    ttf-hack-nerd                       # Hack Nerd Font

    # --- System & CLI Tools ---
    base-devel                          # Essential dev tools
    curl                                # HTTP CLI tool
    tree                                # Directory tree viewer
    unzip                               # Archive extractor
    zip                                 # Archive compressor
    deluge-gtk                          # Torrent client
    ventoy                              # Bootable USB creator
    scrcpy                              # Android screen mirroring
    usbmuxd                             # iOS USB communication

    # --- Mobile / iOS Development ---
    android-tools                       # adb, fastboot
    gvfs-afc                            # iDevice mounter
    ifuse                               # FUSE for Apple devices
    libimobiledevice                    # iOS sync/access utility
)

### ─── Status Arrays ──────────────────────────────────────────────────────

declare -a installed_packages already_present failed_packages
installed_packages=()
already_present=()
failed_packages=()

### ─── Installer Functions ────────────────────────────────────────────────

is_installed() { pacman -Q "$1" &>/dev/null; }
is_pacman_available() { pacman -Si "$1" &>/dev/null; }

install_with_pacman() {
    local pkg="$1"
    log "📦 Installing $pkg via pacman..."
    if sudo pacman -S --needed --noconfirm "$pkg"; then
        installed_packages+=("$pkg")
        ok "$pkg installed (pacman)"
    else
        failed_packages+=("$pkg")
        warn "Failed to install $pkg via pacman"
    fi
}

install_with_aur() {
    local pkg="$1"
    log "📦 Installing $pkg via $AUR_HELPER..."
    if aur_install "$pkg"; then
        if pacman -Q "$pkg" &>/dev/null; then
            installed_packages+=("$pkg")
            ok "$pkg installed ($AUR_HELPER)"
        else
            failed_packages+=("$pkg")
            warn "❌ $pkg failed to install via $AUR_HELPER"
        fi
    else
        failed_packages+=("$pkg")
        warn "❌ $pkg failed to install via $AUR_HELPER"
    fi
}

### ─── Main Install Loop ──────────────────────────────────────────────────

section "🛠 Installing All Packages..."

for pkg in "${all_packages[@]}"; do
    if is_installed "$pkg"; then
        already_present+=("$pkg")
        ok "$pkg already installed"
    elif is_pacman_available "$pkg"; then
        install_with_pacman "$pkg"
    else
        install_with_aur "$pkg"
    fi
done

### ─── Installation Summary (Logs) ────────────────────────────────────────

section "📊 Installation Summary"
if (( ${#installed_packages[@]} > 0 )); then
    log "🟢 Newly installed: ${installed_packages[*]}"
fi
if (( ${#already_present[@]} > 0 )); then
    log "🟡 Already present: ${already_present[*]}"
fi
if (( ${#failed_packages[@]} > 0 )); then
    warn "🔴 Failed to install: ${failed_packages[*]}"
fi

### ─── Special Handling: VirtualBox Group Membership ──────────────────────

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

ok "🎉 All packages processed for $PLATFORM_STRING!"

# End of script. Go grab some coffee and let the automation work for you.
