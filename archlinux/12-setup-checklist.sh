#!/bin/bash
set -euo pipefail

##############################################################################
# 12-setup-checklist.sh
#   - Interactive post-install system setup checklist with task status
#   - Uses add_task "Title | Category | Action" for legible entries
##############################################################################

# --- Add tasks here using: add_task "Title | Category | Action" ---
declare -a tasks=()
add_task() {
  tasks+=("$1")
}

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
add_task "Enable KeepassXC Connect DB| KeepassXC | Enable database connection and browser integration"
add_task "Login to Ferdium | Ferdium | Open Ferdium and login with user credentials"
add_task "Install Windows in VBox | Virtualization | Install Windows OS inside VirtualBox"
add_task "Add AIM RDP in Remmina | Remmina | Configure AIM RDP connection in Remmina"
add_task "Add Local/Prod DB in DBeaver| DBeaver | Configure Local and Production databases in DBeaver"
add_task "Add company email in Thunderbird | Thunderbird | Setup company email account in Thunderbird"
add_task "Login to Chrome | Chrome | Login to Chrome browser with user account"
add_task "Set Firefox/Dev session restore | Firefox | Configure both Firefox and Firefox Developer to restore previous session tabs"
add_task "VS Code login with GitHub | VS Code | Login to VS Code and enable GitHub backup"
add_task "Void connect the OLLAMA | Void | Connect Void app to OLLAMA service"
add_task "Postman login with Google | Postman | Login to Postman using Google account"

# --- End of tasks ---

# Store task statuses
declare -a status=()

echo "============================================"
echo "   🛠️  Interactive System Setup Checklist"
echo "============================================"
echo "Answer with [y]es or [n]o"
echo

# Interactive main loop
for i in "${!tasks[@]}"; do
  IFS=" | " read -r title category action <<< "${tasks[$i]}"
  printf "🔹 Task:     %s\n" "$title"
  printf "   🗂  Menu:  %s\n" "$category"
  printf "   📋 Action: %s\n" "$action"
  while true; do
    read -p "   ✅ Done? (y/n): " input
    case "$input" in
      [Yy]) status[$i]="✔️ Done" ; break ;;
      [Nn]) status[$i]="❌ Skipped" ; break ;;
      *) echo "   ⚠️  Please enter y or n." ;;
    esac
  done
  echo
done

# Summary
echo "============================================"
echo "                 ✅ Summary"
echo "============================================"
for i in "${!tasks[@]}"; do
  IFS=" | " read -r title _ _ <<< "${tasks[$i]}"
  printf "%2d. %-35s %s\n" $((i+1)) "$title" "${status[$i]}"
done

echo
echo "🎉 Setup checklist complete!"
