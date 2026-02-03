#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 20-php-runtime-setup.sh
#
# Purpose
# -------
# Opinionated, safe PHP runtime bootstrap for Arch-based distros.
#
# Installs
# --------
# ✅ PHP + php-fpm
# ✅ Common PHP extensions (ONLY if available in pacman repos)
#
# Configures (idempotent)
# -----------------------
# ✅ PHP tuning:        /etc/php/conf.d/custom.ini
# ✅ php-fpm overrides: /etc/php/php-fpm.d/custom_upload.conf
# ✅ nginx upload cap:  /etc/nginx/conf.d/custom_upload.conf (optional; only if nginx installed)
#
# Safety Rules (non-negotiable)
# -----------------------------
# ✅ Never writes broken extension ini stubs (checks `php -m` first)
# ✅ Never fails because an extension package doesn't exist (repo check)
#
# What this does NOT do
# ---------------------
# ❌ Node/NPM/NVM
# ❌ Composer / Valet / Valkey
#
# Usage
# -----
#   ./20-php-runtime-setup.sh
#   ./20-php-runtime-setup.sh --uninstall
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors have receipts)
### ─────────────────────────────────────────────────────────────────────────
on_err() { echo "❌ Error on line $1 while running: $2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Boot: load shared libraries
### ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBDIR="$SCRIPT_DIR/../lib"

if [[ ! -f "$LIBDIR/lib-logger.sh" ]]; then
  echo "Logger library not found! Exiting." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-logger.sh"

if [[ ! -f "$LIBDIR/lib-platform.sh" ]]; then
  fail "Platform library not found! Exiting."
fi
# shellcheck disable=SC1091
source "$LIBDIR/lib-platform.sh"

# Keep this list aligned with your other scripts
ensure_supported_platform arch cachyos manjaro garuda endeavouros
section "🐘 PHP Runtime Setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront (fail early instead of dying mid-flight)
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to begin..."
sudo -v || fail "❌ Failed to authenticate sudo."

### ─────────────────────────────────────────────────────────────────────────
### Helpers (idempotency + safety)
### ─────────────────────────────────────────────────────────────────────────
have_cmd() { command -v "$1" &>/dev/null; }
is_installed_pkg() { pacman -Qi "$1" &>/dev/null; }
repo_has_pkg() { pacman -Si "$1" &>/dev/null; }

install_pkg_if_available() {
  # Install a package only if:
  #  - not already installed
  #  - present in pacman repositories
  # Otherwise: skip with a warning (no hard failure)
  local pkg="$1"

  if is_installed_pkg "$pkg"; then
    ok "$pkg already installed."
    return 0
  fi

  if ! repo_has_pkg "$pkg"; then
    warn "Skipping '$pkg' (not available in pacman repos on this system)."
    return 0
  fi

  log "Installing $pkg..."
  sudo pacman -S --noconfirm --needed "$pkg" || warn "❌ Failed to install $pkg"
  is_installed_pkg "$pkg" && ok "Installed $pkg" || warn "❌ $pkg still not installed after attempt"
}

backup_if_exists() {
  # Creates a timestamped backup if file exists
  local path="$1"
  [[ -f "$path" ]] || return 0
  local bak="${path}.bak.$(date +%Y%m%d%H%M%S)"
  sudo cp "$path" "$bak" >/dev/null 2>&1 || true
  warn "Backup created: $bak"
}

write_file_if_changed() {
  # Write content to a root-owned file only if different
  local path="$1"
  local content="$2"

  if [[ -f "$path" ]] && diff -q <(printf "%s" "$content") "$path" &>/dev/null; then
    ok "No changes needed: $path"
    return 0
  fi

  backup_if_exists "$path"
  printf "%s" "$content" | sudo tee "$path" >/dev/null
  ok "Updated: $path"
}

##############################################################################
# Uninstall mode (best-effort cleanup)
##############################################################################
if [[ "${1:-}" == "--uninstall" ]]; then
  section "🧹 Uninstalling PHP runtime (best-effort)"

  # Stop services first (don’t error if they’re absent)
  sudo systemctl stop php-fpm.service >/dev/null 2>&1 || warn "php-fpm was not running"
  sudo systemctl disable php-fpm.service >/dev/null 2>&1 || warn "php-fpm was not enabled"

  # Files managed by this script
  declare -a managed_files=(
    "/etc/php/conf.d/custom.ini"
    "/etc/nginx/conf.d/custom_upload.conf"
    "/etc/php/php-fpm.d/custom_upload.conf"
  )

  # Extension ini stubs managed by this script
  declare -a managed_ext_inis=(
    "/etc/php/conf.d/zz-bcmath.ini"
    "/etc/php/conf.d/zz-gd.ini"
    "/etc/php/conf.d/zz-intl.ini"
    "/etc/php/conf.d/zz-iconv.ini"
    "/etc/php/conf.d/zz-mbstring.ini"
    "/etc/php/conf.d/zz-pdo.ini"
    "/etc/php/conf.d/zz-pdo_mysql.ini"
    "/etc/php/conf.d/zz-sqlite3.ini"
    "/etc/php/conf.d/zz-zip.ini"
  )

  log "Removing managed config files..."
  sudo rm -f "${managed_files[@]}" >/dev/null 2>&1 || true

  log "Removing managed extension ini stubs..."
  sudo rm -f "${managed_ext_inis[@]}" >/dev/null 2>&1 || true

  # Remove packages (won’t hard-fail if deps are in use)
  declare -a remove_pkgs=(
    php
    php-fpm
    php-apcu
    php-gd
    php-intl
    php-mbstring
    php-pdo
    php-pdo-mysql
    php-sqlite
    php-xml
    php-zip
    php-xdebug
    php-redis
  )

  log "Removing packages (best-effort)..."
  sudo pacman -Rs --noconfirm "${remove_pkgs[@]}" >/dev/null 2>&1 \
    || warn "Could not remove some packages (deps in use or not installed)."

  ok "Uninstall complete."
  exit 0
fi

##############################################################################
# Step 1: Install PHP + common extensions (repo-checked)
##############################################################################
install_php_stack() {
  section "📥 Installing PHP + common extensions (repo-checked)"

  # Some distros fold certain extensions into core php.
  # We still list them; repo check prevents false installs.
  local pkgs=(
    php
    php-fpm
    php-apcu
    php-gd
    php-intl
    php-mbstring
    php-pdo
    php-pdo-mysql
    php-sqlite
    php-xml
    php-zip
    php-xdebug
    php-redis
  )

  for pkg in "${pkgs[@]}"; do
    install_pkg_if_available "$pkg"
  done
}

##############################################################################
# Step 2: Enable php-fpm (only if installed)
##############################################################################
enable_php_fpm() {
  section "🛠 Enabling php-fpm"

  if ! is_installed_pkg "php-fpm"; then
    warn "php-fpm package not installed. Skipping service enable."
    return 0
  fi

  sudo systemctl enable --now php-fpm.service || fail "php-fpm service failed to start or enable"
  ok "php-fpm is active and enabled"
}

##############################################################################
# Step 3: Write PHP runtime tuning file (idempotent)
##############################################################################
write_custom_php_ini() {
  section "⚙️ Writing PHP runtime tuning (/etc/php/conf.d/custom.ini)"

  read -r -p "Enter max upload size (default: 64M): " upload_max_filesize
  upload_max_filesize="${upload_max_filesize:-64M}"

  read -r -p "Enter max post size (default: 64M): " post_max_size
  post_max_size="${post_max_size:-64M}"

  read -r -p "Enter memory limit (default: 512M): " memory_limit
  memory_limit="${memory_limit:-512M}"

  read -r -p "Enter max execution time (default: 300): " max_execution_time
  max_execution_time="${max_execution_time:-300}"

  local path="/etc/php/conf.d/custom.ini"
  local content
  content="$(cat <<EOF
; PHP runtime tuning for local development
; Managed by: 20-php-runtime-setup.sh
;
; Revert:
;   sudo rm -f /etc/php/conf.d/custom.ini
;   sudo systemctl restart php-fpm

opcache.enable=1
opcache.enable_cli=1
opcache.memory_consumption=128
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=10000
opcache.revalidate_freq=0
opcache.fast_shutdown=1

realpath_cache_size=4096K
realpath_cache_ttl=600

memory_limit=${memory_limit}
max_execution_time=${max_execution_time}
upload_max_filesize=${upload_max_filesize}
post_max_size=${post_max_size}
EOF
)"
  write_file_if_changed "$path" "$content"
}

