#!/bin/bash

set -e

# === CONFIG ===
LOGDIR="$HOME/logs"
LOGFILE="$LOGDIR/udev_rules_setup.log"
AUTO_MODE=false

mkdir -p "$LOGDIR"
touch "$LOGFILE"

# === COLORS ===
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}➤ $1${NC}" | tee -a "$LOGFILE"; }
ok() { echo -e "${GREEN}✔ $1${NC}" | tee -a "$LOGFILE"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}" | tee -a "$LOGFILE"; }
fail() {
    echo -e "${RED}✖ $1${NC}" | tee -a "$LOGFILE"
    exit 1
}

# === Flags ===
for arg in "$@"; do
    case $arg in
    --auto) AUTO_MODE=true ;;
    esac
done

log "🔧 Starting udev rules setup for iPhone and Android devices"

# === Prompt or Auto ===
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
fi

iphone_vendor="${iphone_vendor:-05ac}"
iphone_product="${iphone_product:-*}"
android_vendor="${android_vendor:-1004}"
android_product="${android_product:-633e}"

# === Rule Content ===
iphone_rule="ACTION==\"add|change\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$iphone_vendor\", ATTR{idProduct}==\"$iphone_product\", ENV{ID_MM_DEVICE_IGNORE}=\"1\""
android_rule="ACTION==\"add|change\", SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$android_vendor\", ATTR{idProduct}==\"$android_product\", ENV{ID_MM_DEVICE_IGNORE}=\"1\", ENV{UDISKS_IGNORE}=\"1\", ENV{MTP_IGNORE}=\"1\", ENV{GVFS_IGNORE}=\"1\", ENV{ID_GPHOTO2_IGNORE}=\"1\""

# === Write Rules ===
log "📦 Writing udev rules..."

echo "$iphone_rule" | sudo tee /etc/udev/rules.d/99-iphone.rules >/dev/null || fail "Failed to write iPhone rule"
echo "$android_rule" | sudo tee /etc/udev/rules.d/99-android.rules >/dev/null || fail "Failed to write Android rule"

# === Set Permissions ===
sudo chmod a+r /etc/udev/rules.d/99-iphone.rules /etc/udev/rules.d/99-android.rules || fail "Failed to set rule permissions"
ok "Permissions set"

# === Reload & Restart Services ===
log "🔄 Reloading udev rules..."
sudo udevadm control --reload-rules || fail "Failed to reload udev rules"

log "🔄 Restarting usbmuxd..."
sudo systemctl restart usbmuxd || fail "Failed to restart usbmuxd"

ok "iPhone and Android udev rules created and applied successfully!"
