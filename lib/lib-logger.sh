#!/bin/bash
# lib/lib-logger.sh

# === Setup Log Directory ===
LOGDIR="${LOGDIR:-$HOME/logs}"
mkdir -p "$LOGDIR"

# === Auto-determine log file unless explicitly set ===
if [[ -z "${LOGFILE:-}" ]]; then
    CALLER_NAME="$(basename "${BASH_SOURCE[1]%.*}")"
    LOGFILE="$LOGDIR/${CALLER_NAME}.log"
fi

# === Colors ===
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# === Timestamp ===
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# === Logger Functions ===
log()      { echo -e "$(timestamp) ${BLUE}➤ $1${NC}" | tee -a "$LOGFILE"; }
ok()       { echo -e "$(timestamp) ${GREEN}✔ $1${NC}" | tee -a "$LOGFILE"; }
warn()     { echo -e "$(timestamp) ${YELLOW}⚠ $1${NC}" | tee -a "$LOGFILE"; }
fail()     { echo -e "$(timestamp) ${RED}✖ $1${NC}" | tee -a "$LOGFILE"; exit 1; }
section()  { echo -e "\n$(timestamp) ${BLUE}== $1 ==${NC}" | tee -a "$LOGFILE"; }

# === Semantic Aliases (Optional Sugar) ===
log_success() { ok "$@"; }
log_error()   { fail "$@"; }
