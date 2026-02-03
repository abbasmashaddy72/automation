#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 21-mariadb-setup.sh
#
# Purpose
# -------
# Automated, idempotent MariaDB setup for Arch-based distros:
# - Installs MariaDB (pacman)
# - Initializes the data directory if needed
# - Enables + starts mariadb.service
# - Optionally runs secure hardening (interactive password prompt)
# - Tracks what it changed so --uninstall can rollback safely
#
# Safety / Reliability
# --------------------
# - Skips cleanly when components aren’t present
# - Avoids nuking /var/lib/mysql unless YOU confirm
# - Stores state under /var/lib/arch-dev-setup/21-mariadb-setup/
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./21-mariadb-setup.sh
#   ./21-mariadb-setup.sh --uninstall
#
# Notes
# -----
# - This script prompts for a root password (min 8 chars) and will apply it.
# - MariaDB auth plugins vary by distro/version; we use a best-effort method:
#     * run mariadb-secure-installation if present
#     * then attempt to enforce root password via SQL
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
  echo "❌ Error on line $1 while running: $2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Library checks and bootstrap
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

section "📦 MariaDB setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (for uninstall + tracking)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
for arg in "$@"; do
  case "$arg" in
    --uninstall) DO_UNINSTALL="y" ;;
    -h|--help)
      cat <<EOF
Usage:
  $0              Install + configure MariaDB
  $0 --uninstall  Disable/stop MariaDB and optionally remove data

State directory:
  /var/lib/arch-dev-setup/21-mariadb-setup/
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

STATE_DIR="/var/lib/arch-dev-setup/21-mariadb-setup"
STATE_PKGS="$STATE_DIR/installed-packages.txt"
STATE_INIT_FLAG="$STATE_DIR/datadir.initialized.flag"

sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true
sudo touch "$STATE_PKGS" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to begin..."
if ! sudo -v; then
  fail "❌ Failed to authenticate sudo."
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

is_installed_pkg() { pacman -Q "$1" &>/dev/null; }

record_installed_pkgs() {
  # Record only packages NOT installed before this script runs.
  local pkgs=("$@")
  local p
  for p in "${pkgs[@]}"; do
    if ! is_installed_pkg "$p"; then
      echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
    fi
  done
}

