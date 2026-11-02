#!/usr/bin/env bash
# Bootstrap without Python. No arbitrary repositories, curl|bash or package substitutions.
set -Eeuo pipefail
umask 077
export LC_ALL=C

usage() {
    cat <<'HELP'
Usage: bash setup.sh prerequisites check|install [options]
  --with-ui          Include optional Gum terminal UI
  --without-ui       Skip Gum (used for automatic setup preflight)
  --with-validation  Include optional ShellCheck and shfmt tools
  --with-lerd        Include Podman/crun prerequisites (supported systemd hosts)
  --runtime-only     Check/bootstrap only Python (automatic command preflight)
  --with-ai-build    Include Git, CMake, Make, CA certificates and the native C++ compiler
  --with-ollama      Include curl, tar, zstd, CA certificates and installer utilities
  --with-git         Include Git for explicit user identity configuration
  --with-ssh         Include OpenSSH client, agent and key-generation commands
  --dry-run          Print the plan; do not install or refresh packages
  --yes              Approve an install in noninteractive sessions
  --non-interactive  Never prompt

Core prerequisites: Python >=3.9, curl, tar, unzip, CA certificates.
Uses existing distro package repositories only; never adds repositories.
No Lerd or optional tool is installed unless explicitly requested.
HELP
}

ACTION="${1:-check}"
case "$ACTION" in check|install) shift || true ;; -h|--help|help) usage; exit 0 ;; *) usage >&2; exit 2 ;; esac
WITH_UI=0 WITH_VALIDATION=0 WITH_LERD=0 WITH_AI_BUILD=0 WITH_OLLAMA=0 WITH_GIT=0 WITH_SSH=0 RUNTIME_ONLY=0 DRY_RUN=0 YES=0 NONINTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --with-ui) WITH_UI=1 ;;
        --without-ui) WITH_UI=2 ;;
        --with-validation) WITH_VALIDATION=1 ;;
        --with-lerd) WITH_LERD=1 ;;
        --with-ai-build) WITH_AI_BUILD=1 ;;
        --with-ollama) WITH_OLLAMA=1 ;;
        --with-git) WITH_GIT=1 ;;
        --with-ssh) WITH_SSH=1 ;;
        --runtime-only) RUNTIME_ONLY=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --yes|-y) YES=1 ;;
        --non-interactive) NONINTERACTIVE=1 ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Unknown prerequisite option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

# Test release fixtures are permitted ONLY for read-only commands.
OS_RELEASE=/etc/os-release
if [[ "$ACTION" == check || "$DRY_RUN" == 1 ]]; then
    OS_RELEASE="${AUTOMATION_PREREQ_OS_RELEASE:-$OS_RELEASE}"
fi
if [[ ! -r "$OS_RELEASE" ]]; then printf 'Missing os-release: %s\n' "$OS_RELEASE" >&2; exit 3; fi
ID=unknown ID_LIKE='' VERSION_ID='' VARIANT_ID=''
# Parse literal data, never source the file (os-release can contain shell syntax).
while IFS='=' read -r key value; do
    case "$key" in
        ID|ID_LIKE|VERSION_ID|VARIANT_ID)
            value="${value%\"}"; value="${value#\"}"
            value="${value%\'}"; value="${value#\'}"
            case "$key" in ID) ID="$value" ;; ID_LIKE) ID_LIKE="$value" ;; VERSION_ID) VERSION_ID="$value" ;; VARIANT_ID) VARIANT_ID="$value" ;; esac
            ;;
    esac
done < "$OS_RELEASE"
FAMILY=unknown
for item in "$ID" $ID_LIKE; do
    case "$item" in
        arch|archlinux|manjaro|cachyos|endeavouros|garuda|artix) FAMILY=arch; break ;;
        debian|ubuntu|linuxmint|pop|kali|elementary|zorin|raspbian) FAMILY=debian; break ;;
        fedora|nobara) FAMILY=fedora; break ;;
        rhel|rocky|almalinux|centos|ol) FAMILY=rhel; break ;;
        opensuse*|suse|sles) FAMILY=opensuse; break ;;
        alpine) FAMILY=alpine; break ;;
    esac
