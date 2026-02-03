#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 02-install-packages.sh
#
# Purpose
# -------
# One unified, self-documenting installer for dev tools + daily apps on
# Arch-based distros (Arch/Manjaro/Garuda/CachyOS/EndeavourOS/etc).
#
# What it does
# ------------
# - Prompts sudo once (then uses sudo only when needed)
# - Detects an AUR helper (via lib-aur-helper.sh). If none:
#     * tries to install yay from repos (if available), else
#     * bootstraps yay from AUR safely (git + base-devel first)
# - Installs packages idempotently:
#     * If already installed -> skip
#     * If in official repos -> pacman
#     * Else -> AUR helper
# - Tracks what THIS script installed so --uninstall can remove safely
# - Optionally adds user to vboxusers if VirtualBox installed
#
# Safety / Reliability
# --------------------
# - Skips cleanly if something is missing
# - Stores state under /var/lib/arch-dev-setup/02-install-packages/
# - --uninstall removes only packages this script added (from state file)
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
# - ../lib/lib-aur-helper.sh
#
# Usage
# -----
#   ./02-install-packages.sh
#   ./02-install-packages.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so failures are diagnosable instead of “it broke”)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
    echo "❌ Error on line $1 while running: $2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Library checks and bootstrap
### ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
    echo "Logger library not found at: $LIBDIR/lib-logger.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
    echo "Platform library not found at: $LIBDIR/lib-platform.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-platform.sh"

if [[ ! -f "$LIBDIR/lib-aur-helper.sh" ]]; then
    echo "AUR helper library not found at: $LIBDIR/lib-aur-helper.sh" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-aur-helper.sh"

# Keep this broad: most Arch-based distros should pass if your lib supports them.
ensure_supported_platform arch cachyos manjaro garuda endeavouros

section "📦 Universal Package Installation for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (for uninstall + tracking)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL="y" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0              Install packages
  $0 --uninstall  Remove packages installed by this script

State directory:
  /var/lib/arch-dev-setup/02-install-packages/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/02-install-packages"
STATE_PKGS="$STATE_DIR/installed-packages.txt"
STATE_VBOX="$STATE_DIR/added-vboxusers.flag"

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
echo "🔐 Please enter your sudo password to begin..."
if ! sudo -v; then
    fail "❌ Failed to authenticate sudo."
