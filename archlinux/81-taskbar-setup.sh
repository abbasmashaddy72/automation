#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 81-taskbar-setup.sh
#
# Purpose
# -------
# Automatically pins favorite apps to KDE Plasma taskbar (Task Manager).
# - Finds .desktop launchers from system/user application dirs
# - Updates the Task Manager "launchers=" list in plasma desktop applets config
# - Creates timestamped backups for safe rollback
# - Idempotent (re-running produces the same launcher list)
#
# Safety / Reliability
# --------------------
# - Detects Plasma session (and required tools) before editing anything
# - Backs up $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc
# - Uses a state dir for uninstall pointers:
#     /var/lib/arch-dev-setup/81-taskbar-setup/
# - Uses safer launcher discovery:
#     * fallback map for known “weird” names
#     * tries exact ID match first (desktop-file-validate friendly)
#     * then fuzzy find as a last resort
#
# Usage
# -----
#   ./81-taskbar-setup.sh
#   ./81-taskbar-setup.sh --apps=Firefox,Brave,code
#   PIN_APPS="Firefox,Brave,Visual Studio Code" ./81-taskbar-setup.sh
#   ./81-taskbar-setup.sh --uninstall
#
# Notes
# -----
# - Plasma writes multiple Task Manager instances; this targets the first
#   matching Task Manager "General" section found. If you have multiple panels,
#   you can extend the matching logic to target a specific containment/applet id.
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
  echo "❌ Error on line $1 while running: $2" >&2
}
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

section "📌 KDE Task Manager Pinning Setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Detect KDE/Plasma Session (defensive checks)
### ─────────────────────────────────────────────────────────────────────────
if [[ "${XDG_CURRENT_DESKTOP:-}" != *"KDE"* && "${DESKTOP_SESSION:-}" != *"plasma"* ]]; then
  fail "Not a KDE Plasma session. Aborting."
fi

# Tools used to restart plasmashell. On Plasma 6, kstart5 becomes kstart, etc.
have_kquit="n"
have_kstart="n"
command -v kquitapp5 &>/dev/null && have_kquit="y"
command -v kquitapp6 &>/dev/null && have_kquit="y"
command -v kstart5 &>/dev/null && have_kstart="y"
command -v kstart &>/dev/null && have_kstart="y"
[[ "$have_kquit" == "y" && "$have_kstart" == "y" ]] || warn "Plasma restart helpers missing. Script will still patch config, but you may need to log out/in."

### ─────────────────────────────────────────────────────────────────────────
### State (for uninstall pointers) + config path
### ─────────────────────────────────────────────────────────────────────────
STATE_DIR="/var/lib/arch-dev-setup/81-taskbar-setup"
STATE_LAST_BACKUP="$STATE_DIR/last-backup.path"
sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true

APPLETSRC="$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc"
if [[ ! -f "$APPLETSRC" ]]; then
  fail "Plasma config not found: $APPLETSRC"
fi

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

restart_plasma() {
  log "🔄 Restarting Plasma shell..."

  if command -v kquitapp6 &>/dev/null; then
    kquitapp6 plasmashell || warn "Failed to quit plasmashell (kquitapp6)"
  elif command -v kquitapp5 &>/dev/null; then
    kquitapp5 plasmashell || warn "Failed to quit plasmashell (kquitapp5)"
  else
    warn "kquitapp not found; skipping automatic restart."
    return 0
  fi

  # Slight pause helps plasmashell exit cleanly
  sleep 1

  if command -v kstart &>/dev/null; then
    kstart plasmashell || warn "Failed to start plasmashell (kstart)"
  elif command -v kstart5 &>/dev/null; then
    kstart5 plasmashell || warn "Failed to start plasmashell (kstart5)"
  else
    warn "kstart not found; skipping automatic restart."
  fi
}

