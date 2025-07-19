#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "📁 Setting up Laravel-friendly Project Sites"

# === Config ===
ROOT_DIR="$HOME/Documents/Project-Sites"

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

# === Create Root Directory ===
log "📂 Creating root directory: $ROOT_DIR"
mkdir -p "$ROOT_DIR" || fail "Could not create root directory: $ROOT_DIR"

# === Create Subdirectories ===
for subdir in "${SUBDIRS[@]}"; do
    path="$ROOT_DIR/$subdir"
    if [[ -d "$path" ]]; then
        warn "Directory already exists: $subdir"
    else
        mkdir -p "$path"
        ok "Created: $subdir"
    fi
done

# === Valet Park ===
if ! command -v valet &>/dev/null; then
    fail "Laravel Valet is not installed. Cannot park folders."
fi

section "🚗 Parking Valet in selected directories..."

for dir in "${PARKABLE_SUBDIRS[@]}"; do
    full_path="$ROOT_DIR/$dir"
    cd "$full_path" || fail "Failed to change into $full_path"
    valet park || fail "Valet failed to park in $full_path"
    ok "Valet parked in: $dir"
done

ok "🎉 Project Sites structure created and valet parked successfully!"