##############################################################################
# Step 4: Optional nginx upload cap (only if nginx installed)
##############################################################################
write_custom_nginx_upload_conf() {
  section "⚙️ Writing Nginx upload cap (optional)"

  if ! is_installed_pkg "nginx"; then
    warn "nginx not installed. Skipping nginx upload config."
    return 0
  fi

  read -r -p "Enter Nginx max body size (default: 1024M): " nginx_max_body_size
  nginx_max_body_size="${nginx_max_body_size:-1024M}"

  local path="/etc/nginx/conf.d/custom_upload.conf"
  local content
  content="$(cat <<EOF
# Nginx upload cap for local development
# Managed by: 20-php-runtime-setup.sh

client_max_body_size ${nginx_max_body_size};
EOF
)"
  write_file_if_changed "$path" "$content"
}

##############################################################################
# Step 5: php-fpm pool overrides (only if php-fpm installed)
##############################################################################
write_custom_php_fpm_conf() {
  section "⚙️ Writing php-fpm pool overrides (/etc/php/php-fpm.d/custom_upload.conf)"

  if ! is_installed_pkg "php-fpm"; then
    warn "php-fpm not installed. Skipping php-fpm override config."
    return 0
  fi

  read -r -p "Enter PHP upload_max_filesize (default: 1024M): " upload_max_filesize
  upload_max_filesize="${upload_max_filesize:-1024M}"

  read -r -p "Enter PHP post_max_size (default: 1024M): " post_max_size
  post_max_size="${post_max_size:-1024M}"

  read -r -p "Enter PHP memory_limit (default: 1024M): " memory_limit
  memory_limit="${memory_limit:-1024M}"

  local path="/etc/php/php-fpm.d/custom_upload.conf"
  local content
  content="$(cat <<EOF
; php-fpm pool overrides for local development
; Managed by: 20-php-runtime-setup.sh
;
; Revert:
;   sudo rm -f /etc/php/php-fpm.d/custom_upload.conf
;   sudo systemctl restart php-fpm

php_admin_value[upload_max_filesize] = ${upload_max_filesize}
php_admin_value[post_max_size] = ${post_max_size}
php_admin_value[memory_limit] = ${memory_limit}
EOF
)"
  write_file_if_changed "$path" "$content"
}