backup_config() {
  local ts backup
  ts="$(date +%Y%m%d%H%M%S)"
  backup="$APPLETSRC.bak.$ts"
  cp -a "$APPLETSRC" "$backup" || fail "Failed to backup plasma config"
  ok "💾 Backed up plasma config to $backup"
  echo "$backup" | sudo tee "$STATE_LAST_BACKUP" >/dev/null
}

restore_backup() {
  if [[ ! -f "$STATE_LAST_BACKUP" ]]; then
    fail "No uninstall state found ($STATE_LAST_BACKUP)."
  fi
  local backup
  backup="$(sudo cat "$STATE_LAST_BACKUP" 2>/dev/null || true)"
  [[ -n "$backup" && -f "$backup" ]] || fail "Recorded backup missing/invalid: $backup"

  cp -a "$backup" "$APPLETSRC"
  ok "Restored KDE taskbar config from $backup"
}

# Convert app name or user token into a .desktop file name (best-effort):
# - If input already ends with .desktop, accept as-is if file exists somewhere
# - Try fallback table (hard-coded known IDs)
# - Try exact ID match by scanning application dirs
# - Try fuzzy find only as last resort
discover_desktop_file() {
  local name="$1"
  local candidate=""
  local found_path=""

  local search_paths=(/usr/share/applications)
  local user_app_dir="$HOME/.local/share/applications"
  [[ -d "$user_app_dir" ]] && search_paths+=("$user_app_dir")

  # If user passed "something.desktop"
  if [[ "$name" == *.desktop ]]; then
    for p in "${search_paths[@]}"; do
      if [[ -f "$p/$name" ]]; then
        echo "$name"
        return 0
      fi
    done
    # If it’s a full path
    if [[ -f "$name" && "$name" == *.desktop ]]; then
      echo "$(basename "$name")"
      return 0
    fi
  fi

  # fallback mapping
  if [[ -n "${APP_NAME_FALLBACKS[$name]:-}" ]]; then
    candidate="${APP_NAME_FALLBACKS[$name]}"
    for p in "${search_paths[@]}"; do
      if [[ -f "$p/$candidate" ]]; then
        echo "$candidate"
        return 0
      fi
    done
  fi

  # exact-ish match: try lowercase/space-normalized search for common desktop IDs
  # (We try a few patterns without going “find *everything*” first)
  local norm
  norm="$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9_.-')"

  for p in "${search_paths[@]}"; do
    # common: org.foo.Bar.desktop / foo.desktop / foo-bar.desktop
    for pat in \
      "${norm}.desktop" \
      "${norm//./-}.desktop" \
      "*${norm}*.desktop"
    do
      found_path="$(find "$p" -maxdepth 1 -type f -iname "$pat" 2>/dev/null | head -n1 || true)"
      if [[ -n "$found_path" ]]; then
        echo "$(basename "$found_path")"
        return 0
      fi
    done
  done

  return 1
}

### ─────────────────────────────────────────────────────────────────────────
### Rollback option
### ─────────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  section "♻️ Restoring previous KDE taskbar backup..."
  restore_backup
  restart_plasma
  ok "Plasma taskbar config restored!"
  exit 0
fi

### ─────────────────────────────────────────────────────────────────────────
### Application list setup
### ─────────────────────────────────────────────────────────────────────────
# Defaults (can override via PIN_APPS env or --apps=)
APP_NAMES=(
  "FreeTube"
  "Elisa"
  "System Monitor"
  "KeepassXC"
  "KCalc"
  "Ferdium"
  "AnyDesk"
  "VirtualBox"
  "Remmina"
  "WinSCP"
  "DBeaver"
  "Tiny RDM"
  "Thunderbird"
  "Tor Browser"
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

# Fallbacks for known naming mismatches
declare -A APP_NAME_FALLBACKS=(
  ["System Monitor"]="org.kde.plasma-systemmonitor.desktop"
  ["Firefox Developer Edition"]="firefox-developer-edition.desktop"
  ["Visual Studio Code"]="code.desktop"
  ["Android Studio"]="android-studio.desktop"
  ["IntelliJ IDEA Community Edition"]="idea.desktop"
  ["Tor Browser"]="torbrowser-launcher.desktop"
  ["Brave"]="brave-browser.desktop"
  ["Chrome"]="google-chrome.desktop"
  ["KeepassXC"]="org.keepassxc.KeePassXC.desktop"
)

# Override via env
if [[ -n "${PIN_APPS:-}" ]]; then
  IFS=, read -ra APP_NAMES <<< "$PIN_APPS"
fi

# Override via --apps=comma,separated,list
for arg in "$@"; do
  case "$arg" in
    --apps=*) IFS=, read -ra APP_NAMES <<< "${arg#*=}" ;;
  esac
