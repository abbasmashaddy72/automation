#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 61-project-sites-setup.sh
#
# Purpose
# -------
# Creates an opinionated directory structure for Laravel/Valet dev workflow:
# - Creates a “Project-Sites” style folder tree (idempotent)
# - Ensures Composer is installed (pacman)
# - Ensures Valet (valet-linux) is installed via Composer global (idempotent)
# - Ensures required Valet dependencies exist
# - Runs `valet install` (idempotent best-effort)
# - Parks selected folders with `valet park`
#
# Why this exists
# --------------
# Parking is useless if Valet isn’t installed/initialized.
# Valet installation depends on Composer, so we validate that chain first.
#
# Safety / Reliability
# --------------------
# - Uses safe arg parsing
# - Avoids guessing Composer global paths (asks composer)
# - Tracks state under /var/lib/arch-dev-setup/61-project-sites-setup/
# - Supports --uninstall (restores what it can; does not nuke your projects)
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./61-project-sites-setup.sh
#   ./61-project-sites-setup.sh --dir "$HOME/Documents/Project-Sites"
#   ./61-project-sites-setup.sh --dir=/path/to/sites
#   ./61-project-sites-setup.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t mysterious)
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

section "📁 Laravel Project Sites Setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (uninstall tracking)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
ROOT_DIR="${PROJECT_SITES_DIR:-$HOME/Documents/Project-Sites}"

for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL="y" ;;
        --dir=*) ROOT_DIR="${arg#*=}" ;;
        --dir) : ;; # handled in the positional parse below
        -h|--help)
      cat <<EOF
Usage:
  $0 [--dir PATH]
  $0 --uninstall

Options:
  --dir PATH     Root folder for project sites (default: $HOME/Documents/Project-Sites)

Uninstall:
  Restores nothing inside your projects (does not delete folders),
  but can remove valet-linux (Composer global) if you confirm.
EOF
            exit 0
        ;;
    esac
done