done
case "$FAMILY" in
    arch) MANAGER=pacman ;;
    debian) MANAGER=apt-get ;;
    fedora|rhel) MANAGER=dnf ;;
    opensuse) MANAGER=zypper ;;
    alpine) MANAGER=apk ;;
    *) MANAGER='' ;;
esac
printf 'Platform: %s %s / %s / manager: %s\n' "$ID" "$VERSION_ID" "$FAMILY" "${MANAGER:-unsupported}"
READONLY_HOST=0
case "$ID" in
    fedora-silverblue|silverblue|kinoite|sericea|onyx|aurora|bazzite|bluefin|ublue|nixos|microos|opensuse-microos|aeon|opensuse-aeon|kalpa|opensuse-kalpa|fedora-coreos|fedora-iot) READONLY_HOST=1 ;;
esac
case "$VARIANT_ID" in silverblue|kinoite|sericea|onyx|coreos|sway-atomic|cosmic-atomic|budgie-atomic) READONLY_HOST=1 ;; esac
if [[ -e /run/ostree-booted || -n "${WSL_DISTRO_NAME:-}" ]]; then READONLY_HOST=1; fi
if [[ -r /proc/version ]]; then
    kernel_version="$(< /proc/version)"
    if [[ "${kernel_version,,}" == *microsoft* ]]; then READONLY_HOST=1; fi
fi
if (( READONLY_HOST )); then printf 'Read-only planning target: immutable host or WSL; native prerequisite installation is disabled.\n'; fi
if [[ -z "$MANAGER" ]]; then
    printf 'No safe automatic prerequisite installer for this distribution.\n' >&2
    exit 3
fi
if [[ "$ACTION" == install && "$DRY_RUN" == 0 ]] && ! command -v "$MANAGER" >/dev/null 2>&1; then
    printf 'Native package manager missing: %s\n' "$MANAGER" >&2; exit 3
fi

