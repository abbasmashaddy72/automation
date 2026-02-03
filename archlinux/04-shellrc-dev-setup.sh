#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 04-shellrc-dev-setup.sh
#
# Purpose
# -------
# Configure developer-friendly shell RC blocks for Fish or Zsh:
# - Adds Composer global bin to PATH (Fish/Zsh)
# - Adds $HOME/bin to PATH (for phpv and other personal tools)
# - Adds helpful aliases + functions (artisan, vbin, etc.)
# - Enables a system info banner on every new interactive terminal:
#     * If fastfetch exists -> auto enable (no prompts)
#     * Else if neofetch exists -> auto enable (no prompts)
#     * Else -> asks once to install fastfetch (visible prompt)
# - Fixes broken Fish config from older bad injections:
#     * Removes legacy duplicate sections
#     * Removes timestamp junk lines
# - Disables Fish greeting (“Welcome to fish…”)
#
# Safety / Reliability
# --------------------
# - Uses BEGIN/END markers for clean idempotent updates
# - Backs up modified files
# - Tracks backups/state for --uninstall rollback
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./04-shellrc-dev-setup.sh
#   ./04-shellrc-dev-setup.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() {
    echo "❌ Error on line $1 while running: $2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Bootstrap libs
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
section "⚡️ Dev Shell RC Setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Flags / state dir (for uninstall + backups)
### ─────────────────────────────────────────────────────────────────────────
DO_UNINSTALL="n"
for arg in "$@"; do
    case "$arg" in
        --uninstall) DO_UNINSTALL="y" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0              Apply dev shell RC configuration (Fish/Zsh)
  $0 --uninstall  Restore previous config from backups (best-effort)

State directory:
  /var/lib/arch-dev-setup/04-shellrc-dev-setup/
EOF
            exit 0
        ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
        ;;
    esac
done

STATE_DIR="/var/lib/arch-dev-setup/04-shellrc-dev-setup"
BACKUP_DIR="$STATE_DIR/backups"
STATE_LAST_FISH_BACKUP="$STATE_DIR/last-fish-backup.path"
STATE_LAST_ZSH_BACKUP="$STATE_DIR/last-zsh-backup.path"

sudo mkdir -p "$BACKUP_DIR" >/dev/null 2>&1 || true

### ─────────────────────────────────────────────────────────────────────────
### Helpers
### ─────────────────────────────────────────────────────────────────────────
trim_ws() {
    local s="${1:-}"
    s="$(printf '%s' "$s" | sed -e 's/^[[:space:]]\+//' -e 's/[[:space:]]\+$//')"
    printf '%s' "$s"
}

prompt_yn() {
    # ALWAYS visible prompt using /dev/tty (works even if output is redirected)
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply=""
    
    while true; do
        if [[ "$default" == "y" ]]; then
            printf "%s [Y/n]: " "$prompt" >/dev/tty
            read -r reply </dev/tty || reply=""
            reply="${reply:-y}"
        else
            printf "%s [y/N]: " "$prompt" >/dev/tty
            read -r reply </dev/tty || reply=""
            reply="${reply:-n}"
        fi
        
        case "${reply,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." >/dev/tty ;;
        esac
    done
}

require_sudo() {
    log "🔐 Sudo required..."
    sudo -v || fail "Failed to authenticate sudo."
}

pacman_has_pkg() {
    local pkg
    pkg="$(trim_ws "${1:-}")"
    [[ -n "$pkg" ]] || return 1
    pacman -Si "$pkg" &>/dev/null
}

install_pkg_if_needed() {
    # Installs a pacman package only if it's available and not already installed.
    local pkg
    pkg="$(trim_ws "${1:-}")"
    [[ -n "$pkg" ]] || return 1
    
    if pacman -Qi "$pkg" &>/dev/null; then
        return 0
    fi
    
    pacman_has_pkg "$pkg" || return 1
    require_sudo
    sudo pacman -S --noconfirm --needed "$pkg" >/dev/null
}