# Proper positional parsing for --dir PATH
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[$i]}" in
        --dir)
            if (( i + 1 < ${#args[@]} )); then
                ROOT_DIR="${args[$((i+1))]}"
            fi
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/61-project-sites-setup"
STATE_PKGS="$STATE_DIR/installed-packages.txt"

sudo mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true
sudo touch "$STATE_PKGS" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to continue..."
sudo -v || fail "❌ Failed to authenticate sudo."

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
    local pkgs=("$@")
    local p
    for p in "${pkgs[@]}"; do
        if ! is_installed_pkg "$p"; then
            echo "$p" | sudo tee -a "$STATE_PKGS" >/dev/null
        fi
    done
}

ensure_pkgs() {
    local pkgs=("$@")
    record_installed_pkgs "${pkgs[@]}"
    sudo pacman -S --noconfirm --needed "${pkgs[@]}" || fail "Failed to install dependencies: ${pkgs[*]}"
}

ensure_composer() {
    section "🎼 Ensuring Composer is installed"
    if command -v composer &>/dev/null; then
        ok "Composer already installed: $(command -v composer)"
        return 0
    fi
    ensure_pkgs composer
    command -v composer &>/dev/null || fail "Composer installed but not found in PATH."
    ok "Composer ready."
}

resolve_composer_paths() {
    # Ask composer for canonical paths; only fallback if composer returns empty.
    COMPOSER_HOME="$(composer config --global home 2>/dev/null | tail -n 1 || true)"
    [[ -n "${COMPOSER_HOME// }" ]] || COMPOSER_HOME="$HOME/.config/composer"
    
    COMPOSER_BIN="$(composer global config bin-dir --absolute 2>/dev/null | tail -n 1 || true)"
    [[ -n "${COMPOSER_BIN// }" ]] || COMPOSER_BIN="$COMPOSER_HOME/vendor/bin"
    
    export COMPOSER_HOME
    export PATH="$COMPOSER_BIN:$PATH"
    
    log "Composer global home: $COMPOSER_HOME"
    log "Composer global bin:  $COMPOSER_BIN"
}

ensure_valet_deps() {
    section "🧩 Ensuring Valet dependencies"
    # Minimal deps you specified earlier
    ensure_pkgs nss jq xsel networkmanager
    ok "Valet dependencies ensured."
}

ensure_valet_installed() {
    section "🚗 Ensuring Valet is installed (valet-linux)"
    
    ensure_composer
    ensure_valet_deps
    resolve_composer_paths
    
    if command -v valet &>/dev/null; then
        ok "Valet already installed: $(command -v valet)"
        return 0
    fi
    
    log "Installing valet-linux via Composer (global)..."
    composer global require cpriego/valet-linux || fail "Failed to install valet-linux"
    
    hash -r 2>/dev/null || true
    command -v valet &>/dev/null || fail "Valet installed but not found in PATH (bin-dir: $COMPOSER_BIN)"
    ok "Valet installed: $(command -v valet)"
}

ensure_valet_initialized() {
    section "🛠 Ensuring Valet is initialized (valet install)"
    
    ensure_valet_installed
    
    # `valet install` is usually safe to re-run; treat failures as actionable.
    if valet install; then
        ok "Valet initialized."
    else
        warn "Valet install failed."
        warn "Common causes: missing nginx/dns tooling, NetworkManager not running, or permissions."
        fail "Valet initialization failed."
    fi
}

valet_park_dir() {
    local dir="$1"
    [[ -d "$dir" ]] || fail "Directory does not exist: $dir"
    ( cd "$dir" && valet park ) || fail "Valet failed to park in: $dir"
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall (best-effort)
### ─────────────────────────────────────────────────────────────────────────
run_uninstall() {
    section "🧹 Uninstall: Project Sites / Valet (best-effort)"
    
    # We do NOT delete your project directories.
    warn "This uninstall does NOT remove: $ROOT_DIR"
    warn "It can optionally remove valet-linux from Composer global packages."
    
    ensure_composer
    resolve_composer_paths
    
    if command -v valet &>/dev/null; then
        if prompt_yn "Remove valet-linux (composer global remove cpriego/valet-linux)?" "n"; then
            composer global remove cpriego/valet-linux || warn "Failed to remove valet-linux via composer."
            hash -r 2>/dev/null || true
            ok "Valet removal attempted."
        else
            log "Skipping valet-linux removal."
        fi
    else
        warn "Valet command not found; skipping valet removal."
    fi
    
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Directory structure config
### ─────────────────────────────────────────────────────────────────────────
SUBDIRS=(
    "Experiment"
    "Local"
    "Other-Languages"
    "Packages-Git"
    "Packages-Own"
    "Personal-Git"
    "Staging"
    "Testing"
)

PARKABLE_SUBDIRS=(
    "Experiment"
    "Local"
    "Staging"
    "Testing"
)

declare -a created_dirs existing_dirs parked_dirs

### ─────────────────────────────────────────────────────────────────────────
### Main flow
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

section "📂 Creating project sites structure"
log "Root directory: $ROOT_DIR"
mkdir -p "$ROOT_DIR" || fail "Could not create root directory: $ROOT_DIR"

for subdir in "${SUBDIRS[@]}"; do
    path="$ROOT_DIR/$subdir"
    if [[ -d "$path" ]]; then
        existing_dirs+=("$subdir")
    else
        mkdir -p "$path"
        created_dirs+=("$subdir")
    fi
done

if (( ${#created_dirs[@]} > 0 )); then ok "Created: ${created_dirs[*]}"; fi
if (( ${#existing_dirs[@]} > 0 )); then warn "Already existed: ${existing_dirs[*]}"; fi

# Ensure Valet is usable before parking
ensure_valet_initialized

section "🚗 Parking Valet in selected directories..."
for dir in "${PARKABLE_SUBDIRS[@]}"; do
    full_path="$ROOT_DIR/$dir"
    valet_park_dir "$full_path"
    parked_dirs+=("$dir")
    ok "Valet parked in: $dir"
done

section "📋 Project Sites Setup Summary"
(( ${#created_dirs[@]} > 0 )) && log "🟢 Created: ${created_dirs[*]}"
(( ${#existing_dirs[@]} > 0 )) && warn "🟡 Already existed: ${existing_dirs[*]}"
(( ${#parked_dirs[@]} > 0 )) && ok "🚗 Valet parked in: ${parked_dirs[*]}"

ok "🎉 Project Sites structure created and Valet parked successfully!"
