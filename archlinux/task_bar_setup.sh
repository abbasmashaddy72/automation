log "📌 Auto-detecting .desktop files and pinning to KDE Task Manager..."

# === 1. Your desired applications (human-friendly names) ===
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
    "VS Code"
    "Void"
    "Android Studio"
    "PyCharm"
    "IntelliJ"
    "Postman"
)

# === 2. Locate matching .desktop files ===
FOUND_LAUNCHERS=()

for name in "${APP_NAMES[@]}"; do
    # Search for .desktop file in known app folders
    desktop_file=$(find /usr/share/applications ~/.local/share/applications -iname "*$name*.desktop" | head -n1)
    if [[ -n "$desktop_file" ]]; then
        file_name=$(basename "$desktop_file")
        FOUND_LAUNCHERS+=("applications:${file_name}")
        log_ok "Found launcher for '$name' → $file_name"
    else
        log "⚠️ No launcher found for '$name'"
    fi
done

# === 3. Inject launchers= line into KDE config ===
APPLETSRC="$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc"
BACKUP="$APPLETSRC.bak.$(date +%s)"
cp "$APPLETSRC" "$BACKUP" || log_error "❌ Failed to backup plasma config"

# === 4. Locate task manager config section ===
SECTION_LINE=$(grep -n "^\[Containments\].*\[Applets\].*\[Configuration\]\[General\]" "$APPLETSRC" | cut -d: -f1 | head -n1)

if [[ -n "$SECTION_LINE" ]]; then
    NEW_LAUNCHERS_LINE="launchers=$(IFS=,; echo "${FOUND_LAUNCHERS[*]}")"
    
    awk -v section_line="$SECTION_LINE" -v new_line="$NEW_LAUNCHERS_LINE" '
    NR == section_line { in_section=1 }
    in_section && /^launchers=/ { print new_line; in_section=0; next }
    { print }
    ' "$APPLETSRC" > "${APPLETSRC}.tmp" && mv "${APPLETSRC}.tmp" "$APPLETSRC"

    log_ok "Updated pinned apps in task manager config."
else
    log_error "❌ Could not locate Task Manager config section in plasma-org.kde.plasma.desktop-appletsrc"
fi

# === 5. Restart Plasma to apply changes ===
log "🔄 Restarting Plasma shell to apply pinned apps..."
kquitapp5 plasmashell && kstart5 plasmashell
