#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 08-usb-udev-rules-setup.sh
#   - Safe, idempotent setup for Android/iPhone udev rules
#   - Supports manual and --auto unattended mode
#   - Automatic backup and logging for max confidence
##############################################################################

### ─── Logger & Platform Detection ─────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/../lib/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
source "$SCRIPT_DIR/../lib/lib-logger.sh"
if [[ ! -f "$SCRIPT_DIR/../lib/lib-platform.sh" ]]; then
    fail "Platform library not found! Exiting."
fi
source "$SCRIPT_DIR/../lib/lib-platform.sh"

ensure_supported_platform arch cachyos manjaro
section "🔧 udev Rules Setup for iPhone & Android (Arch-based)"

### ─── Config and Defaults ────────────────────────────────────────────────

UDEV_DIR="/etc/udev/rules.d"
IPHONE_RULE="$UDEV_DIR/99-iphone.rules"
ANDROID_RULE="$UDEV_DIR/99-android.rules"

# Vendor/Product defaults (easy to adjust)
IPHONE_DEFAULT_VENDOR="05ac"
IPHONE_DEFAULT_PRODUCT="*"
ANDROID_DEFAULT_VENDOR="1004"
ANDROID_DEFAULT_PRODUCT="633e"

# Flags and input
AUTO_MODE=false
for arg in "$@"; do
    case "$arg" in
        --auto) AUTO_MODE=true ;;
    esac
done

if [[ "$AUTO_MODE" == false ]]; then
    read -rp "Enter iPhone idVendor [default: $IPHONE_DEFAULT_VENDOR]: " iphone_vendor
    read -rp "Enter iPhone idProduct [default: $IPHONE_DEFAULT_PRODUCT]: " iphone_product
    read -rp "Enter Android idVendor [default: $ANDROID_DEFAULT_VENDOR]: " android_vendor
    read -rp "Enter Android idProduct [default: $ANDROID_DEFAULT_PRODUCT]: " android_product
else
    iphone_vendor="$IPHONE_DEFAULT_VENDOR"
    iphone_product="$IPHONE_DEFAULT_PRODUCT"
    android_vendor="$ANDROID_DEFAULT_VENDOR"
    android_product="$ANDROID_DEFAULT_PRODUCT"
    log "⚙️  Auto mode: using default USB IDs"
fi

iphone_vendor="${iphone_vendor:-$IPHONE_DEFAULT_VENDOR}"
iphone_product="${iphone_product:-$IPHONE_DEFAULT_PRODUCT}"
android_vendor="${android_vendor:-$ANDROID_DEFAULT_VENDOR}"
android_product="${android_product:-$ANDROID_DEFAULT_PRODUCT}"

### ─── udev Rules Content ────────────────────────────────────────────────

iphone_rule='ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="'"$iphone_vendor"'", ATTR{idProduct}=="'"$iphone_product"'", ENV{ID_MM_DEVICE_IGNORE}="1"'
android_rule='ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="'"$android_vendor"'", ATTR{idProduct}=="'"$android_product"'", ENV{ID_MM_DEVICE_IGNORE}="1", ENV{UDISKS_IGNORE}="1", ENV{MTP_IGNORE}="1", ENV{GVFS_IGNORE}="1", ENV{ID_GPHOTO2_IGNORE}="1"'

### ─── Backup & Overwrite Logic ──────────────────────────────────────────

backup_and_check() {
    local rule_file="$1"
    local vendor="$2"
    if [[ -f "$rule_file" ]]; then
        local backup="${rule_file}.bak.$(date +%Y%m%d%H%M%S)"
        sudo cp "$rule_file" "$backup" && ok "Backed up $rule_file → $backup"
        if grep -q "$vendor" "$rule_file"; then
            warn "Rule for vendor ID ($vendor) already exists in $rule_file. Skipping overwrite."
            return 1
        else
            if [[ "$AUTO_MODE" == false ]]; then
                read -rp "Rule $rule_file exists. Overwrite? [y/N]: " confirm
                if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
                    warn "Skipped $rule_file"
                    return 1
                fi
            else
                warn "Overwriting $rule_file due to --auto mode"
            fi
        fi
    fi
    return 0
}

declare -a applied_rules=() skipped_rules=()

### ─── Apply iPhone Rule ─────────────────────────────────────────────────

if backup_and_check "$IPHONE_RULE" "$iphone_vendor"; then
    echo "$iphone_rule" | sudo tee "$IPHONE_RULE" >/dev/null || fail "Failed to write iPhone rule"
    sudo chmod a+r "$IPHONE_RULE"
    applied_rules+=("iPhone")
else
    skipped_rules+=("iPhone")
fi

### ─── Apply Android Rule ────────────────────────────────────────────────

if backup_and_check "$ANDROID_RULE" "$android_vendor"; then
    echo "$android_rule" | sudo tee "$ANDROID_RULE" >/dev/null || fail "Failed to write Android rule"
    sudo chmod a+r "$ANDROID_RULE"
    applied_rules+=("Android")
else
    skipped_rules+=("Android")
fi

### ─── Reload udev and usbmuxd ───────────────────────────────────────────

log "🔄 Reloading udev rules..."
sudo udevadm control --reload-rules || fail "Failed to reload udev rules"

log "🔁 Restarting usbmuxd service (for iOS devices)..."
sudo systemctl restart usbmuxd || warn "usbmuxd restart failed — not always critical"

### ─── Final Summary ─────────────────────────────────────────────────────

section "✅ udev Rules Setup Summary"
[[ ${#applied_rules[@]} -gt 0 ]] && ok "🟢 Applied rules: ${applied_rules[*]}"
[[ ${#skipped_rules[@]} -gt 0 ]] && warn "🟡 Skipped rules: ${skipped_rules[*]}"

ok "🎉 udev rules applied (or skipped) for iPhone and Android devices."

# End of script. Welcome to plug-and-play Nirvana.
