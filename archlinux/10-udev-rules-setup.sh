#!/bin/bash
set -euo pipefail

# === Platform Check ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

ensure_supported_platform arch manjaro

section "🔧 Setting up udev rules for iPhone and Android devices"

UDEV_DIR="/etc/udev/rules.d"
IPHONE_RULE="$UDEV_DIR/99-iphone.rules"
ANDROID_RULE="$UDEV_DIR/99-android.rules"

# === Flags ===
AUTO_MODE=false
for arg in "$@"; do
    case "$arg" in
        --auto) AUTO_MODE=true ;;
    esac
done

# === Prompt or Defaults ===
if [[ "$AUTO_MODE" == false ]]; then
    read -rp "Enter iPhone idVendor [default: 05ac]: " iphone_vendor
    read -rp "Enter iPhone idProduct [default: *]: " iphone_product
    read -rp "Enter Android idVendor [default: 1004]: " android_vendor
    read -rp "Enter Android idProduct [default: 633e]: " android_product
else
    iphone_vendor="05ac"
    iphone_product="*"
    android_vendor="1004"
    android_product="633e"
    log "⚙️  Auto mode: using default USB IDs"
fi

# === Fallback Defaults ===
iphone_vendor="${iphone_vendor:-05ac}"
iphone_product="${iphone_product:-*}"
android_vendor="${android_vendor:-1004}"
android_product="${android_product:-633e}"

# === Rules Content ===
iphone_rule="ACTION==\"add|change\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$iphone_vendor\", ATTR{idProduct}==\"$iphone_product\", ENV{ID_MM_DEVICE_IGNORE}=\"1\""
android_rule="ACTION==\"add|change\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$android_vendor\", ATTR{idProduct}==\"$android_product\", ENV{ID_MM_DEVICE_IGNORE}=\"1\", ENV{UDISKS_IGNORE}=\"1\", ENV{MTP_IGNORE}=\"1\", ENV{GVFS_IGNORE}=\"1\", ENV{ID_GPHOTO2_IGNORE}=\"1\""

# === Backup & Check for Existing Rules ===
backup_and_check() {
    local rule_file="$1"
    if [[ -f "$rule_file" ]]; then
        local backup="${rule_file}.bak.$(date +%Y%m%d%H%M%S)"
        sudo cp "$rule_file" "$backup" && ok "Backed up $rule_file to $backup"
        if grep -q "$iphone_vendor" "$rule_file" || grep -q "$android_vendor" "$rule_file"; then
            warn "Rule for vendor/product ID already exists in $rule_file. Skipping overwrite."
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

declare -a applied_rules skipped_rules

# === Apply iPhone Rule ===
if backup_and_check "$IPHONE_RULE"; then
    echo "$iphone_rule" | sudo tee "$IPHONE_RULE" >/dev/null || fail "Failed to write iPhone rule"
    sudo chmod a+r "$IPHONE_RULE"
    applied_rules+=("iPhone")
else
    skipped_rules+=("iPhone")
fi

# === Apply Android Rule ===
if backup_and_check "$ANDROID_RULE"; then
    echo "$android_rule" | sudo tee "$ANDROID_RULE" >/dev/null || fail "Failed to write Android rule"
    sudo chmod a+r "$ANDROID_RULE"
    applied_rules+=("Android")
else
    skipped_rules+=("Android")
fi

# === Reload and Restart ===
log "🔄 Reloading udev rules..."
sudo udevadm control --reload-rules || fail "Failed to reload udev rules"

log "🔁 Restarting usbmuxd service..."
sudo systemctl restart usbmuxd || warn "usbmuxd restart failed — not always critical"

section "✅ udev Rules Setup Summary"
[[ ${#applied_rules[@]} -gt 0 ]] && ok "🟢 Applied rules: ${applied_rules[*]}"
[[ ${#skipped_rules[@]} -gt 0 ]] && warn "🟡 Skipped rules: ${skipped_rules[*]}"

ok "🎉 udev rules applied (or skipped) for iPhone and Android devices"
