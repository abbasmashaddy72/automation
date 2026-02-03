#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 99-setup-checklist.sh
#
# Purpose
# -------
# Interactive post-install system setup checklist with task status.
# - Tasks are defined in one place using:
#     add_task "Title | Category | Action"
# - Runs an interactive loop asking "Done? y/n"
# - Prints a clean summary at the end
#
# Fixes vs your original
# ----------------------
# ✅ Safer shebang + error trap for easier debugging
# ✅ Correct parsing of "Title | Category | Action"
#    (Your original used: IFS=" | " which does NOT split on " | " as a token.
#     In bash, IFS is a set of *single characters*, so it split on space or '|'
#     and would mangle fields.)
# ✅ Handles titles/actions that contain spaces reliably
# ✅ Optional non-interactive mode: --yes-all / --no-all
# ✅ Optional export to a file: --out=/path/to/report.txt
#
# Usage
# -----
#   ./99-setup-checklist.sh
#   ./99-setup-checklist.sh --yes-all
#   ./99-setup-checklist.sh --no-all
#   ./99-setup-checklist.sh --out="$HOME/setup-checklist.txt"
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() { echo "❌ Error on line $1 while running: $2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Args
### ─────────────────────────────────────────────────────────────────────────
MODE="interactive"   # interactive | yes-all | no-all
OUTFILE=""

for arg in "$@"; do
    case "$arg" in
        --yes-all) MODE="yes-all" ;;
        --no-all)  MODE="no-all" ;;
        --out=*)   OUTFILE="${arg#*=}" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0 [options]

Options:
  --yes-all        Mark every task as done (non-interactive)
  --no-all         Mark every task as skipped (non-interactive)
  --out=FILE       Write the summary to FILE
  -h, --help       Show this help
EOF
            exit 0
        ;;
    esac
done

### ─────────────────────────────────────────────────────────────────────────
### Task registry
### ─────────────────────────────────────────────────────────────────────────
declare -a tasks=()
add_task() { tasks+=("$1"); }

# --- Add tasks here using: add_task "Title | Category | Action" ---
add_task "Apply theme | Quick Settings | Select 'Breath Dark' theme"
add_task "Set touchpad speed | Mouse & Touchpad | Set Pointer speed to 0.4"
add_task "Set notification volume | Sound | Adjust notification volume"
add_task "Enable raise max volume | Sound | Enable 'Allow volume above 100%'"
add_task "Enable night light | Colors & Theme | Enable Night Light with Custom Schedule"
add_task "Set default browser | Default Applications | Set default browser (e.g., Firefox)"
add_task "Set task switcher | Window Management | Choose 'Flip Switch' for Task Switcher"
add_task "Set animation speed | General Behaviour | Increase Animation Speed by 4 points"
add_task "Disable recent files | Recent Files | Disable remembering recent files and clear list"
add_task "Enable spell check | Spell Check | Ensure automatic spell checking is enabled"
add_task "Set user email | Users | Set user email (e.g., for Git or system identity)"
add_task "Set session restore | Session | Enable 'Restore previous session on login'"
add_task "Setting hardware drivers | Manjaro Settings Manager | Go to Hardware Configurations and select auto install options one after another"
add_task "Configure Dolphin | Dolphin File Manager | Show all hidden files and change layout from icons to details"
add_task "Add/remove software | Preference | Enable 'Hide system tray when no updates' option"
add_task "Copy data from HDD | Data Transfer | Copy required data from HDD to appropriate location"
add_task "Enable KeepassXC Connect DB | KeepassXC | Enable database connection and browser integration"
add_task "Login to Ferdium | Ferdium | Open Ferdium and login with user credentials"
add_task "Install Windows in VBox | Virtualization | Install Windows OS inside VirtualBox"
add_task "Add AIM RDP in Remmina | Remmina | Configure AIM RDP connection in Remmina"
add_task "Add Local/Prod DB in DBeaver | DBeaver | Configure Local and Production databases in DBeaver"
add_task "Add company email in Thunderbird | Thunderbird | Setup company email account in Thunderbird"
add_task "Login to Chrome | Chrome | Login to Chrome browser with user account"
add_task "Set Firefox/Dev session restore | Firefox | Configure both Firefox and Firefox Developer to restore previous session tabs"
add_task "VS Code login with GitHub | VS Code | Login to VS Code and enable GitHub backup"
add_task "Void connect the OLLAMA | Void | Connect Void app to OLLAMA service"
add_task "Postman login with Google | Postman | Login to Postman using Google account"
# --- End of tasks ---

