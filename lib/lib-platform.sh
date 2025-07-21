#!/bin/bash

# === OS Detection ===
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_NAME="${NAME:-unknown}"
else
    OS_ID="unknown"
    OS_NAME="Unknown Linux"
fi

# === Architecture Detection ===
ARCH="$(uname -m)"

# === Pretty String for Logging ===
PLATFORM_STRING="$OS_ID ($OS_NAME) / $ARCH"

# === Helper Functions ===

# Usage: ensure_supported_platform arch manjaro
ensure_supported_platform() {
    local target
    for target in "$@"; do
        if [[ "$OS_ID" == "$target" ]]; then
            return 0
        fi
    done
    # Defensive: handle if 'fail' not defined yet
    if command -v fail &>/dev/null; then
        fail "Unsupported platform: Detected $OS_ID ($OS_NAME), expected: $*"
    else
        echo "✖ Unsupported platform: Detected $OS_ID ($OS_NAME), expected: $*" >&2
        exit 1
    fi
}

is_arch() { [[ "$OS_ID" == "arch" ]]; }
is_manjaro() { [[ "$OS_ID" == "manjaro" ]]; }
is_x86_64() { [[ "$ARCH" == "x86_64" ]]; }
is_aarch64() { [[ "$ARCH" == "aarch64" ]]; }

platform_summary() {
    echo "Detected platform: $PLATFORM_STRING"
}

# === Export for sourced use ===
export OS_ID OS_NAME ARCH PLATFORM_STRING

# === Example usage (uncomment to test) ===
# ensure_supported_platform arch manjaro
# platform_summary