python_ok() {
    command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1
}
package_name() {
    case "$1:$FAMILY" in
        python3:arch) echo python ;;
        python3:opensuse)
            case "$ID:$VERSION_ID" in
                opensuse-tumbleweed:*|opensuse-slowroll:*|opensuse-leap:16*) echo python313 ;;
                *) echo python3 ;;
            esac ;;
        shellcheck:fedora|shellcheck:rhel|shellcheck:opensuse) echo ShellCheck ;;
        awk:debian) echo mawk ;;
        awk:*) echo gawk ;;
        tee:*) echo coreutils ;;
        xargs:*) echo findutils ;;
        c++:arch) echo gcc ;;
        c++:debian|c++:alpine) echo g++ ;;
        c++:fedora|c++:rhel|c++:opensuse) echo gcc-c++ ;;
        ssh-client:debian|ssh-keygen:debian) echo openssh-client ;;
        ssh-client:arch|ssh-keygen:arch) echo openssh ;;
        ssh-client:fedora|ssh-keygen:fedora|ssh-client:rhel|ssh-keygen:rhel) echo openssh-clients ;;
        ssh-client:opensuse|ssh-keygen:opensuse) echo openssh-clients ;;
        ssh-client:alpine) echo openssh-client-default ;;
        ssh-keygen:alpine) echo openssh-keygen ;;
        *) echo "$1" ;;
    esac
}
package_present() {
    local logical="$1" pkg
    pkg="$(package_name "$logical")"
    case "$logical" in
        python3) python_ok;return ;;
        ssh-client) command -v ssh >/dev/null 2>&1 && command -v ssh-add >/dev/null 2>&1 && command -v ssh-agent >/dev/null 2>&1;return ;;
        ssh-keygen) command -v ssh-keygen >/dev/null 2>&1;return ;;
        curl|tar|unzip|gum|shellcheck|shfmt|podman|crun|git|cmake|make|c++|zstd|awk|grep|sed|tee|xargs) command -v "$logical" >/dev/null 2>&1 && return 0 ;;
    esac
    # Certificates have no universal executable; verify the native package.
    case "$FAMILY" in
        arch) command -v pacman >/dev/null && pacman -Q "$pkg" >/dev/null 2>&1 ;;
        debian) command -v dpkg-query >/dev/null && [[ "$(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true)" == 'install ok installed' ]] ;;
        fedora|rhel|opensuse) command -v rpm >/dev/null && rpm -q "$pkg" >/dev/null 2>&1 ;;
        alpine) command -v apk >/dev/null && apk info -e "$pkg" >/dev/null 2>&1 ;;
    esac
}
package_available() {
    local pkg="$1" output
    command -v "$MANAGER" >/dev/null 2>&1 || return 1
    case "$FAMILY" in
        arch) output="$(pacman -Si "$pkg" 2>/dev/null)" || return 1
              [[ "$output" =~ (^|$'\n')Name[[:space:]]*:[[:space:]]*$pkg($|$'\n') ]] ;;
        debian) output="$(apt-cache show "$pkg" 2>/dev/null)" || return 1
                grep -Fxq "Package: $pkg" <<< "$output" ;;
        fedora|rhel) output="$(dnf -q --cacheonly info --available "$pkg" 2>/dev/null)" || return 1
                     grep -Eq "^Name[[:space:]]*:[[:space:]]*${pkg}[[:space:]]*$" <<< "$output" ;;
        opensuse) output="$(zypper --non-interactive --no-refresh info "$pkg" 2>/dev/null)" || return 1
                   grep -Eq "^Name[[:space:]]*:[[:space:]]*${pkg}[[:space:]]*$" <<< "$output" ;;
        alpine) output="$(apk search -x "$pkg" 2>/dev/null)" || return 1
                grep -Eq "^${pkg}(-[0-9]|$)" <<< "$output" ;;
    esac
}

# A normal interactive prerequisite install prepares Gum BEFORE the wizard.
# Read-only check always reports Gum; automated preflight uses --without-ui.
if [[ "$WITH_UI" == 0 ]]; then
    if [[ "$ACTION" == check || ( -t 0 && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ) ]]; then WITH_UI=1; fi
fi
wanted=(python3 curl tar unzip ca-certificates)
if (( RUNTIME_ONLY )); then wanted=(python3); fi
if (( WITH_AI_BUILD )); then
    wanted+=(git cmake make c++)
    if (( RUNTIME_ONLY )); then wanted+=(ca-certificates); fi
fi
if (( WITH_OLLAMA )); then wanted+=(curl tar zstd ca-certificates awk grep sed tee xargs); fi
if (( WITH_GIT && ! WITH_AI_BUILD )); then wanted+=(git); fi
if (( WITH_SSH )); then wanted+=(ssh-client ssh-keygen); fi
if (( WITH_UI == 1 )); then wanted+=(gum); fi
if (( WITH_VALIDATION )); then wanted+=(shellcheck shfmt); fi
if (( WITH_LERD )); then
    if [[ "$FAMILY" == alpine || ! -d /run/systemd/system ]]; then
        printf 'Lerd prerequisites require a compatible systemd host (Alpine/OpenRC and containers without systemd are not eligible).\n' >&2
        exit 3
    fi
    wanted+=(podman crun)
fi
# Refuse a blocked installation before repository clients run: DNF5 may create
# user state even for --cacheonly queries. Installed prerequisites remain a no-op.
if (( READONLY_HOST )) && [[ "$ACTION" == install && "$DRY_RUN" == 0 ]]; then
    for name in "${wanted[@]}"; do
        if ! package_present "$name"; then
            printf 'Prerequisite installation blocked on this planning-only host.\n' >&2
            exit 3
        fi
    done