backup_file() {
    # Creates a timestamped backup and records "last backup" path for uninstall.
    local file="$1"
    local tag="$2"
    [[ -f "$file" ]] || { touch "$file"; }
    
    local ts backup
    ts="$(date +%Y%m%d%H%M%S)"
    backup="$BACKUP_DIR/${tag}.backup.$ts"
    
    cp -a "$file" "$backup"
    ok "🔁 Backup created: $backup"
    
    if [[ "$tag" == "fish" ]]; then
        echo "$backup" | sudo tee "$STATE_LAST_FISH_BACKUP" >/dev/null
    else
        echo "$backup" | sudo tee "$STATE_LAST_ZSH_BACKUP" >/dev/null
    fi
}

restore_from_last_backup() {
    # restore_from_last_backup <state_file> <target_file>
    local state_file="$1"
    local target_file="$2"
    
    if [[ ! -f "$state_file" ]]; then
        warn "No backup state file found: $state_file"
        return 1
    fi
    
    local backup
    backup="$(sudo cat "$state_file" 2>/dev/null || true)"
    
    if [[ -z "$backup" || ! -f "$backup" ]]; then
        warn "Recorded backup missing/invalid: $backup"
        return 1
    fi
    
    cp -a "$backup" "$target_file"
    ok "Restored $target_file from $backup"
    return 0
}

# Remove blocks between markers (inclusive)
remove_block_range() {
    local file="$1"
    local begin="$2"
    local end="$3"
    
    grep -qF "$begin" "$file" || return 0
    
    sed -i "/$(printf '%s' "$begin" | sed 's/[\/&]/\\&/g')/,/$(printf '%s' "$end" | sed 's/[\/&]/\\&/g')/d" "$file"
}

# Remove legacy junk from earlier broken injections:
# - timestamped logger output inside config files
# - duplicated legacy headers without reliable END markers
sanitize_legacy_fish_junk() {
    local file="$1"
    
    # Remove any lines that look like timestamp logger output
    sed -i -E '/^[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]][0-9]{2}:[0-9]{2}:[0-9]{2}[[:space:]]/d' "$file"
    
    # Remove duplicated legacy sections that start with these headers (no reliable END).
    # Deletes from header to next blank line. Repeats for common old headers.
    for hdr in \
    "# === CUSTOM DEV SHELL SETUP ===" \
    "# === PHPV PATH SETUP ===" \
    "# === FETCH TOOL ON TERMINAL START ==="
    do
        sed -i "/$(printf '%s' "$hdr" | sed 's/[\/&]/\\&/g')/{:a;N;/\n[[:space:]]*$/!ba;d}" "$file" 2>/dev/null || true
    done
}

### ─────────────────────────────────────────────────────────────────────────
### Shell detection
### ─────────────────────────────────────────────────────────────────────────
CURRENT_SHELL="$(basename "${SHELL:-}")"
log "Detected current shell: ${CURRENT_SHELL:-unknown}"

SHELL_TYPE="none"
if [[ "$CURRENT_SHELL" == "fish" ]]; then
    SHELL_TYPE="fish"
    elif [[ "$CURRENT_SHELL" == "zsh" ]]; then
    SHELL_TYPE="zsh"
fi

choose_shell_menu() {
  cat >/dev/tty <<'EOF'

This script supports only: zsh or fish.
Pick what you want to configure:
  1) Zsh
  2) Fish
  3) Exit

EOF
    while true; do
        printf "Choose [1-3]: " >/dev/tty
        read -r choice </dev/tty || choice=""
        case "${choice:-}" in
            1) printf '%s\n' "zsh"; return 0 ;;
            2) printf '%s\n' "fish"; return 0 ;;
            3) printf '%s\n' "exit"; return 0 ;;
            *) echo "Pick 1, 2, or 3." >/dev/tty ;;
        esac
    done
}

ensure_shell_installed() {
    local shell_name="$1"
    
    if command -v "$shell_name" &>/dev/null; then
        ok "✅ $shell_name is installed."
        return 0
    fi
    
    warn "⚠️ $shell_name is not installed."
    if prompt_yn "Install $shell_name now (pacman)?" "y"; then
        install_pkg_if_needed "$shell_name" || fail "Failed to install $shell_name."
        ok "✅ Installed $shell_name."
    else
        fail "Cannot continue without $shell_name installed."
    fi
}

