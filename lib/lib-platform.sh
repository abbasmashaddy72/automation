#!/usr/bin/env bash
# === lib-platform.sh: Minimal, Root Distro Detection ===

if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_NAME="${NAME:-unknown}"
    OS_VERSION_ID="${VERSION_ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
else
    OS_ID="unknown"
    OS_NAME="Unknown Linux"
    OS_VERSION_ID="unknown"
    OS_LIKE=""
fi

KERNEL="$(uname -r)"
ARCH="$(uname -m)"

if grep -qi microsoft /proc/version 2>/dev/null || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
    IS_WSL=1
else
    IS_WSL=0
fi
if grep -qa 'docker\|lxc' /proc/1/cgroup 2>/dev/null; then
    IS_CONTAINER=1
else
    IS_CONTAINER=0
fi
if systemd-detect-virt &>/dev/null; then
    VIRT_TYPE="$(systemd-detect-virt)"
    IS_VIRTUAL=1
else
    VIRT_TYPE="none"
    IS_VIRTUAL=0
fi
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
    IS_ARM=1
else
    IS_ARM=0
fi

PLATFORM_STRING="$OS_ID ($OS_NAME $OS_VERSION_ID) / $ARCH / kernel:$KERNEL"
[[ $IS_WSL -eq 1 ]] && PLATFORM_STRING+=" / WSL"
[[ $IS_CONTAINER -eq 1 ]] && PLATFORM_STRING+=" / Container"
[[ $IS_VIRTUAL -eq 1 ]] && PLATFORM_STRING+=" / VM:$VIRT_TYPE"
[[ $IS_ARM -eq 1 ]] && PLATFORM_STRING+=" / ARM"

export OS_ID OS_NAME OS_VERSION_ID OS_LIKE ARCH KERNEL PLATFORM_STRING IS_WSL IS_CONTAINER VIRT_TYPE IS_VIRTUAL IS_ARM

ensure_supported_platform() {
    local target
    for target in "$@"; do
        [[ "$OS_ID" == "$target" || "$OS_LIKE" =~ $target ]] && return 0
    done
    if command -v fail &>/dev/null; then
        fail "Unsupported platform: Detected $OS_ID ($OS_NAME), expected: $*"
    else
        echo "✖ Unsupported platform: Detected $OS_ID ($OS_NAME), expected: $*" >&2
        exit 1
    fi
}

is_arch()    { [[ "$OS_ID" == "arch" || "$OS_LIKE" =~ arch ]]; }
is_debian()  { [[ "$OS_ID" == "debian" || "$OS_LIKE" =~ debian ]]; }
is_ubuntu()  { [[ "$OS_ID" == "ubuntu" || "$OS_LIKE" =~ debian ]]; }
is_fedora()  { [[ "$OS_ID" == "fedora" || "$OS_LIKE" =~ fedora ]]; }
is_x86_64()  { [[ "$ARCH" == "x86_64" ]]; }
is_aarch64() { [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; }
is_wsl()     { [[ $IS_WSL -eq 1 ]]; }
is_container(){ [[ $IS_CONTAINER -eq 1 ]]; }
is_virtual() { [[ $IS_VIRTUAL -eq 1 ]]; }
is_arm()     { [[ $IS_ARM -eq 1 ]]; }

platform_summary() {
    echo -e "🔎 Detected platform: $PLATFORM_STRING"
    [[ $IS_WSL -eq 1 ]]      && echo "   - WSL detected"
    [[ $IS_CONTAINER -eq 1 ]] && echo "   - Container environment detected"
    [[ $IS_VIRTUAL -eq 1 ]]  && echo "   - Virtualized: $VIRT_TYPE"
    [[ $IS_ARM -eq 1 ]]      && echo "   - ARM/Apple Silicon"
}

export -f ensure_supported_platform is_arch is_debian is_ubuntu is_fedora is_x86_64 is_aarch64 is_wsl is_container is_virtual is_arm platform_summary

# --- Example usage (uncomment for demo) ---
# platform_summary
# ensure_supported_platform arch