fi
missing=() unavailable=() required_unavailable=() optional_unavailable=()
index=0
for name in "${wanted[@]}"; do
    index=$((index+1))
    if [[ -t 2 ]]; then printf '[prerequisites %d/%d] Checking %s ...\r' "$index" "${#wanted[@]}" "$name" >&2; fi
    if package_present "$name"; then
        printf '  [installed] %-18s\n' "$name"
    else
        pkg="$(package_name "$name")"
        if package_available "$pkg"; then
            printf '  [available] %-18s (%s)\n' "$name" "$pkg"
            if [[ " ${missing[*]} " != *" $pkg "* ]]; then missing+=("$pkg"); fi
        else
            printf '  [unavailable] %-18s (repository metadata missing or unsupported)\n' "$name"
            unavailable+=("$name")
            case "$name" in gum|shellcheck|shfmt|crun) optional_unavailable+=("$name") ;; *) required_unavailable+=("$name") ;; esac
        fi
    fi
done
if [[ -t 2 ]]; then printf '\033[2K\r' >&2; fi
printf 'Summary: missing=%d unavailable=%d (required=%d optional=%d)\n' "${#missing[@]}" "${#unavailable[@]}" "${#required_unavailable[@]}" "${#optional_unavailable[@]}"
if [[ "$ACTION" == check || "$DRY_RUN" == 1 ]]; then
    if [[ "$DRY_RUN" == 1 && ${#missing[@]} -gt 0 ]]; then
        printf 'Would install via %s: %s\n' "$MANAGER" "${missing[*]}"
    fi
    exit 0
fi
if (( READONLY_HOST && (${#missing[@]} > 0 || ${#required_unavailable[@]} > 0) )); then
    printf 'Prerequisite installation blocked on this planning-only host.\n' >&2
    exit 3
fi
if (( ${#missing[@]} == 0 )); then
    if (( ${#required_unavailable[@]} > 0 )); then exit 5; fi
    exit 0
fi
if (( YES == 0 )); then
    if (( NONINTERACTIVE )) || [[ ! -t 0 ]]; then
        printf 'Installation needs --yes in noninteractive mode.\n' >&2; exit 4
    fi
    read -r -p "Install ${#missing[@]} prerequisites from existing $MANAGER repositories? [y/N] " reply
    case "$reply" in y|Y|yes|YES) ;; *) exit 4 ;; esac
fi
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'sudo is required for privileged installation; install it through a trusted system administrator.\n' >&2; exit 3
    fi
    PRIV=(sudo)
else
    PRIV=()
fi
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/automation-toolkit"
for part in "$HOME/.local" "$HOME/.local/state" "$STATE"; do
    if [[ -L "$part" ]]; then printf 'Refusing symlinked state directory component: %s\n' "$part" >&2; exit 3; fi
done
mkdir -p -m 700 -- "$STATE"
if ! mkdir -m 700 "$STATE/.prerequisite-lock" 2>/dev/null; then
    printf 'Prerequisite install already active (or stale lock): %s/.prerequisite-lock\n' "$STATE" >&2; exit 75
fi
trap 'rmdir -- "$STATE/.prerequisite-lock" 2>/dev/null || true' EXIT
case "$FAMILY" in
    arch) cmd=(pacman -S --needed --noconfirm) ;;
    debian) cmd=(apt-get install -y --no-install-recommends) ;;
    fedora|rhel) cmd=(dnf install -y) ;;
    opensuse) cmd=(zypper --non-interactive install) ;;
    alpine) cmd=(apk add) ;;
esac
printf 'Installing from native configured repositories: %s\n' "${missing[*]}"
"${PRIV[@]}" "${cmd[@]}" "${missing[@]}"
failed=0
for name in "${wanted[@]}"; do
    case " ${optional_unavailable[*]} " in *" $name "*) continue ;; esac
    if ! package_present "$name"; then
        printf 'Post-install verification failed: %s\n' "$name" >&2; failed=1
    fi
done
if (( failed )); then exit 1; fi
if (( ${#required_unavailable[@]} > 0 )); then exit 5; fi
printf 'Prerequisites ready.\n'
