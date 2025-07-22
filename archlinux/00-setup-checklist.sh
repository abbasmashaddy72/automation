#!/bin/bash

# Define each task as an associative array
declare -A task1=(
  [title]="Apply theme"
  [category]="Quick Settings"
  [action]="Select 'Breath Dark' theme"
)

declare -A task2=(
  [title]="Set touchpad speed"
  [category]="Mouse & Touchpad"
  [action]="Set Pointer speed to 0.4"
)

declare -A task3=(
  [title]="Set notification volume"
  [category]="Sound"
  [action]="Adjust notification volume"
)

declare -A task4=(
  [title]="Enable raise max volume"
  [category]="Sound"
  [action]="Enable 'Allow volume above 100%'"
)

declare -A task5=(
  [title]="Enable night light"
  [category]="Colors & Theme"
  [action]="Enable Night Light with Custom Schedule"
)

declare -A task6=(
  [title]="Set default browser"
  [category]="Default Applications"
  [action]="Set default browser (e.g., Firefox)"
)

declare -A task7=(
  [title]="Set task switcher"
  [category]="Window Management"
  [action]="Choose 'Flip Switch' for Task Switcher"
)

declare -A task8=(
  [title]="Set animation speed"
  [category]="General Behaviour"
  [action]="Increase Animation Speed by 4 points"
)

declare -A task9=(
  [title]="Disable recent files"
  [category]="Recent Files"
  [action]="Disable remembering recent files and clear list"
)

declare -A task10=(
  [title]="Enable spell check"
  [category]="Spell Check"
  [action]="Ensure automatic spell checking is enabled"
)

declare -A task11=(
  [title]="Set user email"
  [category]="Users"
  [action]="Set user email (e.g., for Git or system identity)"
)

declare -A task12=(
  [title]="Set session restore"
  [category]="Session"
  [action]="Enable 'Restore previous session on login'"
)

declare -A task13=(
  [title]="Setting hardware drivers"
  [category]="Manjaro Settings Manager"
  [action]="Go to Hardware Configurations and select auto install options one after another"
)

declare -A task14=(
  [title]="Configure Dolphin"
  [category]="Dolphin File Manager"
  [action]="Show all hidden files and change layout from icons to details"
)

declare -A task15=(
  [title]="Add/remove software"
  [category]="Preference"
  [action]="Enable 'Hide system tray when no updates' option"
)

declare -A task16=(
  [title]="Copy data from HDD"
  [category]="Data Transfer"
  [action]="Copy required data from HDD to appropriate location"
)

declare -A task17=(
  [title]="Enable KeepassXC Connect DB"
  [category]="KeepassXC"
  [action]="Enable database connection and browser integration"
)

declare -A task18=(
  [title]="Login to Ferdium"
  [category]="Ferdium"
  [action]="Open Ferdium and login with user credentials"
)

declare -A task19=(
  [title]="Install Windows in VirtualBox"
  [category]="Virtualization"
  [action]="Install Windows OS inside VirtualBox"
)

declare -A task20=(
  [title]="Add AIM RDP in Remmina"
  [category]="Remmina"
  [action]="Configure AIM RDP connection in Remmina"
)

declare -A task21=(
  [title]="Add Local DB and Production DB in DBeaver"
  [category]="DBeaver"
  [action]="Configure Local and Production databases in DBeaver"
)

declare -A task22=(
  [title]="Add company email in Thunderbird"
  [category]="Thunderbird"
  [action]="Setup company email account in Thunderbird"
)

declare -A task23=(
  [title]="Login to Chrome"
  [category]="Chrome"
  [action]="Login to Chrome browser with user account"
)

declare -A task24=(
  [title]="Set Firefox & Firefox Developer to open previous tabs"
  [category]="Firefox"
  [action]="Configure both Firefox and Firefox Developer editions to restore previous session tabs"
)

declare -A task25=(
  [title]="VS Code login with GitHub backup"
  [category]="VS Code"
  [action]="Login to VS Code and enable GitHub backup"
)

declare -A task26=(
  [title]="Void Connect the OLLAMA"
  [category]="Void"
  [action]="Connect Void app to OLLAMA service"
)

declare -A task27=(
  [title]="Postman login with Google"
  [category]="Postman"
  [action]="Login to Postman using Google account"
)

# Store all task variable names in a list
task_list=(task1 task2 task3 task4 task5 task6 task7 task8 task9 task10 task11 task12 task13 task14 task15 task16 task17 task18 task19 task20 task21 task22 task23 task24 task25 task26 task27)
status=()

echo "============================================"
echo "   🛠️  Interactive System Setup Checklist"
echo "============================================"
echo "Answer with [y]es or [n]o"
echo

# Loop through each task
for task_var in "${task_list[@]}"; do
  eval "title=\${$task_var[title]}"
  eval "category=\${$task_var[category]}"
  eval "action=\${$task_var[action]}"

  echo "🔹 Task:     $title"
  echo "   🗂  Menu:  $category"
  echo "   📋 Action: $action"

  while true; do
    read -p "   ✅ Done? (y/n): " input
    case "$input" in
      [Yy]) status+=("✔️ Done") ; break ;;
      [Nn]) status+=("❌ Skipped") ; break ;;
      *) echo "   ⚠️  Please enter y or n." ;;
    esac
  done

  echo
done

# Summary
echo "============================================"
echo "                 ✅ Summary"
echo "============================================"
for i in "${!task_list[@]}"; do
  task_var=${task_list[$i]}
  eval "title=\${$task_var[title]}"
  printf "%2d. %-30s %s\n" $((i+1)) "$title" "${status[$i]}"
done

echo
echo "🎉 Setup checklist complete!"