fi
sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Small helpers
### ─────────────────────────────────────────────────────────────────────────
prompt_yn() {
    # Usage: prompt_yn "Question?" "y|n"
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply
    
    while true; do
        if [[ "$default" == "y" ]]; then
            read -r -p "$prompt [Y/n]: " reply
            reply="${reply:-y}"
        else
            read -r -p "$prompt [y/N]: " reply
            reply="${reply:-n}"
        fi
        
        case "${reply,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

is_installed() { pacman -Q "$1" &>/dev/null; }
is_pacman_available() { pacman -Si "$1" &>/dev/null; }

record_installed_pkgs() {
    # Record only packages that were NOT installed before this script ran.
    # This makes uninstall safe: we remove only what this script added.
    local pkgs=("$@")
    local p
    for p in "${pkgs[@]}"; do
        if ! is_installed "$p"; then
            echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
        fi
    done
}

### ─────────────────────────────────────────────────────────────────────────
### AUR helper bootstrap (robust + non-interactive)
### ─────────────────────────────────────────────────────────────────────────
bootstrap_yay_from_aur() {
    # Builds yay from AUR if not available in repos.
    # Needs: git, base-devel
    section "🧰 Bootstrapping yay from AUR (no helper found)"
    
    # Ensure prerequisites
    if ! is_installed base-devel; then
        log "Installing base-devel (required to build AUR packages)..."
        record_installed_pkgs base-devel
        sudo pacman -S --needed --noconfirm base-devel || fail "Failed to install base-devel"
    fi
    
    if ! command -v git &>/dev/null; then
        log "Installing git (required to clone AUR repos)..."
        record_installed_pkgs git
        sudo pacman -S --needed --noconfirm git || fail "Failed to install git"
    fi
    
    # Build in a temp dir as the current user (best practice)
    local tmpdir
    tmpdir="$(mktemp -d)"
    log "Cloning yay into: $tmpdir"
    
    (
        cd "$tmpdir"
        git clone https://aur.archlinux.org/yay.git
        cd yay
        # makepkg should not run as root; it will prompt for sudo when installing
        makepkg -si --noconfirm
    ) || fail "Failed to build/install yay from AUR"
    
    rm -rf "$tmpdir" || true
    ok "yay installed via AUR bootstrap."
}

ensure_aur_helper() {
    # Uses lib-aur-helper.sh to detect, else installs yay.
    AUR_HELPER="$(detect_aur_helper)"
    
    if [[ "$AUR_HELPER" != "none" ]]; then
        ok "AUR helper selected: $AUR_HELPER"
        return 0
    fi
    
    section "🔄 No AUR helper found"
    
    # First choice: install yay from official repos if present on this distro
    if is_pacman_available yay; then
        log "Installing yay from repos..."
        record_installed_pkgs yay
        sudo pacman -S --needed --noconfirm yay || fail "Failed to install yay from repos"
        AUR_HELPER="yay"
        ok "AUR helper installed: $AUR_HELPER"
        return 0
    fi
    
    # Fallback: bootstrap from AUR
    bootstrap_yay_from_aur
    AUR_HELPER="yay"
    
    # Sanity check
    if [[ "$(detect_aur_helper)" == "none" ]]; then
        fail "AUR helper installation appears to have failed (still none detected)."
    fi
    
    ok "AUR helper installed: $AUR_HELPER"
}

### ─────────────────────────────────────────────────────────────────────────
### Installer functions
### ─────────────────────────────────────────────────────────────────────────
install_with_pacman() {
    local pkg="$1"
    log "📦 Installing $pkg via pacman..."
    if sudo pacman -S --needed --noconfirm "$pkg"; then
        ok "$pkg installed (pacman)"
        return 0
    fi
    warn "Failed to install $pkg via pacman"
    return 1
}

install_with_aur() {
    local pkg="$1"
    log "📦 Installing $pkg via $AUR_HELPER..."
    if aur_install "$pkg"; then
        if pacman -Q "$pkg" &>/dev/null; then
            ok "$pkg installed ($AUR_HELPER)"
            return 0
        fi
    fi
    warn "❌ $pkg failed to install via $AUR_HELPER"
    return 1
}

### ─────────────────────────────────────────────────────────────────────────
### Package list (Official + AUR mixed)
### ─────────────────────────────────────────────────────────────────────────
all_packages=(
    # --- Browsers ---
    brave-browser
    firefox
    firefox-developer-edition
    google-chrome
    torbrowser-launcher
    
    # --- IDEs ---
    intellij-idea-community-edition
    pycharm-community-edition
    android-studio
    visual-studio-code-bin
    void-bin
    
    # --- Database & Data Tools ---
    dbeaver
    postman-bin
    tiny-rdm-bin
    
    # --- Office & Communication ---
    onlyoffice-bin
    thunderbird
    ferdium
    
    # --- Security & Passwords ---
    keepassxc
    
    # --- File/Sync/Remote Tools ---
    winscp
    remmina
    freerdp
    anydesk-bin
    
    # --- Utility Apps ---
    meld
    peek
    vlc
    freetube
    
    # --- Virtualization ---
    virtualbox
    virtualbox-guest-iso
    virtualbox-guest-utils
    
    # --- Fonts ---
    ttf-jetbrains-mono
    ttf-hack-nerd
    
    # --- System & CLI Tools ---
    base-devel
    curl
    tree
    unzip
    zip
    deluge-gtk
    ventoy
    scrcpy
    usbmuxd
    
    # --- Mobile / iOS Development ---
    android-tools
    gvfs-afc
    ifuse
    libimobiledevice
)

### ─────────────────────────────────────────────────────────────────────────
### Status arrays (for summary reporting)
### ─────────────────────────────────────────────────────────────────────────
declare -a installed_packages already_present failed_packages
installed_packages=()
already_present=()
failed_packages=()

### ─────────────────────────────────────────────────────────────────────────
### Uninstall mode
### ─────────────────────────────────────────────────────────────────────────
uninstall_remove_recorded_packages() {
    if [[ ! -f "$STATE_PKGS" ]]; then
        warn "No recorded package list found at $STATE_PKGS. Nothing to uninstall."
        return 0
    fi
    
    mapfile -t pkgs < <(sudo sort -u "$STATE_PKGS" | sed '/^\s*$/d' || true)
    
    if [[ ${#pkgs[@]} -eq 0 ]]; then
        warn "Recorded package list is empty. Nothing to uninstall."
        return 0
    fi
    
    section "🧯 Uninstall: packages installed by this script"
    printf '  - %s\n' "${pkgs[@]}"
    
    if prompt_yn "Remove these packages now? (safe: only ones this script added)" "n"; then
        local to_remove=()
        local p
        for p in "${pkgs[@]}"; do
            if is_installed "$p"; then
                to_remove+=("$p")
            fi
        done
        
        if [[ ${#to_remove[@]} -gt 0 ]]; then
            sudo pacman -Rns --noconfirm "${to_remove[@]}" || warn "Some removals failed (deps in use or required)."
            ok "Package removal step complete."
        else
            ok "None of the recorded packages are currently installed. Nothing to remove."
        fi
    else
        log "Skipping package removal."
    fi
}

uninstall_vboxusers_if_added() {
    if [[ ! -f "$STATE_VBOX" ]]; then
        return 0
    fi
    
    section "🧯 Uninstall: vboxusers group membership"
    if prompt_yn "This script previously added you to vboxusers. Remove you from vboxusers now?" "n"; then
        # gpasswd -d returns non-zero if user not in group, so we soften it.
        sudo gpasswd -d "$USER" vboxusers 2>/dev/null || warn "Could not remove $USER from vboxusers (maybe already removed)."
        sudo rm -f "$STATE_VBOX" || true
        ok "vboxusers membership removal attempted."
    else
        warn "Leaving vboxusers membership unchanged."
    fi
}

run_uninstall() {
    section "🧯 Running uninstall rollback"
    uninstall_vboxusers_if_added
    uninstall_remove_recorded_packages
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Main install flow
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

ensure_aur_helper

section "🛠 Installing all packages..."

for pkg in "${all_packages[@]}"; do
    if is_installed "$pkg"; then
        already_present+=("$pkg")
        ok "$pkg already installed"
        continue
    fi
    
    # Track it as "installed by this script" BEFORE installing,
    # so --uninstall can remove it later safely.
    record_installed_pkgs "$pkg"
    
    if is_pacman_available "$pkg"; then
        if install_with_pacman "$pkg"; then
            installed_packages+=("$pkg")
        else
            failed_packages+=("$pkg")
        fi
    else
        if install_with_aur "$pkg"; then
            installed_packages+=("$pkg")
        else
            failed_packages+=("$pkg")
        fi
    fi
done

### ─────────────────────────────────────────────────────────────────────────
### Summary
### ─────────────────────────────────────────────────────────────────────────
section "📊 Installation Summary"
if (( ${#installed_packages[@]} > 0 )); then
    log "🟢 Newly installed: ${installed_packages[*]}"
fi
if (( ${#already_present[@]} > 0 )); then
    log "🟡 Already present: ${already_present[*]}"
fi
if (( ${#failed_packages[@]} > 0 )); then
    warn "🔴 Failed to install: ${failed_packages[*]}"
    warn "Tip: Some names may differ per distro or may have moved repos/AUR."
fi

### ─────────────────────────────────────────────────────────────────────────
### Special handling: VirtualBox group membership
### ─────────────────────────────────────────────────────────────────────────
if is_installed virtualbox || is_installed virtualbox-guest-utils || is_installed virtualbox-guest-iso; then
    if ! groups "$USER" | grep -qw vboxusers; then
        sudo usermod -aG vboxusers "$USER"
        echo "added" | sudo tee "$STATE_VBOX" >/dev/null
        warn "Added $USER to vboxusers group (VirtualBox USB support)."
        warn "You MUST log out and log back in for this to take effect."
    else
        ok "$USER is already in the vboxusers group."
    fi
fi

ok "🎉 All packages processed for $PLATFORM_STRING!"