datadir_initialized() {
  [[ -d /var/lib/mysql/mysql ]]
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall mode
### ─────────────────────────────────────────────────────────────────────────
uninstall_remove_recorded_packages() {
  if [[ ! -f "$STATE_PKGS" ]]; then
    warn "No recorded packages file found. Skipping package removal."
    return 0
  fi

  mapfile -t pkgs < <(sudo sort -u "$STATE_PKGS" | sed '/^\s*$/d' || true)
  if [[ ${#pkgs[@]} -eq 0 ]]; then
    ok "No packages were recorded as installed by this script."
    return 0
  fi

  section "🧯 Uninstall: packages installed by this script"
  printf '  - %s\n' "${pkgs[@]}"

  if prompt_yn "Remove these packages now? (safe: only ones this script added)" "n"; then
    local to_remove=()
    local p
    for p in "${pkgs[@]}"; do
      if is_installed_pkg "$p"; then
        to_remove+=("$p")
      fi
    done

    if [[ ${#to_remove[@]} -gt 0 ]]; then
      sudo pacman -Rns --noconfirm "${to_remove[@]}" || warn "Some removals failed (deps in use/required)."
      ok "Package removal attempted."
    else
      ok "None of the recorded packages are currently installed."
    fi
  else
    log "Skipping package removal."
  fi
}

run_uninstall() {
  section "🧹 Uninstalling MariaDB (best-effort rollback)"

  # Stop/disable service if it exists
  if systemctl list-unit-files | grep -q '^mariadb\.service'; then
    sudo systemctl stop mariadb 2>/dev/null || true
    sudo systemctl disable mariadb 2>/dev/null || true
    ok "mariadb.service stop/disable attempted."
  else
    warn "mariadb.service not found. Skipping service stop/disable."
  fi

  # Optionally remove data directory (this is destructive; require explicit consent)
  if [[ -d /var/lib/mysql ]]; then
    warn "MariaDB data directory exists: /var/lib/mysql"
    if prompt_yn "Delete /var/lib/mysql ? (DESTRUCTIVE: deletes all databases)" "n"; then
      sudo rm -rf /var/lib/mysql || warn "Could not remove /var/lib/mysql"
      ok "Removed /var/lib/mysql"
    else
      warn "Leaving /var/lib/mysql intact."
    fi
  fi

  # Remove packages this script installed (if any)
  uninstall_remove_recorded_packages

  ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Connectivity check (optional but helpful)
### ─────────────────────────────────────────────────────────────────────────
check_internet() {
  if ping -c1 -W1 archlinux.org &>/dev/null; then
    ok "Internet connectivity: OK"
    return 0
  fi
  warn "No internet connectivity detected. If packages are cached locally, this may still work."
  return 1
}

### ─────────────────────────────────────────────────────────────────────────
### Install MariaDB (idempotent)
### ─────────────────────────────────────────────────────────────────────────
install_mariadb() {
  if is_installed_pkg mariadb; then
    ok "MariaDB already installed."
    return 0
  fi

  log "📥 Installing MariaDB..."
  record_installed_pkgs mariadb
  sudo pacman -S --needed --noconfirm mariadb || fail "Failed to install MariaDB."
  ok "MariaDB installed."
}

### ─────────────────────────────────────────────────────────────────────────
### Initialize database (idempotent)
### ─────────────────────────────────────────────────────────────────────────
initialize_datadir_if_needed() {
  if datadir_initialized; then
    ok "MariaDB data directory already initialized."
    return 0
  fi

  log "🛠️ Initializing MariaDB data directory..."
  # Record that this script performed initialization
  sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql || fail "MariaDB initialization failed."
  echo "initialized" | sudo tee "$STATE_INIT_FLAG" >/dev/null
  ok "MariaDB initialized."
}

### ─────────────────────────────────────────────────────────────────────────
### Enable + start service (idempotent)
### ─────────────────────────────────────────────────────────────────────────
enable_and_start_service() {
  log "🚀 Enabling and starting mariadb.service..."
  sudo systemctl enable --now mariadb || fail "Failed to enable/start mariadb.service"
  ok "mariadb.service enabled and started."
}

verify_service() {
  log "🔍 Verifying MariaDB service status..."
  if sudo systemctl is-active --quiet mariadb; then
    ok "MariaDB is running."
    return 0
  fi
  sudo systemctl status mariadb | tee -a "$LOGFILE" || true
  fail "MariaDB service is not running."
}

### ─────────────────────────────────────────────────────────────────────────
### Secure installation (interactive)
### ─────────────────────────────────────────────────────────────────────────
prompt_root_password() {
  local pass pass2
  section "🛡️ Secure MariaDB Installation"

  read -rsp "🔑 Enter new MariaDB root password (min 8 chars): " pass; echo
  read -rsp "🔑 Confirm password: " pass2; echo

  if [[ -z "$pass" || "$pass" != "$pass2" || ${#pass} -lt 8 ]]; then
    fail "Password validation failed. Must not be empty, must match, and be at least 8 characters."
  fi

  export MARIADB_ROOT_PASSWORD="$pass"
}

run_secure_installation() {
  # Run mariadb-secure-installation if present (best-effort, may vary by version).
  if command -v mariadb-secure-installation &>/dev/null; then
    log "🔒 Running mariadb-secure-installation (best-effort)..."
    if ! sudo mariadb-secure-installation <<EOF
Y
$MARIADB_ROOT_PASSWORD
$MARIADB_ROOT_PASSWORD
Y
Y
Y
Y
EOF
    then
      warn "⚠️ mariadb-secure-installation failed or partially succeeded."
    else
      ok "✅ mariadb-secure-installation completed."
    fi
  else
    warn "mariadb-secure-installation not found. Skipping that step."
  fi
}

enforce_root_password_sql() {
  # MariaDB root auth varies: sometimes unix_socket, sometimes mysql_native_password.
  # We try a safe approach:
  # - Attempt ALTER USER to set password
  # - If that fails, we warn and you can fix manually
  log "🔐 Enforcing root password via SQL (best-effort)..."

  local sql
  sql="$(cat <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED BY '${MARIADB_ROOT_PASSWORD}';
FLUSH PRIVILEGES;
EOF
)"

  # First try: connect as root via local socket auth (common on Arch)
  if echo "$sql" | sudo mariadb -u root; then
    ok "✅ Root password set successfully."
    return 0
  fi

  warn "Could not set root password using local socket auth."
  warn "Your installation may require different auth plugin handling."
  warn "Manual check: sudo mariadb -u root"
  return 1
}

### ─────────────────────────────────────────────────────────────────────────
### Main
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
  run_uninstall
  exit 0
fi

check_internet || true
install_mariadb
initialize_datadir_if_needed
enable_and_start_service
verify_service

# Show version info
mariadb_version="$(mariadb --version 2>/dev/null || mysql --version 2>/dev/null || true)"
[[ -n "$mariadb_version" ]] && log "MariaDB version: $mariadb_version"

# Secure hardening (interactive)
prompt_root_password
run_secure_installation
enforce_root_password_sql || true

ok "🎉 MariaDB setup completed successfully!"

section "✅ MariaDB Final Status"
sudo systemctl status mariadb | tee -a "$LOGFILE" || true
mariadb --version 2>/dev/null | tee -a "$LOGFILE" || true
