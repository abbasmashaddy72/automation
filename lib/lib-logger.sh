#!/bin/bash

# === Setup Log Directory ===
LOGDIR="${LOGDIR:-$HOME/logs}"
if [[ ! -d "$LOGDIR" ]]; then
    mkdir -p "$LOGDIR" || { echo "✖ Failed to create log directory: $LOGDIR" >&2; exit 1; }
fi

# === Auto-determine log file unless explicitly set ===
if [[ -z "${LOGFILE:-}" ]]; then
    # If BASH_SOURCE[1] not set, default to 'script'
    if [[ ${#BASH_SOURCE[@]} -gt 1 && -n "${BASH_SOURCE[1]}" ]]; then
        CALLER_NAME="$(basename "${BASH_SOURCE[1]%.*}")"
    else
        CALLER_NAME="script"
    fi
    LOGFILE="$LOGDIR/${CALLER_NAME}.log"
fi

# === Colors (override with NO_COLOR=1 for CI/non-TTY) ===
if [[ -t 1 && "${NO_COLOR:-0}" != "1" ]]; then
    BLUE='\033[1;34m'
    GREEN='\033[1;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    BLUE=''; GREEN=''; YELLOW=''; RED=''; NC=''
fi

# === Verbosity Control ===
VERBOSE="${VERBOSE:-1}"   # Set VERBOSE=0 for silent except fails

# === Timestamp ===
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# === Log rotation (before any writes) ===
LOG_MAX_SIZE=${LOG_MAX_SIZE:-1048576}
if [[ -f "$LOGFILE" && $(stat -c%s "$LOGFILE") -ge $LOG_MAX_SIZE ]]; then
    mv "$LOGFILE" "$LOGFILE.$(date '+%Y%m%d%H%M%S')"
fi

# === Ensure log file is writable ===
if ! touch "$LOGFILE" &>/dev/null; then
    echo "✖ Cannot write to log file: $LOGFILE" >&2
    exit 1
fi

# === Logger Functions ===
log() {
    [[ "$VERBOSE" -ge 1 ]] && echo -e "$(timestamp) ${BLUE}➤ $*${NC}" | tee -a "$LOGFILE"
}
ok() {
    [[ "$VERBOSE" -ge 1 ]] && echo -e "$(timestamp) ${GREEN}✔ $*${NC}" | tee -a "$LOGFILE"
}
warn() {
    echo -e "$(timestamp) ${YELLOW}⚠ $*${NC}" | tee -a "$LOGFILE" >&2
}
fail() {
    echo -e "$(timestamp) ${RED}✖ $*${NC}" | tee -a "$LOGFILE" >&2
    exit 1
}
section() {
    [[ "$VERBOSE" -ge 1 ]] && echo -e "\n$(timestamp) ${BLUE}== $* ==${NC}" | tee -a "$LOGFILE"
}

# === Semantic Aliases ===
log_success() { ok "$@"; }
log_error()   { fail "$@"; }

# === Debug Helper (prints always if DEBUG=1) ===
debug() {
    [[ "${DEBUG:-0}" == "1" ]] && echo -e "$(timestamp) ${YELLOW}[DEBUG] $*${NC}" | tee -a "$LOGFILE"
}
