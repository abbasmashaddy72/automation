#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 82-udev-rules-setup.sh
#
# Purpose
# -------
# Safe, idempotent setup for iPhone + Android udev rules on Arch-based distros.
# - Creates/updates udev rules files under /etc/udev/rules.d
# - Supports:
#     * interactive mode (default)
#     * --auto (unattended defaults)
#     * --uninstall (restore backups / remove created rules)
#
# Safety / Reliability
# --------------------
# - Sudo prompted once, early
# - Always backs up existing rule files before changing them
# - Idempotent: won't rewrite if the exact rule already exists
# - Never blindly overwrites in interactive mode (asks)
# - Records state under: /var/lib/arch-dev-setup/82-udev-rules-setup/
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./82-udev-rules-setup.sh
#   ./82-udev-rules-setup.sh --auto
#   ./82-udev-rules-setup.sh --iphone-vendor 05ac --iphone-product 12ab
#   ./82-udev-rules-setup.sh --android-vendor 18d1 --android-product 4ee7
#   ./82-udev-rules-setup.sh --uninstall
#
# Notes
# -----
# - Default iPhone vendor is Apple: 05ac
# - Android vendor/product defaults are examples; you should replace with YOUR device IDs
#   (use: lsusb)
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() { echo "❌ Error on line $1 while running: $2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Logger & platform detection
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

ensure_supported_platform arch cachyos manjaro garuda endeavouros
section "🔧 udev Rules Setup for iPhone & Android (Arch-based)"

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to continue..."
sudo -v || fail "❌ Failed to authenticate sudo."

### ─────────────────────────────────────────────────────────────────────────
### Config + defaults
### ─────────────────────────────────────────────────────────────────────────
UDEV_DIR="/etc/udev/rules.d"
IPHONE_RULE="$UDEV_DIR/99-iphone.rules"
ANDROID_RULE="$UDEV_DIR/99-android.rules"

# Vendor/Product defaults (easy to adjust)
IPHONE_DEFAULT_VENDOR="05ac"
IPHONE_DEFAULT_PRODUCT="*"     # any product for Apple devices
ANDROID_DEFAULT_VENDOR="1004"  # example
ANDROID_DEFAULT_PRODUCT="633e" # example

# State dir for uninstall tracking
STATE_DIR="/var/lib/arch-dev-setup/82-udev-rules-setup"
STATE_FILES="$STATE_DIR/managed-files.txt"
sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true
sudo touch "$STATE_FILES" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Flags + arg parsing
### ─────────────────────────────────────────────────────────────────────────
AUTO_MODE="n"
DO_UNINSTALL="n"

iphone_vendor=""
iphone_product=""
android_vendor=""
android_product=""

for arg in "$@"; do
    case "$arg" in
        --auto) AUTO_MODE="y" ;;
        --uninstall) DO_UNINSTALL="y" ;;
        --iphone-vendor) : ;;
        --iphone-product) : ;;
        --android-vendor) : ;;
        --android-product) : ;;
        -h|--help)
      cat <<EOF
Usage:
  $0 [options]

Options:
  --auto                 Use defaults (unattended)
  --iphone-vendor HEX    e.g. 05ac
  --iphone-product HEX|* e.g. 12ab or *
  --android-vendor HEX   e.g. 18d1
  --android-product HEX  e.g. 4ee7
  --uninstall            Remove/restore files managed by this script

Tip:
  Get USB IDs via: lsusb
EOF
            exit 0
        ;;
    esac
done

# Parse positional values safely
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[$i]}" in
        --iphone-vendor)  iphone_vendor="${args[$((i+1))]:-}";;
        --iphone-product) iphone_product="${args[$((i+1))]:-}";;
        --android-vendor) android_vendor="${args[$((i+1))]:-}";;
        --android-product) android_product="${args[$((i+1))]:-}";;
    esac
done

