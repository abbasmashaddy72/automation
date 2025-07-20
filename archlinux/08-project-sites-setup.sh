#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

ensure_supported_platform arch manjaro

section "📁 Setting up Laravel-friendly Project Sites"

# === Config: Allow user to set base dir ===
ROOT_DIR="${PROJECT_SITES_DIR:-$HOME/Documents/Project-Sites}"

for arg in "$@"; do
    case "$arg" in
        --dir=*) ROOT_DIR="${arg#*=}" ;;
        --dir) shift; ROOT_DIR="${1:-$ROOT_DIR}" ;;
    esac
done

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

# === Create Root Directory ===
log "📂 Creating root directory: $ROOT_DIR"
mkdir -p "$ROOT_DIR" || fail "Could not create root directory: $ROOT_DIR"

# === Create Subdirectories (idempotent) ===
for subdir in "${SUBDIRS[@]}"; do
    path="$ROOT_DIR/$subdir"
    if [[ -d "$path" ]]; then
        warn "Directory already exists: $subdir"
        existing_dirs+=("$subdir")
    else
        mkdir -p "$path" && ok "Created: $subdir"
        created_dirs+=("$subdir")
    fi
done

# === Valet Park Check ===
if ! command -v valet &>/dev/null; then
    fail "Laravel Valet is not installed. Cannot park folders."
fi

section "🚗 Parking Valet in selected directories..."

for dir in "${PARKABLE_SUBDIRS[@]}"; do
    full_path="$ROOT_DIR/$dir"
    cd "$full_path" || fail "Failed to change into $full_path"
    valet park || fail "Valet failed to park in $full_path"
    parked_dirs+=("$dir")
    ok "Valet parked in: $dir"
done

# === Print Summary ===
section "📋 Project Sites Setup Summary"
[[ ${#created_dirs[@]} -gt 0 ]] && log "🟢 Created: ${created_dirs[*]}"
[[ ${#existing_dirs[@]} -gt 0 ]] && warn "🟡 Already existed: ${existing_dirs[*]}"
[[ ${#parked_dirs[@]} -gt 0 ]] && ok "🚗 Valet parked in: ${parked_dirs[*]}"

ok "🎉 Project Sites structure created and valet parked successfully!"
