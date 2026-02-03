#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 22-postgres-setup.sh
#
# Purpose
# -------
# Automated, idempotent PostgreSQL setup for Arch-based distros:
# - Installs PostgreSQL (pacman)
# - Initializes cluster (initdb) if needed
# - Enables + starts postgresql.service
# - Sets password for the 'postgres' role (interactive; min 8 chars)
# - Stores state so --uninstall can rollback safely
#
# Safety / Reliability
# --------------------
# - Skips cleanly if components are missing
# - Avoids deleting /var/lib/postgres/data unless you explicitly confirm
# - Tracks packages installed by this script for safe removal
# - Stores state under /var/lib/arch-dev-setup/22-postgres-setup/
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./22-postgres-setup.sh
#   ./22-postgres-setup.sh --uninstall
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

section "🐘 PostgreSQL setup for $PLATFORM_STRING"

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
  $0              Install + configure PostgreSQL
  $0 --uninstall  Stop/disable PostgreSQL and optionally remove data

State directory:
  /var/lib/arch-dev-setup/22-postgres-setup/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/22-postgres-setup"
STATE_PKGS="$STATE_DIR/installed-packages.txt"
STATE_INIT_FLAG="$STATE_DIR/cluster.initialized.flag"

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

cluster_initialized() {
    [[ -d /var/lib/postgres/data/base ]]
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
    section "🧹 Uninstalling PostgreSQL (best-effort rollback)"
    
    # Stop/disable service if it exists
    if systemctl list-unit-files | grep -q '^postgresql\.service'; then
        sudo systemctl stop postgresql 2>/dev/null || true
        sudo systemctl disable postgresql 2>/dev/null || true
        ok "postgresql.service stop/disable attempted."
    else
        warn "postgresql.service not found. Skipping service stop/disable."
    fi
    
    # Optionally remove data directory (destructive; require explicit consent)
    if [[ -d /var/lib/postgres/data ]]; then
        warn "PostgreSQL data directory exists: /var/lib/postgres/data"
        if prompt_yn "Delete /var/lib/postgres/data ? (DESTRUCTIVE: deletes all DBs)" "n"; then
            sudo rm -rf /var/lib/postgres/data || warn "Could not remove /var/lib/postgres/data"
            ok "Removed /var/lib/postgres/data"
        else
            warn "Leaving /var/lib/postgres/data intact."
        fi
    fi
    
    uninstall_remove_recorded_packages
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Install PostgreSQL (idempotent)
### ─────────────────────────────────────────────────────────────────────────
install_postgres() {
    if is_installed_pkg postgresql; then
        ok "PostgreSQL already installed."
        return 0
    fi
    
    log "📦 Installing PostgreSQL..."
    record_installed_pkgs postgresql
    sudo pacman -S --noconfirm --needed postgresql || fail "Failed to install PostgreSQL"
    ok "PostgreSQL installed."
}

### ─────────────────────────────────────────────────────────────────────────
### Initialize cluster (idempotent)
### ─────────────────────────────────────────────────────────────────────────
init_postgres_db() {
    if cluster_initialized; then
        ok "PostgreSQL cluster already initialized. Skipping initdb."
        return 0
    fi
    
    log "🔧 Initializing PostgreSQL cluster (initdb)..."
    # initdb location differs; on Arch, postgres user owns /var/lib/postgres
    sudo -u postgres initdb --locale "${LANG:-en_US.UTF-8}" -E UTF8 -D '/var/lib/postgres/data/' \
    || fail "PostgreSQL initdb failed"
    echo "initialized" | sudo tee "$STATE_INIT_FLAG" >/dev/null
    ok "PostgreSQL initialized."
}

### ─────────────────────────────────────────────────────────────────────────
### Enable + start service (idempotent)
### ─────────────────────────────────────────────────────────────────────────
start_postgres_service() {
    log "🚀 Enabling and starting postgresql.service..."
    sudo systemctl enable --now postgresql || fail "Failed to enable/start PostgreSQL service"
    
    # Give it a moment on slower machines
    sleep 2
    
    if sudo systemctl is-active --quiet postgresql; then
        ok "PostgreSQL service is running."
        return 0
    fi
    
    sudo systemctl status postgresql | tee -a "$LOGFILE" || true
    fail "PostgreSQL service failed to start."
}

### ─────────────────────────────────────────────────────────────────────────
### Password setting (interactive)
### ─────────────────────────────────────────────────────────────────────────
set_postgres_password() {
    local pass pass2
    
    while true; do
        read -rsp "🔐 Enter new password for PostgreSQL 'postgres' user (min 8 chars): " pass; echo
        read -rsp "🔁 Confirm password: " pass2; echo
        
        if [[ -n "$pass" && "$pass" == "$pass2" && ${#pass} -ge 8 ]]; then
            break
        fi
        warn "❌ Passwords do not match or are too short. Please try again."
    done
    
    # Escape single quotes for SQL literal
    local pass_sql
    pass_sql="${pass//\'/\'\'}"
    
    log "🔐 Setting password for 'postgres' role..."
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE postgres WITH PASSWORD '${pass_sql}';" \
    || fail "Failed to set postgres password"
    
    ok "Password set for 'postgres' role."
}

### ─────────────────────────────────────────────────────────────────────────
### Summary output
### ─────────────────────────────────────────────────────────────────────────
show_postgres_status() {
    section "🐘 PostgreSQL Version & Service Status"
    
    # Version
    if command -v psql &>/dev/null; then
        sudo -u postgres psql -V | tee -a "$LOGFILE" || true
    else
        warn "psql not found in PATH (unexpected)."
    fi
    
    # Service status
    sudo systemctl status postgresql | tee -a "$LOGFILE" || true
}

### ─────────────────────────────────────────────────────────────────────────
### Main
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

install_postgres
init_postgres_db
start_postgres_service
set_postgres_password
show_postgres_status

ok "🎉 PostgreSQL setup complete. User: postgres"