### ─────────────────────────────────────────────────────────────────────────
### Helpers
### ─────────────────────────────────────────────────────────────────────────
prompt_yn() {
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply=""
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

record_managed_file() {
    local f="$1"
    if ! sudo grep -qxF "$f" "$STATE_FILES" 2>/dev/null; then
        echo "$f" | sudo tee -a "$STATE_FILES" >/dev/null
    fi
}

is_hex_or_star() {
    local v="${1:-}"
    [[ "$v" == "*" ]] && return 0
    [[ "$v" =~ ^[0-9a-fA-F]{4}$ ]]
}

normalize_hex4_or_star() {
    local v="${1:-}"
    if [[ "$v" == "*" ]]; then
        echo "*"
    else
        echo "${v,,}"
    fi
}

# Create a udev rule line; handles product "*" by omitting ATTR{idProduct} match.
mk_udev_rule() {
    local vendor="$1"
    local product="$2"
    local extras="$3"
    
    if [[ "$product" == "*" ]]; then
        printf 'ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="%s"%s' "$vendor" "$extras"
    else
        printf 'ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="%s", ATTR{idProduct}=="%s"%s' "$vendor" "$product" "$extras"
    fi
}

backup_file() {
    local f="$1"
    [[ -f "$f" ]] || return 0
    local backup="${f}.bak.$(date +%Y%m%d%H%M%S)"
    sudo cp -a "$f" "$backup"
    ok "Backed up $f → $backup"
}

rule_already_present() {
    local rule_file="$1"
    local exact_line="$2"
    [[ -f "$rule_file" ]] || return 1
    sudo grep -qxF "$exact_line" "$rule_file"
}

write_rule_file() {
    local rule_file="$1"
    local exact_line="$2"
    local label="$3"
    
    # If exact rule already exists, do nothing (idempotent)
    if rule_already_present "$rule_file" "$exact_line"; then
        ok "$label rule already present in $rule_file (no changes)."
        return 0
    fi
    
    if [[ -f "$rule_file" ]]; then
        backup_file "$rule_file"
        if [[ "$AUTO_MODE" != "y" ]]; then
            if ! prompt_yn "Rule file exists: $rule_file — overwrite with new rule?" "n"; then
                warn "Skipped updating $rule_file"
                return 1
            fi
        else
            warn "Overwriting $rule_file due to --auto mode"
        fi
    fi
    
    echo "$exact_line" | sudo tee "$rule_file" >/dev/null || fail "Failed to write $label rule to $rule_file"
    sudo chmod a+r "$rule_file" || true
    record_managed_file "$rule_file"
    ok "Applied $label rule → $rule_file"
    return 0
}

reload_udev() {
    log "🔄 Reloading udev rules..."
    sudo udevadm control --reload-rules || fail "Failed to reload udev rules"
    # Trigger may fail if no matching devices are plugged in; don’t hard-fail.
    sudo udevadm trigger --subsystem-match=usb >/dev/null 2>&1 || true
    ok "udev rules reloaded."
}

restart_usbmuxd_if_present() {
    # usbmuxd is relevant for iOS devices; restart only if unit exists.
    if systemctl list-unit-files | grep -q '^usbmuxd\.service'; then
        log "🔁 Restarting usbmuxd service (for iOS devices)..."
        sudo systemctl restart usbmuxd || warn "usbmuxd restart failed — not always critical"
    else
        warn "usbmuxd service not found. Skipping restart."
    fi
}

run_uninstall() {
    section "🧹 Uninstalling udev rules managed by this script"
    
    if [[ ! -f "$STATE_FILES" ]]; then
        warn "No state file found ($STATE_FILES). Nothing to uninstall."
        exit 0
    fi
    
    mapfile -t files < <(sudo sed '/^\s*$/d' "$STATE_FILES" 2>/dev/null || true)
    if [[ ${#files[@]} -eq 0 ]]; then
        ok "No managed files recorded. Nothing to uninstall."
        exit 0
    fi
    
    log "Managed files:"
    printf '  - %s\n' "${files[@]}"
    
    if ! prompt_yn "Remove these rule files now?" "n"; then
        warn "Uninstall cancelled."
        exit 0
    fi
    
    local f
    for f in "${files[@]}"; do
        if [[ -f "$f" ]]; then
            backup_file "$f"
            sudo rm -f "$f" || warn "Failed to remove: $f"
            ok "Removed: $f"
        else
            warn "Not found (already removed): $f"
        fi
    done
    
    # Clear state (so uninstall is repeatable)
    sudo truncate -s 0 "$STATE_FILES" >/dev/null 2>&1 || true
    
    reload_udev
    restart_usbmuxd_if_present
    
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall early exit
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

### ─────────────────────────────────────────────────────────────────────────
### Input collection (interactive unless --auto or explicit flags provided)
### ─────────────────────────────────────────────────────────────────────────
if [[ "$AUTO_MODE" == "y" ]]; then
    iphone_vendor="${iphone_vendor:-$IPHONE_DEFAULT_VENDOR}"
    iphone_product="${iphone_product:-$IPHONE_DEFAULT_PRODUCT}"
    android_vendor="${android_vendor:-$ANDROID_DEFAULT_VENDOR}"
    android_product="${android_product:-$ANDROID_DEFAULT_PRODUCT}"
    log "⚙️ Auto mode: using defaults / provided flags"
else
    # If a value is missing, ask for it
    if [[ -z "${iphone_vendor:-}" ]]; then
        read -rp "Enter iPhone idVendor [default: $IPHONE_DEFAULT_VENDOR]: " iphone_vendor
    fi
    if [[ -z "${iphone_product:-}" ]]; then
        read -rp "Enter iPhone idProduct [default: $IPHONE_DEFAULT_PRODUCT]: " iphone_product
    fi
    if [[ -z "${android_vendor:-}" ]]; then
        read -rp "Enter Android idVendor [default: $ANDROID_DEFAULT_VENDOR]: " android_vendor
    fi
    if [[ -z "${android_product:-}" ]]; then
        read -rp "Enter Android idProduct [default: $ANDROID_DEFAULT_PRODUCT]: " android_product
    fi
fi

iphone_vendor="${iphone_vendor:-$IPHONE_DEFAULT_VENDOR}"
iphone_product="${iphone_product:-$IPHONE_DEFAULT_PRODUCT}"
android_vendor="${android_vendor:-$ANDROID_DEFAULT_VENDOR}"
android_product="${android_product:-$ANDROID_DEFAULT_PRODUCT}"

# Validate inputs
is_hex_or_star "$iphone_vendor" || fail "Invalid iPhone vendor: '$iphone_vendor' (expected 4 hex chars)"
is_hex_or_star "$iphone_product" || fail "Invalid iPhone product: '$iphone_product' (expected 4 hex chars or *)"
is_hex_or_star "$android_vendor" || fail "Invalid Android vendor: '$android_vendor' (expected 4 hex chars)"
is_hex_or_star "$android_product" || fail "Invalid Android product: '$android_product' (expected 4 hex chars)"

iphone_vendor="$(normalize_hex4_or_star "$iphone_vendor")"
iphone_product="$(normalize_hex4_or_star "$iphone_product")"
android_vendor="$(normalize_hex4_or_star "$android_vendor")"
android_product="$(normalize_hex4_or_star "$android_product")"

### ─────────────────────────────────────────────────────────────────────────
### Ensure udev dir exists
### ─────────────────────────────────────────────────────────────────────────
sudo mkdir -p "$UDEV_DIR" || fail "Failed to ensure udev rules directory: $UDEV_DIR"

### ─────────────────────────────────────────────────────────────────────────
### udev rules content (use correct syntax and optional product matching)
### ─────────────────────────────────────────────────────────────────────────
# Note: Using ENV{ID_MM_DEVICE_IGNORE} etc. is “ignore modem manager / mounts”.
# Adjust to your preference if you want MTP mounting etc.
IPHONE_EXTRAS=', ENV{ID_MM_DEVICE_IGNORE}="1"'
ANDROID_EXTRAS=', ENV{ID_MM_DEVICE_IGNORE}="1", ENV{UDISKS_IGNORE}="1", ENV{MTP_IGNORE}="1", ENV{GVFS_IGNORE}="1", ENV{ID_GPHOTO2_IGNORE}="1"'

iphone_rule="$(mk_udev_rule "$iphone_vendor" "$iphone_product" "$IPHONE_EXTRAS")"
android_rule="$(mk_udev_rule "$android_vendor" "$android_product" "$ANDROID_EXTRAS")"

### ─────────────────────────────────────────────────────────────────────────
### Apply rules (idempotent + safe overwrite)
### ─────────────────────────────────────────────────────────────────────────
declare -a applied_rules skipped_rules
applied_rules=()
skipped_rules=()

if write_rule_file "$IPHONE_RULE" "$iphone_rule" "iPhone"; then
    applied_rules+=("iPhone")
else
    skipped_rules+=("iPhone")
fi

if write_rule_file "$ANDROID_RULE" "$android_rule" "Android"; then
    applied_rules+=("Android")
else
    skipped_rules+=("Android")
fi

### ─────────────────────────────────────────────────────────────────────────
### Reload udev + restart usbmuxd (if present)
### ─────────────────────────────────────────────────────────────────────────
reload_udev
restart_usbmuxd_if_present

### ─────────────────────────────────────────────────────────────────────────
### Final summary
### ─────────────────────────────────────────────────────────────────────────
section "✅ udev Rules Setup Summary"
[[ ${#applied_rules[@]} -gt 0 ]] && ok "🟢 Applied rules: ${applied_rules[*]}"
[[ ${#skipped_rules[@]} -gt 0 ]] && warn "🟡 Skipped rules: ${skipped_rules[*]}"

ok "🎉 udev rules applied (or skipped) for iPhone and Android devices."
