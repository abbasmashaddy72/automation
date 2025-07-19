#!/bin/bash

set -euo pipefail

# === Setup ===
ROOT_DIR="$HOME/Documents/Project-Sites"
SUBDIRS=(
    "Staging"
    "Experiment"
    "Personal-Git"
    "Packages-Git"
    "Packages-Own"
    "Local"
    "Testing"
    "Other-Languages"
)

PARKABLE_SUBDIRS=(
    "Staging"
    "Experiment"
    "Local"
    "Testing"
)

timestamp() { date '+%F %T'; }
log() { echo "$(timestamp) | $*"; }
log_ok() { echo "$(timestamp) | ✅ $*"; }
log_error() {
    echo "$(timestamp) | ❌ ERROR: $*"
    exit 1
}

log "📁 Creating Laravel-friendly project structure under $ROOT_DIR"

mkdir -p "$ROOT_DIR" || log_error "Could not create root folder: $ROOT_DIR"

for subdir in "${SUBDIRS[@]}"; do
    path="$ROOT_DIR/$subdir"
    if [ -d "$path" ]; then
        log "🔁 $subdir already exists"
    else
        mkdir -p "$path"
        log_ok "Created $subdir"
    fi
done

# === Run Valet park on specific subdirectories ===
if ! command -v valet &>/dev/null; then
    log_error "Valet is not installed. Please install Laravel Valet first."
fi

for park_dir in "${PARKABLE_SUBDIRS[@]}"; do
    full_path="$ROOT_DIR/$park_dir"
    cd "$full_path" || log_error "Failed to cd into $full_path"
    valet park || log_error "Failed to run valet park in $full_path"
    log_ok "✅ Valet parked in $park_dir"
done

log_ok "🎉 Project-Sites directory structure created and valet parked!"
