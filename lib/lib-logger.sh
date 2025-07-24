#!/usr/bin/env bash

# ==== Library: lib-logger.sh ====
# Modular, colorized, rotating logger for bash automation scripts

# --- Configurable Defaults ---
LOGDIR="${LOGDIR:-$HOME/logs}"
LOG_MAX_SIZE="${LOG_MAX_SIZE:-1048576}"   # 1MB default
LOG_LEVEL="${LOG_LEVEL:-INFO}"            # DEBUG, INFO, WARN, ERROR
KEEP_LOGS="${KEEP_LOGS:-5}"               # How many old logs to keep

# --- Setup Log Directory ---
if [[ ! -d "$LOGDIR" ]]; then
    mkdir -p "$LOGDIR" || { echo "✖ Failed to create log directory: $LOGDIR" >&2; exit 1; }
fi

# --- Get Caller Script Name, Safe for Sourcing/Exec ---
get_script_name() {
    local src
    # BASH_SOURCE[1] = parent, [0] = this lib; fallback to $0
    if [[ -n "${BASH_SOURCE[1]:-}" ]]; then
        src="${BASH_SOURCE[1]}"
    elif [[ -n "${0:-}" ]]; then
        src="$0"
    else
        src="unknown"
    fi
    basename "${src%.*}"
}
CALLER_NAME="${CALLER_NAME:-$(get_script_name)}"
LOGFILE="${LOGFILE:-$LOGDIR/${CALLER_NAME}.log}"

# --- Colors (NO_COLOR=1 disables, or if not a TTY) ---
if [[ -t 1 && "${NO_COLOR:-0}" != "1" ]]; then
    BLUE='\033[1;34m'
    GREEN='\033[1;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    BLUE=''; GREEN=''; YELLOW=''; RED=''; NC=''
fi

# --- Timestamp ---
timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# --- Log Rotation ---
if [[ -f "$LOGFILE" && $(stat -c%s "$LOGFILE") -ge $LOG_MAX_SIZE ]]; then
    mv "$LOGFILE" "$LOGFILE.$(date '+%Y%m%d%H%M%S')"
fi

# --- Log Cleanup (keep only N recent logs) ---
if [[ -n "$KEEP_LOGS" && "$KEEP_LOGS" =~ ^[0-9]+$ ]]; then
    logs=( "$LOGDIR/${CALLER_NAME}.log."* )
    if [[ ${#logs[@]} -gt $KEEP_LOGS ]]; then
        to_delete=( "${logs[@]:0:${#logs[@]}-$KEEP_LOGS}" )
        for oldlog in "${to_delete[@]}"; do rm -f "$oldlog"; done
    fi
fi

# --- Ensure log file is writable ---
if ! touch "$LOGFILE" &>/dev/null; then
    echo "✖ Cannot write to log file: $LOGFILE" >&2
    exit 1
fi

# --- Level Filter ---
log_level_value() {
    case "$1" in
        DEBUG) echo 0;;
        INFO)  echo 1;;
        WARN)  echo 2;;
        ERROR) echo 3;;
        *)     echo 1;;
    esac
}
CURRENT_LEVEL=$(log_level_value "$LOG_LEVEL")

should_log() {
    local msg_level=$(log_level_value "$1")
    [[ $msg_level -ge $CURRENT_LEVEL ]] && return 0 || return 1
}

# --- Logger Functions ---
log() {
    should_log INFO || return
    echo -e "$(timestamp) ${BLUE}➤ $*${NC}" | tee -a "$LOGFILE"
}
ok() {
    should_log INFO || return
    echo -e "$(timestamp) ${GREEN}✔ $*${NC}" | tee -a "$LOGFILE"
}
warn() {
    should_log WARN || return
    echo -e "$(timestamp) ${YELLOW}⚠ $*${NC}" | tee -a "$LOGFILE" >&2
}
fail() {
    should_log ERROR || return
    echo -e "$(timestamp) ${RED}✖ $*${NC}" | tee -a "$LOGFILE" >&2
    exit 1
}
section() {
    should_log INFO || return
    echo -e "\n$(timestamp) ${BLUE}== $* ==${NC}" | tee -a "$LOGFILE"
}

# --- Semantic Aliases ---
log_success() { ok "$@"; }
log_error()   { fail "$@"; }

# --- Debug Helper ---
debug() {
    if should_log DEBUG; then
        echo -e "$(timestamp) ${YELLOW}[DEBUG] $*${NC}" | tee -a "$LOGFILE"
    fi
}

# --- Context Helper (optional) ---
log_with_context() {
    local level="$1"; shift
    local ctx="${FUNCNAME[1]:-main}($CALLER_NAME:$$)"
    case "$level" in
        INFO)  log   "[$ctx] $*";;
        WARN)  warn  "[$ctx] $*";;
        ERROR) fail  "[$ctx] $*";;
        DEBUG) debug "[$ctx] $*";;
        *)     log   "[$ctx] $*";;
    esac
}
