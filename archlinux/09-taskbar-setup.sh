#!/bin/bash
set -euo pipefail

# === Logger ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📌 Auto-pinning favorite apps to KDE Task Manager"

# === App names to match (case-insensitive fuzzy search) ===
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
    "Firefox Developer"
    "Kate"
    "Visual Studio Code"
    "Void"
    "Android Studio"
    "PyCharm"
    "IntelliJ"
    "Postman"
)

# === Search for .desktop entries ===
FOUND_LAUNCHERS=()
log "🔍 Searching for .desktop launchers..."
for name in "${APP_NAMES[@]}"; do
    desktop_file=$(find /usr/share/applications ~/.local/share/applications -iname "*${name}*.desktop" | head -n1)
    if [[ -n "$desktop_file" ]]; then
        file_name=$(basename "$desktop_file")
        FOUND_LAUNCHERS+=("applications:${file_name}")
        ok "Found launcher for '$name' → $file_name"
    else
        warn "No launcher found for '$name'"
    fi
done

if [[ ${#FOUND_LAUNCHERS[@]} -eq 0 ]]; then
    fail "No .desktop files found — aborting taskbar pinning"
fi

# === Target Plasma Applet Config ===
APPLETSRC="$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc"
BACKUP="$APPLETSRC.bak.$(date +%s)"
cp "$APPLETSRC" "$BACKUP" || fail "Failed to backup plasma config"

log "💾 Backed up plasma config to $BACKUP"

# === Find Task Manager Configuration Section ===
SECTION_LINE=$(grep -n "^\[Containments\].*\[Applets\].*\[Configuration\]\[General\]" "$APPLETSRC" | cut -d: -f1 | head -n1)

if [[ -z "$SECTION_LINE" ]]; then
    fail "Could not locate [General] config section in $APPLETSRC"
fi

# === Replace launchers line ===
NEW_LAUNCHERS_LINE="launchers=$(IFS=,; echo "${FOUND_LAUNCHERS[*]}")"

awk -v section_line="$SECTION_LINE" -v new_line="$NEW_LAUNCHERS_LINE" '
NR == section_line { in_section = 1 }
in_section && /^launchers=/ { print new_line; in_section = 0; next }
{ print }
' "$APPLETSRC" > "${APPLETSRC}.tmp" && mv "${APPLETSRC}.tmp" "$APPLETSRC"

ok "Pinned applications updated in KDE Task Manager"

# === Restart Plasma Shell ===
log "🔄 Restarting Plasma shell..."
kquitapp5 plasmashell || warn "Failed to quit plasmashell gracefully"
kstart5 plasmashell || fail "Failed to start plasmashell"

ok "🎉 KDE taskbar pinned apps refreshed successfully!"
