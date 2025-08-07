#!/usr/bin/env bash
set -euo pipefail

##############################################################################
# 06-kde-taskbar-pinning-setup.sh
#   - Automatically pins favorite apps to KDE Plasma taskbar (Task Manager)
#   - Clean rollback and backup support
#   - Idempotent, declarative, and self-documenting
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

section "📌 KDE Task Manager Pinning Setup for $PLATFORM_STRING"

### ─── Detect KDE/Plasma Session ──────────────────────────────────────────

if [[ "${XDG_CURRENT_DESKTOP:-}" != *"KDE"* && "${DESKTOP_SESSION:-}" != *"plasma"* ]]; then
    fail "Not a KDE Plasma session. Aborting."
fi

### ─── Rollback Option ────────────────────────────────────────────────────

APPLETSRC="$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc"
if [[ "${1:-}" == "--uninstall" ]]; then
    section "♻️ Restoring previous KDE taskbar backup..."
    latest_backup=$(ls -t "$APPLETSRC.bak."* 2>/dev/null | head -n1 || true)
    if [[ -f "$latest_backup" ]]; then
        cp "$latest_backup" "$APPLETSRC"
        ok "Restored KDE taskbar config from $latest_backup"
        log "🔄 Restarting Plasma shell..."
        kquitapp5 plasmashell || warn "Failed to quit plasmashell gracefully"
        kstart5 plasmashell || fail "Failed to start plasmashell"
        ok "Plasma taskbar config restored!"
        exit 0
    else
        fail "No backup found to restore!"
    fi
fi

### ─── Application List Setup ─────────────────────────────────────────────

# Allow override via PIN_APPS env or --apps flag
if [[ -n "${PIN_APPS:-}" ]]; then
    IFS=, read -ra APP_NAMES <<< "$PIN_APPS"
else
    APP_NAMES=(
        "Elisa"
        "System Monitor"
        "KeepassXC"
        "Kcalc"
        "Ferdium"
        "AnyDesk"
        "VirtualBox"
        "Remmina"
        "WinSCP"
        "DBeaver"
        "Thunderbird"
        "Brave"
        "Firefox"
        "Chrome"
        "Firefox Developer Edition"
        "Kate"
        "Visual Studio Code"
        "Void"
        "Android Studio"
        "PyCharm"
        "IntelliJ IDEA Community Edition"
        "Postman"
    )
fi

declare -A APP_NAME_FALLBACKS=(
    ["System Monitor"]="org.kde.plasma-systemmonitor.desktop"
    ["Firefox Developer Edition"]="firefox-developer-edition.desktop"
    ["Visual Studio Code"]="code.desktop"
    ["Android Studio"]="android-studio.desktop"
    ["IntelliJ IDEA Community Edition"]="idea.desktop"
)

# CLI flag: --apps=comma,separated,list
for arg in "$@"; do
    case "$arg" in
        --apps=*) IFS=, read -ra APP_NAMES <<< "${arg#*=}" ;;
    esac
done

declare -a FOUND_LAUNCHERS PINNED

### ─── Discover Desktop Launcher Files ────────────────────────────────────

log "🔍 Searching for .desktop launchers..."
for name in "${APP_NAMES[@]}"; do
    file_name=""

    # Try auto-discovery
    search_paths=(/usr/share/applications)
    user_app_dir="$HOME/.local/share/applications"
    [[ -d "$user_app_dir" ]] && search_paths+=("$user_app_dir")

    desktop_file=$(find "${search_paths[@]}" -type f -iname "*${name}*.desktop" 2>/dev/null | head -n1)
    if [[ -n "$desktop_file" ]]; then
        file_name=$(basename "$desktop_file")
        ok "Found launcher for '$name' → $file_name"
    elif [[ -n "${APP_NAME_FALLBACKS[$name]:-}" ]]; then
        file_name="${APP_NAME_FALLBACKS[$name]}"
        warn "Used fallback for '$name' → $file_name"
    else
        warn "No launcher found for '$name'"
    fi

    if [[ -n "$file_name" ]]; then
        FOUND_LAUNCHERS+=("applications:${file_name}")
        PINNED+=("$name")
    fi
done

if [[ ${#FOUND_LAUNCHERS[@]} -eq 0 ]]; then
    fail "No .desktop files found — aborting taskbar pinning"
fi

### ─── Backup Current Config ──────────────────────────────────────────────

BACKUP="$APPLETSRC.bak.$(date +%s)"
cp "$APPLETSRC" "$BACKUP" || fail "Failed to backup plasma config"
ok "💾 Backed up plasma config to $BACKUP"

### ─── Locate and Patch Task Manager Section ──────────────────────────────

# Use awk to replace 'launchers=' in [General] config section.
SECTION_LINE=$(grep -n "^\[Containments\].*\[Applets\].*\[Configuration\]\[General\]" "$APPLETSRC" | cut -d: -f1 | head -n1)
if [[ -z "$SECTION_LINE" ]]; then
    fail "Could not locate [General] config section in $APPLETSRC"
fi

NEW_LAUNCHERS_LINE="launchers=$(IFS=,; echo "${FOUND_LAUNCHERS[*]}")"

awk -v section_line="$SECTION_LINE" -v new_line="$NEW_LAUNCHERS_LINE" '
NR == section_line { in_section = 1 }
in_section && /^launchers=/ { print new_line; in_section = 0; next }
{ print }
' "$APPLETSRC" > "${APPLETSRC}.tmp" && mv "${APPLETSRC}.tmp" "$APPLETSRC"

ok "Pinned applications updated in KDE Task Manager"

### ─── Restart Plasma Shell ───────────────────────────────────────────────

log "🔄 Restarting Plasma shell..."
kquitapp5 plasmashell || warn "Failed to quit plasmashell gracefully"
kstart5 plasmashell || fail "Failed to start plasmashell"

section "📋 Final Pinned Applications"
log "🟢 Pinned: ${PINNED[*]}"

ok "🎉 KDE taskbar pinned apps refreshed successfully!"

# End of script. Your desktop is now fully corporate-pilled.