### ─────────────────────────────────────────────────────────────────────────
### Status store
### ─────────────────────────────────────────────────────────────────────────
declare -a status=()

### ─────────────────────────────────────────────────────────────────────────
### Helpers
### ─────────────────────────────────────────────────────────────────────────
trim() {
    local s="${1:-}"
    # remove leading
    s="${s#"${s%%[![:space:]]*}"}"
    # remove trailing
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# Split "Title | Category | Action" reliably.
# We split on '|' first, then trim whitespace around each field.
parse_task() {
    local line="$1"
    local a b c rest
    
    # First field
    a="${line%%|*}"
    rest="${line#*|}"
    
    # Second field
    b="${rest%%|*}"
    c="${rest#*|}"
    
    # If there weren’t enough separators, fill safely
    if [[ "$line" != *"|"* ]]; then
        a="$line"; b=""; c=""
        elif [[ "$rest" == "$line" ]]; then
        b=""; c=""
        elif [[ "$c" == "$rest" ]]; then
        c=""
    fi
    
    title="$(trim "$a")"
    category="$(trim "$b")"
    action="$(trim "$c")"
}

write_line() {
    local msg="$1"
    echo "$msg"
    if [[ -n "${OUTFILE:-}" ]]; then
        echo "$msg" >> "$OUTFILE"
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Header
### ─────────────────────────────────────────────────────────────────────────
if [[ -n "${OUTFILE:-}" ]]; then
    : > "$OUTFILE" || { echo "❌ Cannot write to --out file: $OUTFILE" >&2; exit 1; }
fi

write_line "============================================"
write_line "   🛠️  Interactive System Setup Checklist"
write_line "============================================"
if [[ "$MODE" == "interactive" ]]; then
    write_line "Answer with [y]es or [n]o"
else
    write_line "Mode: $MODE (non-interactive)"
fi
write_line ""

### ─────────────────────────────────────────────────────────────────────────
### Main loop
### ─────────────────────────────────────────────────────────────────────────
for i in "${!tasks[@]}"; do
    parse_task "${tasks[$i]}"
    
    write_line "🔹 Task:     $title"
    write_line "   🗂  Menu:  ${category:-—}"
    write_line "   📋 Action: ${action:-—}"
    
    case "$MODE" in
        yes-all)
            status[$i]="✔️ Done"
            write_line "   ✅ Done? (auto): y"
        ;;
        no-all)
            status[$i]="❌ Skipped"
            write_line "   ✅ Done? (auto): n"
        ;;
        interactive)
            while true; do
                read -r -p "   ✅ Done? (y/n): " input
                case "$input" in
                    [Yy]) status[$i]="✔️ Done"; break ;;
                    [Nn]) status[$i]="❌ Skipped"; break ;;
                    *) echo "   ⚠️  Please enter y or n." ;;
                esac
            done
        ;;
    esac
    
    write_line ""
done

### ─────────────────────────────────────────────────────────────────────────
### Summary
### ─────────────────────────────────────────────────────────────────────────
write_line "============================================"
write_line "                 ✅ Summary"
write_line "============================================"

for i in "${!tasks[@]}"; do
    parse_task "${tasks[$i]}"
    printf -v line "%2d. %-35s %s" $((i+1)) "$title" "${status[$i]}"
    write_line "$line"
done

write_line ""
write_line "🎉 Setup checklist complete!"

if [[ -n "${OUTFILE:-}" ]]; then
    echo "📄 Summary written to: $OUTFILE"
fi