done

declare -a FOUND_LAUNCHERS PINNED SKIPPED

### ─────────────────────────────────────────────────────────────────────────
### Discover desktop launcher files
### ─────────────────────────────────────────────────────────────────────────
log "🔍 Searching for .desktop launchers..."

for name in "${APP_NAMES[@]}"; do
  name="${name#"${name%%[![:space:]]*}"}"
  name="${name%"${name##*[![:space:]]}"}"

  if desktop_file="$(discover_desktop_file "$name")"; then
    FOUND_LAUNCHERS+=("applications:${desktop_file}")
    PINNED+=("$name")
    ok "Found launcher for '$name' → $desktop_file"
  else
    SKIPPED+=("$name")
    warn "No launcher found for '$name' (skipping)"
  fi
done

if [[ ${#FOUND_LAUNCHERS[@]} -eq 0 ]]; then
  fail "No .desktop files found — aborting taskbar pinning"
fi

### ─────────────────────────────────────────────────────────────────────────
### Backup current config
### ─────────────────────────────────────────────────────────────────────────
backup_config

### ─────────────────────────────────────────────────────────────────────────
### Locate and patch Task Manager section
### ─────────────────────────────────────────────────────────────────────────
# Plasma config is INI-ish with nested group headers.
# We locate the first occurrence of a Task Manager General section and patch its launchers= line.
#
# Common group format examples:
#   [Containments][1][Applets][2][Configuration][General]
#
# We match ANY section ending in [Configuration][General] and then replace the first "launchers=" inside it.
# If your setup has multiple Task Managers, this modifies the first match.
SECTION_LINE="$(grep -nE '^\[Containments\].*\[Applets\].*\[Configuration\]\[General\]$' "$APPLETSRC" | cut -d: -f1 | head -n1 || true)"
if [[ -z "$SECTION_LINE" ]]; then
  fail "Could not locate a [Configuration][General] section in: $APPLETSRC"
fi

NEW_LAUNCHERS_LINE="launchers=$(IFS=,; echo "${FOUND_LAUNCHERS[*]}")"

awk -v section_line="$SECTION_LINE" -v new_line="$NEW_LAUNCHERS_LINE" '
NR == section_line { in_section = 1 }
in_section && /^launchers=/ { print new_line; replaced = 1; in_section = 0; next }
{ print }
END { if (!replaced) { exit 3 } }
' "$APPLETSRC" > "${APPLETSRC}.tmp"

mv "${APPLETSRC}.tmp" "$APPLETSRC"
ok "Pinned applications updated in KDE Task Manager"

### ─────────────────────────────────────────────────────────────────────────
### Restart Plasma shell
### ─────────────────────────────────────────────────────────────────────────
restart_plasma

### ─────────────────────────────────────────────────────────────────────────
### Final output
### ─────────────────────────────────────────────────────────────────────────
section "📋 Final Pinned Applications"
log "🟢 Pinned: ${PINNED[*]}"
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  warn "🟡 Skipped (no launcher found): ${SKIPPED[*]}"
fi

ok "🎉 KDE taskbar pinned apps refreshed successfully!"
