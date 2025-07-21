#!/bin/bash

set -e

# ========== DEFAULTS ==========
USER_HOME="$HOME"
BASE_DIR="$HOME/Documents/Project-Sites"
REPOS=()

# ========== HELPERS ==========

execute_command() {
    echo "▶ $2"
    eval "$1" && echo "✅ $2" || {
        echo "❌ $2"
        exit 1
    }
}

clone_repository() {
    local repo="$1"
    local target="$2"

    if [ -d "$target" ]; then
        echo "✅ Directory $target already exists."
    else
        git clone "https://github.com/$repo" "$target"
        echo "📦 Cloned $repo → $target"
    fi
}

# ========== PARSE ARGUMENTS ==========
for arg in "$@"; do
    case $arg in
    --repos=*)
        IFS=';' read -ra REPOS <<<"${arg#*=}"
        shift
        ;;
    esac
done

# ========== GIT SETUP ==========
execute_command "git config --global credential.helper store" "Configure Git Credential Store"

# You can customize these globally later or use your git identity manager
execute_command "git config --global user.name \"Your Name\"" "Set global Git user name"
execute_command "git config --global user.email \"you@example.com\"" "Set global Git email"

# ========== CLONE REPOS ==========
for entry in "${REPOS[@]}"; do
    IFS=',' read -r repo path <<<"$entry"
    clone_repository "$repo" "$BASE_DIR/$path"
done

# ========== Create PHP Info Page ==========
info_dir="$BASE_DIR/Personal/info"
mkdir -p "$info_dir"
echo "<?php phpinfo();" >"$info_dir/index.php"

# ========== NGINX: Fix ProtectHome ==========
NGINX_SERVICE="/usr/lib/systemd/system/nginx.service"
if ! grep -q "^ProtectHome=false" "$NGINX_SERVICE"; then
    sudo sed -i 's/^ProtectHome=.*/ProtectHome=false/' "$NGINX_SERVICE"
    echo "✅ ProtectHome set to false"
fi

# ========== SYSTEMD DAEMON RELOAD ==========
execute_command "sudo systemctl daemon-reexec" "Reload systemd"

# ========== APPARMOR PATCH (Full + Dynamic) ==========

APPARMOR_FILE="/etc/apparmor.d/php-fpm"
APPARMOR_PATCH=""
USER_HOME_ESCAPED=$(echo "$HOME" | sed 's/\//\\\//g')

check_line() {
    local line="$1"
    if ! grep -qF "$line" "$APPARMOR_FILE"; then
        APPARMOR_PATCH+="$line\n"
        echo "➕ Appending missing: $line"
    fi
}

# Required lines
check_line "abi <abi/3.0>"
check_line "include <tunables/global>"
check_line "include <abstractions/base>"
check_line "include <abstractions/nameservice>"
check_line "include <abstractions/openssl>"
check_line "include <abstractions/php>"
check_line "include <abstractions/ssl_certs>"
check_line "include if exists <local/php-fpm>"
check_line "include if exists <php-fpm.d>"

check_line "capability chown,"
check_line "capability dac_override,"
check_line "capability dac_read_search,"
check_line "capability kill,"
check_line "capability net_admin,"
check_line "capability setgid,"
check_line "capability setuid,"

check_line "signal send peer=php-fpm//*,"
check_line "deny / rw,"
check_line "/usr/libexec/libheif/ r,"
check_line "/usr/sbin/php-fpm* rix,"
check_line "/var/log/php*-fpm.log rw,"
check_line "@{PROC}/@{pid}/attr/{apparmor/,}current rw,"
check_line "@{run}/php*-fpm.pid rw,"
check_line "@{run}/php{,-fpm}/php*-fpm.pid rw,"
check_line "@{run}/php{,-fpm}/php*-fpm.sock rwlk,"

check_line "owner \"$HOME/Documents/Project Sites/**\" rw,"
check_line "owner /etc/ImageMagick-7/log.xml r,"
check_line "owner /etc/ImageMagick-7/policy.xml r,"
check_line "owner $HOME/.composer/vendor/cpriego/** rw,"
check_line "owner $HOME/.valet/** rw,"
check_line "owner /usr/share/ImageMagick-7/english.xml r,"
check_line "owner /usr/share/ImageMagick-7/locale.xml r,"

check_line "change_profile -> php-fpm//*,"

# Append if necessary
if [ -n "$APPARMOR_PATCH" ]; then
    echo -e "\n🔧 Updating AppArmor profile..."

    # Remove closing brace if exists
    sudo sed -i '$d' "$APPARMOR_FILE"

    # Append missing lines
    echo -e "$APPARMOR_PATCH" | sudo tee -a "$APPARMOR_FILE" >/dev/null

    # Add final closing brace
    echo "}" | sudo tee -a "$APPARMOR_FILE" >/dev/null

    echo "✅ AppArmor profile updated successfully."
else
    echo "✅ AppArmor profile already fully configured."
fi

# ========== RESTART SERVICES ==========
execute_command "sudo systemctl restart nginx php-fpm apparmor" "Restart Nginx, PHP-FPM, AppArmor"

# ========== VALET SETUP ==========
execute_command "valet install" "Valet Install"
execute_command "sudo systemctl status nginx php-fpm apparmor" "Verify service status"

for dir in Clients Personal Testing; do
    mkdir -p "$BASE_DIR/$dir"
    cd "$BASE_DIR/$dir" && execute_command "valet park" "Valet park: $dir"
done

echo "✅ All configurations completed!"