offer_set_default_shell() {
    local shell_name="$1"
    local shell_path
    shell_path="$(command -v "$shell_name" || true)"
    [[ -n "$shell_path" ]] || return 0
    
    if [[ "${SHELL:-}" == "$shell_path" ]]; then
        ok "Default shell already set to $shell_name ($shell_path)."
        return 0
    fi
    
    if prompt_yn "Set $shell_name as your default login shell (chsh)?" "n"; then
        if chsh -s "$shell_path"; then
            ok "✅ Default shell updated."
        else
            warn "Failed to change default shell (chsh)."
        fi
    fi
}

offer_switch_current_session_now() {
    local shell_name="$1"
    if [[ "$(basename "${SHELL:-}")" == "$shell_name" ]]; then
        ok "You are already running $shell_name in this terminal."
        return 0
    fi
    
    if prompt_yn "Switch THIS terminal to $shell_name now (exec; no logout)?" "y"; then
        warn "Switching shell now. Close this tab to revert."
        exec "$shell_name"
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Fetch tool selection (NO MENU if fastfetch exists)
### ─────────────────────────────────────────────────────────────────────────
FETCH_TOOL="skip"

select_fetch_tool() {
    if command -v fastfetch &>/dev/null; then
        FETCH_TOOL="fastfetch"
        ok "✅ fastfetch detected → will auto-run on every NEW terminal."
        return 0
    fi
    
    if command -v neofetch &>/dev/null; then
        FETCH_TOOL="neofetch"
        ok "✅ neofetch detected → will auto-run on every NEW terminal."
        return 0
    fi
    
    # Neither installed: ask once, visible
    if prompt_yn "fastfetch/neofetch not found. Install fastfetch and enable banner?" "y"; then
        if pacman_has_pkg fastfetch; then
            install_pkg_if_needed fastfetch || { warn "fastfetch install failed. Banner disabled."; FETCH_TOOL="skip"; return 0; }
            FETCH_TOOL="fastfetch"
            ok "✅ Installed fastfetch → banner enabled."
            return 0
        fi
        warn "fastfetch not available via pacman on this system. Banner disabled."
    fi
    
    FETCH_TOOL="skip"
}

### ─────────────────────────────────────────────────────────────────────────
### Managed config markers (idempotent edits)
### ─────────────────────────────────────────────────────────────────────────
FISH_BEGIN_FETCH="# === BEGIN FETCH TOOL ON TERMINAL START ==="
FISH_END_FETCH="# === END FETCH TOOL ON TERMINAL START ==="
FISH_BEGIN_DEV="# === BEGIN CUSTOM DEV SHELL SETUP ==="
FISH_END_DEV="# === END CUSTOM DEV SHELL SETUP ==="
FISH_BEGIN_PHPV="# === BEGIN PHPV PATH SETUP ==="
FISH_END_PHPV="# === END PHPV PATH SETUP ==="
FISH_BEGIN_GREETING="# === BEGIN FISH GREETING DISABLE ==="
FISH_END_GREETING="# === END FISH GREETING DISABLE ==="

ZSH_BEGIN_FETCH="# === BEGIN FETCH TOOL ON TERMINAL START ==="
ZSH_END_FETCH="# === END FETCH TOOL ON TERMINAL START ==="
ZSH_BEGIN_DEV="# === BEGIN CUSTOM DEV SHELL SETUP ==="
ZSH_END_DEV="# === END CUSTOM DEV SHELL SETUP ==="
ZSH_BEGIN_PHPV="# === BEGIN PHPV PATH SETUP ==="
ZSH_END_PHPV="# === END PHPV PATH SETUP ==="

### ─────────────────────────────────────────────────────────────────────────
### Fish blocks
### ─────────────────────────────────────────────────────────────────────────
fish_block_disable_greeting() {
  cat <<EOF

$FISH_BEGIN_GREETING
set -g fish_greeting ""
$FISH_END_GREETING
EOF
}

fish_block_fetch() {
    local tool="$1"
  cat <<EOF

$FISH_BEGIN_FETCH
if status is-interactive
    if not set -q __FETCH_RAN
        set -gx __FETCH_RAN 1
        if type -q $tool
            $tool
        end
    end
end
$FISH_END_FETCH
EOF
}

fish_block_dev_phpv() {
  cat <<EOF

# Keep everything inside interactive sessions to avoid polluting non-interactive runs
if status is-interactive

$FISH_BEGIN_DEV
if test -d \$HOME/.config/composer/vendor/bin
    set -gx PATH \$HOME/.config/composer/vendor/bin \$PATH
end

alias clean-npm 'rm -rf node_modules package-lock.json; and npm install'
alias clean-composer 'rm -rf vendor composer.lock; and composer install'

function vbin
    set bin ./vendor/bin/\$argv[1]
    set argv (string trim -- \$argv[2..-1])
    if test -x \$bin
        \$bin \$argv
    else
        echo "🔴 '\$argv[1]' not found or not executable in vendor/bin"
    end
end

function artisan
    if test -f artisan
        php artisan \$argv
    else
        echo "🔴 artisan not found in current directory"
    end
end

alias pint 'vbin pint'
alias sail 'vbin sail'
alias fixer 'vbin php-cs-fixer'
alias pest 'vbin pest'
alias phpunit 'vbin phpunit'
$FISH_END_DEV

$FISH_BEGIN_PHPV
if test -d \$HOME/bin
    if type -q fish_add_path
        fish_add_path -g \$HOME/bin
    else
        set -gx PATH \$HOME/bin \$PATH
    end
end
$FISH_END_PHPV

end
EOF
}

apply_fish_config() {
    local fishrc="$HOME/.config/fish/config.fish"
    mkdir -p "$(dirname "$fishrc")"
    touch "$fishrc"
    
    backup_file "$fishrc" "fish"
    
    # Remove managed blocks first
    remove_block_range "$fishrc" "$FISH_BEGIN_FETCH" "$FISH_END_FETCH"
    remove_block_range "$fishrc" "$FISH_BEGIN_DEV" "$FISH_END_DEV"
    remove_block_range "$fishrc" "$FISH_BEGIN_PHPV" "$FISH_END_PHPV"
    remove_block_range "$fishrc" "$FISH_BEGIN_GREETING" "$FISH_END_GREETING"
    
    # Clean legacy junk (timestamps, duplicates, etc.)
    sanitize_legacy_fish_junk "$fishrc"
    
    # Append clean blocks
    fish_block_disable_greeting >> "$fishrc"
    if [[ "$FETCH_TOOL" != "skip" ]]; then
        fish_block_fetch "$FETCH_TOOL" >> "$fishrc"
    fi
    fish_block_dev_phpv >> "$fishrc"
    
    ok "✅ Updated: $fishrc"
    warn "Apply immediately (no logout): source $fishrc"
}

### ─────────────────────────────────────────────────────────────────────────
### Zsh blocks
### ─────────────────────────────────────────────────────────────────────────
apply_zsh_config() {
    local zshrc="$HOME/.zshrc"
    touch "$zshrc"
    
    backup_file "$zshrc" "zsh"
    
    # Remove old managed blocks
    sed -i "/^${ZSH_BEGIN_FETCH}$/,/^${ZSH_END_FETCH}$/d" "$zshrc" 2>/dev/null || true
    sed -i "/^${ZSH_BEGIN_DEV}$/,/^${ZSH_END_DEV}$/d" "$zshrc" 2>/dev/null || true
    sed -i "/^${ZSH_BEGIN_PHPV}$/,/^${ZSH_END_PHPV}$/d" "$zshrc" 2>/dev/null || true
    
    {
        echo ""
        if [[ "$FETCH_TOOL" != "skip" ]]; then
      cat <<EOF
$ZSH_BEGIN_FETCH
if [[ -o interactive ]]; then
  if [[ -z "\${__FETCH_RAN:-}" ]]; then
    __FETCH_RAN=1
    if command -v $FETCH_TOOL >/dev/null 2>&1; then
      $FETCH_TOOL
    fi
  fi
fi
$ZSH_END_FETCH
EOF
        fi
        
    cat <<'EOF'

# === BEGIN CUSTOM DEV SHELL SETUP ===
if [[ -d "$HOME/.config/composer/vendor/bin" ]]; then
  export PATH="$HOME/.config/composer/vendor/bin:$PATH"
fi

alias clean-npm='rm -rf node_modules package-lock.json && npm install'
alias clean-composer='rm -rf vendor composer.lock && composer install'

vbin() {
  local bin="./vendor/bin/$1"
  shift
  if [[ -x "$bin" ]]; then
    "$bin" "$@"
  else
    echo "🔴 '$1' not found or not executable in vendor/bin"
  fi
}

artisan() {
  if [[ -f artisan ]]; then
    php artisan "$@"
  else
    echo "🔴 artisan not found in current directory"
  fi
}

alias pint='vbin pint'
alias sail='vbin sail'
alias fixer='vbin php-cs-fixer'
alias pest='vbin pest'
alias phpunit='vbin phpunit'
# === END CUSTOM DEV SHELL SETUP ===

# === BEGIN PHPV PATH SETUP ===
if [[ -d "$HOME/bin" ]]; then
  export PATH="$HOME/bin:$PATH"
fi
# === END PHPV PATH SETUP ===
EOF
    } >> "$zshrc"
    
    ok "✅ Updated: $zshrc"
    warn "Apply immediately (no logout): source $zshrc"
}

### ─────────────────────────────────────────────────────────────────────────
### Banner preview (run once now)
### ─────────────────────────────────────────────────────────────────────────
run_fetch_now() {
    [[ "$FETCH_TOOL" == "skip" ]] && return 0
    
    if command -v "$FETCH_TOOL" &>/dev/null; then
        section "🖥️ Running $FETCH_TOOL now (preview)"
        "$FETCH_TOOL" || true
    fi
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall (rollback) mode
### ─────────────────────────────────────────────────────────────────────────
run_uninstall() {
    section "🧯 Uninstall: restoring shell RC backups (best-effort)"
    
    local fishrc="$HOME/.config/fish/config.fish"
    local zshrc="$HOME/.zshrc"
    
    if [[ -f "$STATE_LAST_FISH_BACKUP" ]]; then
        restore_from_last_backup "$STATE_LAST_FISH_BACKUP" "$fishrc" || true
    else
        warn "No fish backup state found; fish config unchanged."
    fi
    
    if [[ -f "$STATE_LAST_ZSH_BACKUP" ]]; then
        restore_from_last_backup "$STATE_LAST_ZSH_BACKUP" "$zshrc" || true
    else
        warn "No zsh backup state found; zsh config unchanged."
    fi
    
    ok "✅ Uninstall complete."
}

### ─────────────────────────────────────────────────────────────────────────
### Main flow
### ─────────────────────────────────────────────────────────────────────────
if [[ "$DO_UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

if [[ "$CURRENT_SHELL" == "fish" ]]; then
    SHELL_TYPE="fish"
    elif [[ "$CURRENT_SHELL" == "zsh" ]]; then
    SHELL_TYPE="zsh"
else
    warn "Detected shell '$CURRENT_SHELL' is not supported."
    chosen="$(choose_shell_menu)"
    [[ "$chosen" == "exit" ]] && { warn "Exiting without changes."; exit 0; }
    SHELL_TYPE="$chosen"
fi

ensure_shell_installed "$SHELL_TYPE"

# Decide banner tool (auto fastfetch if present)
select_fetch_tool

# Apply configs
if [[ "$SHELL_TYPE" == "fish" ]]; then
    section "🐟 Fish selected: updating config.fish"
    apply_fish_config
else
    section "💤 Zsh selected: updating .zshrc"
    apply_zsh_config
fi

offer_set_default_shell "$SHELL_TYPE"

# Run banner now (no need to open a new terminal just to see it)
run_fetch_now

# Optional: switch current shell
offer_switch_current_session_now "$SHELL_TYPE"

ok "🚀 Developer shell RC setup complete for $SHELL_TYPE!"
exit 0
