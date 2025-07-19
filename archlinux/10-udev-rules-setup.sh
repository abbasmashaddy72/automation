#!/bin/bash
set -euo pipefail

# === Logger ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "🔧 Setting up udev rules for iPhone and Android devices"

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

# === Write udev Rules ===
log "📄 Writing udev rules to /etc/udev/rules.d/..."
echo "$iphone_rule"  | sudo tee /etc/udev/rules.d/99-iphone.rules >/dev/null || fail "Failed to write iPhone rule"
echo "$android_rule" | sudo tee /etc/udev/rules.d/99-android.rules >/dev/null || fail "Failed to write Android rule"

# === Permissions ===
log "🔐 Setting read permissions..."
sudo chmod a+r /etc/udev/rules.d/99-iphone.rules /etc/udev/rules.d/99-android.rules || fail "Could not set permissions"
ok "Permissions set"

# === Reload and Restart ===
log "🔄 Reloading udev rules..."
sudo udevadm control --reload-rules || fail "Failed to reload udev rules"

log "🔁 Restarting usbmuxd service..."
sudo systemctl restart usbmuxd || warn "usbmuxd restart failed — not always critical"

ok "🎉 udev rules applied successfully for iPhone and Android"