##############################################################################
# Step 6: Ensure select PHP extensions are enabled (no duplicates)
##############################################################################
php_ext_enabled() {
  local ext="$1"

  # Best signal: `php -m`
  if have_cmd php; then
    php -m 2>/dev/null | tr '[:upper:]' '[:lower:]' | grep -qx "${ext,,}" && return 0
  fi

  # Fallback: our managed ini exists
  [[ -f "/etc/php/conf.d/zz-${ext}.ini" ]] && return 0
  return 1
}

enable_extra_php_extensions() {
  section "📎 Ensuring select PHP extensions are enabled (no dup ini spam)"

  if ! have_cmd php; then
    warn "php not found in PATH yet. Skipping extension enable step."
    return 0
  fi

  local extensions=(bcmath gd intl iconv mbstring pdo pdo_mysql sqlite3 zip)

  for ext in "${extensions[@]}"; do
    if php_ext_enabled "$ext"; then
      ok "Extension already enabled: $ext"
      continue
    fi

    # Don’t create ini stubs for extensions whose packages aren’t even available.
    case "$ext" in
      gd) repo_has_pkg php-gd || { warn "php-gd not in repos; skipping $ext"; continue; } ;;
      intl) repo_has_pkg php-intl || { warn "php-intl not in repos; skipping $ext"; continue; } ;;
      mbstring) repo_has_pkg php-mbstring || { warn "php-mbstring not in repos; skipping $ext"; continue; } ;;
      pdo_mysql) repo_has_pkg php-pdo-mysql || { warn "php-pdo-mysql not in repos; skipping $ext"; continue; } ;;
      sqlite3) repo_has_pkg php-sqlite || { warn "php-sqlite not in repos; skipping $ext"; continue; } ;;
      zip) repo_has_pkg php-zip || { warn "php-zip not in repos; skipping $ext"; continue; } ;;
      *) : ;;
    esac

    local ini_file="/etc/php/conf.d/zz-${ext}.ini"
    echo "extension=${ext}" | sudo tee "$ini_file" >/dev/null
    ok "Enabled $ext via $ini_file"
  done
}

##############################################################################
# Step 7: Restart php-fpm (only if installed)
##############################################################################
restart_php_fpm() {
  section "🔄 Restarting php-fpm"

  if ! is_installed_pkg "php-fpm"; then
    warn "php-fpm not installed. Skipping restart."
    return 0
  fi

  sudo systemctl restart php-fpm.service || fail "Failed to restart php-fpm"
  ok "php-fpm restarted successfully"
}

##############################################################################
# Step 8: Final verification
##############################################################################
final_checks() {
  section "🧪 Verifying PHP runtime"

  have_cmd php || fail "php is not available in PATH"
  php -v | tee -a "$LOGFILE"

  if is_installed_pkg "php-fpm"; then
    sudo systemctl is-active --quiet php-fpm.service \
      && ok "php-fpm is running" \
      || warn "php-fpm installed but not running (check: systemctl status php-fpm)"
  fi

  ok "All checks complete."
}

### ─────────────────────────────────────────────────────────────────────────
### MAIN FLOW
### ─────────────────────────────────────────────────────────────────────────
install_php_stack
enable_php_fpm
write_custom_php_ini
write_custom_nginx_upload_conf
write_custom_php_fpm_conf
enable_extra_php_extensions
restart_php_fpm
final_checks

ok "🎉 PHP runtime setup completed."
