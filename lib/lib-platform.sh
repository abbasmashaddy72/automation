#!/bin/bash
# lib/lib-platform.sh

set -euo pipefail

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
    local ok=false
    for distro in "$@"; do
        if [[ "$OS_ID" == "$distro" ]]; then
            ok=true
        fi
    done
    if [[ "$ok" != true ]]; then
        echo "✖ Unsupported platform: $OS_ID ($OS_NAME). Supported: $*"
        exit 1
    fi
}

# Usage: is_arch || (echo "Not arch"; exit 1)
is_arch() { [[ "$OS_ID" == "arch" ]]; }
is_manjaro() { [[ "$OS_ID" == "manjaro" ]]; }
is_x86_64() { [[ "$ARCH" == "x86_64" ]]; }
is_aarch64() { [[ "$ARCH" == "aarch64" ]]; }

# === Example usage (uncomment to test) ===
# ensure_supported_platform arch manjaro

# === Export for sourced use ===
export OS_ID OS_NAME ARCH PLATFORM_STRING

