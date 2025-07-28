#!/usr/bin/env bash
# === lib-aur-helper.sh: Abstracts all AUR helpers (pamac, paru, yay) ===

# Detects and sets $AUR_HELPER global variable.
detect_aur_helper() {
    if command -v pamac &>/dev/null; then
        echo "pamac"
    elif command -v paru &>/dev/null; then
        echo "paru"
    elif command -v yay &>/dev/null; then
        echo "yay"
    else
        echo "none"
    fi
}

# Usage: aur_install <pkg>
# Auto-detects and uses correct install flags for each helper.
aur_install() {
    local pkg="$1"
    case "$AUR_HELPER" in
        pamac)
            pamac install --no-confirm --needed "$pkg"
            ;;
        paru|yay)
            "$AUR_HELPER" -S --noconfirm --needed "$pkg"
            ;;
        *)
            echo "❌ No supported AUR helper available." >&2
            return 1
            ;;
    esac
}

# Usage: aur_install_many <pkg1> <pkg2> ...
aur_install_many() {
    for pkg in "$@"; do
        aur_install "$pkg" || return 1
    done
}
