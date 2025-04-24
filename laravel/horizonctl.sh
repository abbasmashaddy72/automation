#!/bin/bash

set -e

# === Defaults ===
RESTART=false
TERMINATE=false
WAIT_SECONDS=2
FORCE_MODE=false
REMOVE=false
STATUS_ONLY=false
ENVIRONMENT=""
PROJECT_ROOT=$(pwd)
USER=$(whoami)

# === Colors ===
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# === Help ===
show_help() {
    echo -e "${BLUE}Laravel Horizon Supervisor Helper${NC}"
    echo ""
    echo "Usage: ./horizonctl.sh [options]"
    echo ""
    echo "Options:"
    echo "  --path=/path/to/project     Path to Laravel project (resolves artisan + logs)"
    echo "  --env=staging               Add environment suffix to supervisor config"
    echo "  --remove                    Remove Supervisor config and stop Horizon"
    echo "  --status                    Show Horizon Supervisor status"
    echo "  --wait-seconds=5            Wait after supervisor update (default: 2)"
    echo "  --force                     Run non-interactively (no confirmations)"
    echo "  --restart                   Restart Horizon process"
    echo "  --terminate                 Terminate Horizon process (via Supervisor)"
    echo "  --help                      Show this help message"
    exit 0
}

# === Parse Args ===
for arg in "$@"; do
    case $arg in
    --restart) RESTART=true ;;
    --terminate) TERMINATE=true ;;
    --wait-seconds=*) WAIT_SECONDS="${arg#*=}" ;;
    --remove) REMOVE=true ;;
    --force) FORCE_MODE=true ;;
    --env=*) ENVIRONMENT="${arg#*=}" ;;
    --path=*) PROJECT_ROOT="${arg#*=}" ;;
    --status) STATUS_ONLY=true ;;
    --help) show_help ;;
    esac
done

# === Setup Vars ===
PROJECT_NAME=$(basename "$PROJECT_ROOT")
SUPERVISOR_SAFE_NAME=$(echo "$PROJECT_NAME" | tr -cd '[:alnum:]_')
[[ -n "$ENVIRONMENT" ]] && SUPERVISOR_SAFE_NAME="${SUPERVISOR_SAFE_NAME}_${ENVIRONMENT}"

ARTISAN_PATH="$PROJECT_ROOT/artisan"
LOGS_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOGS_DIR/horizon.log"
SUPERVISOR_DIR=$(sudo grep -Po '(?<=files = )[^ ]+' /etc/supervisord.conf 2>/dev/null | sed 's|/\*\.ini||')
SUPERVISOR_DIR=${SUPERVISOR_DIR:-"/etc/supervisord.d"}
SUPERVISOR_CONFIG="$SUPERVISOR_DIR/horizon_${SUPERVISOR_SAFE_NAME}.ini"

# === Check Root ===
[[ "$EUID" == 0 ]] && echo -e "${RED}❌ Do not run as root.${NC}" && exit 1

# === Status Only ===
if [[ "$STATUS_ONLY" == true ]]; then
    echo -e "${BLUE}📋 Horizon Status:${NC}"
    sudo supervisorctl status | grep "horizon_${SUPERVISOR_SAFE_NAME}" || echo -e "${RED}❌ Not running${NC}"
    exit 0
fi

# === Remove Mode ===
if [[ "$REMOVE" == true ]]; then
    echo -e "${YELLOW}🧹 Removing Horizon Supervisor config...${NC}"
    [ -f "$SUPERVISOR_CONFIG" ] && {
        sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || true
        sudo rm -f "$SUPERVISOR_CONFIG"
        sudo supervisorctl reread
        sudo supervisorctl update
        echo -e "${GREEN}✅ Removed horizon_${SUPERVISOR_SAFE_NAME}${NC}"
    } || echo -e "${BLUE}ℹ️ No config to remove.${NC}"
    exit 0
fi

# === Terminate Mode ===
if [[ "$TERMINATE" == true ]]; then
    echo -e "${YELLOW}🛑 Stopping Horizon: horizon_${SUPERVISOR_SAFE_NAME}${NC}"
    sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || {
        echo -e "${RED}❌ Failed to stop Horizon.${NC}"
        exit 1
    }
    echo -e "${GREEN}✅ Horizon terminated successfully.${NC}"
    exit 0
fi

# === Restart Mode ===
if [[ "$RESTART" == true ]]; then
    echo -e "${YELLOW}🔁 Restarting Horizon: horizon_${SUPERVISOR_SAFE_NAME}${NC}"
    sudo supervisorctl restart "horizon_${SUPERVISOR_SAFE_NAME}" || {
        echo -e "${RED}❌ Failed to restart Horizon.${NC}"
        exit 1
    }
    echo -e "${GREEN}✅ Horizon restarted successfully.${NC}"
    exit 0
fi

# === Confirm ===
if [[ "$FORCE_MODE" == false ]]; then
    echo "⚙️  Configuring Laravel Horizon Supervisor:"
    echo "   📂 Project: $PROJECT_NAME"
    echo "   📍 Path: $PROJECT_ROOT"
    [[ -n "$ENVIRONMENT" ]] && echo "   🌐 Env: $ENVIRONMENT"
    read -p "❓ Continue? (y/N): " CONFIRM
    [[ ! "$CONFIRM" =~ ^[Yy]$ ]] && echo -e "${RED}🚫 Cancelled.${NC}" && exit 1
fi

# === Pre-checks ===
command -v composer >/dev/null || {
    echo -e "${RED}❌ Composer not found.${NC}"
    exit 1
}
command -v supervisorctl >/dev/null || {
    echo -e "${RED}❌ Supervisor not installed.${NC}"
    exit 1
}
[[ -f "$ARTISAN_PATH" ]] || {
    echo -e "${RED}❌ artisan not found at $ARTISAN_PATH${NC}"
    exit 1
}

if ! grep -q "laravel/horizon" "$PROJECT_ROOT/composer.json" 2>/dev/null && [ ! -d "$PROJECT_ROOT/vendor/laravel/horizon" ]; then
    echo -e "${RED}❌ Laravel Horizon not found in this project.${NC}"
    exit 1
fi

if ! sudo systemctl is-active --quiet supervisord; then
    echo -e "${YELLOW}⚠️  Starting Supervisor...${NC}"
    sudo systemctl start supervisord || {
        echo -e "${RED}❌ Failed to start Supervisor.${NC}"
        exit 1
    }
fi

# === Log Dir ===
mkdir -p "$LOGS_DIR"
touch "$LOG_FILE"
sudo chown "$USER:$USER" "$LOGS_DIR" "$LOG_FILE"
sudo chmod 755 "$LOGS_DIR"
sudo chmod 644 "$LOG_FILE"

# === Supervisor Dir ===
sudo mkdir -p "$SUPERVISOR_DIR"
sudo chown root:root "$SUPERVISOR_DIR"
sudo chmod 755 "$SUPERVISOR_DIR"

# === Handle Existing Config ===
if [ -f "$SUPERVISOR_CONFIG" ]; then
    if [[ "$FORCE_MODE" == true ]]; then
        echo -e "${YELLOW}⚙️  Overwriting existing config...${NC}"
        sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || true
        sudo rm -f "$SUPERVISOR_CONFIG"
    else
        echo -e "${YELLOW}⚠️ Config exists: $SUPERVISOR_CONFIG${NC}"
        read -p "❓ Overwrite? (y/N): " OVERWRITE
        [[ "$OVERWRITE" =~ ^[Yy]$ ]] && sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || exit 0
        sudo rm -f "$SUPERVISOR_CONFIG"
    fi
fi

# === Write Config ===
echo -e "${BLUE}📦 Writing Supervisor config...${NC}"
sudo tee "$SUPERVISOR_CONFIG" >/dev/null <<EOF
[program:horizon_${SUPERVISOR_SAFE_NAME}]
process_name=%(program_name)s
command=php $ARTISAN_PATH horizon
environment=HORIZON_PREFIX="${SUPERVISOR_SAFE_NAME}_horizon:"
autostart=true
autorestart=true
numprocs=1
redirect_stderr=true
stdout_logfile=$LOG_FILE
stopwaitsecs=3600
user=$USER
EOF

sudo chown root:root "$SUPERVISOR_CONFIG"
sudo chmod 644 "$SUPERVISOR_CONFIG"

# === Reload Supervisor ===
echo -e "${YELLOW}🔄 Reloading Supervisor...${NC}"
sudo supervisorctl reread
sudo supervisorctl update

echo -e "${BLUE}⏳ Waiting ${WAIT_SECONDS}s for Supervisor to register...${NC}"
sleep "$WAIT_SECONDS"

# === Start Horizon ===
if sudo supervisorctl status | grep -q "horizon_${SUPERVISOR_SAFE_NAME}.*RUNNING"; then
    echo -e "${GREEN}✅ Horizon is already running.${NC}"
else
    echo -e "${BLUE}🚀 Starting Horizon...${NC}"
    sudo supervisorctl start "horizon_${SUPERVISOR_SAFE_NAME}" || {
        echo -e "${RED}❌ Failed to start Horizon. Check logs: tail -f $LOG_FILE${NC}"
        exit 1
    }

    for i in {1..5}; do
        if sudo supervisorctl status | grep -q "horizon_${SUPERVISOR_SAFE_NAME}.*RUNNING"; then
            echo -e "${GREEN}✅ Horizon started successfully!${NC}"
            break
        fi
        echo -e "${YELLOW}⏳ Waiting for Horizon to start... ($i/5)${NC}"
        sleep 2
    done

    if ! sudo supervisorctl status | grep -q "horizon_${SUPERVISOR_SAFE_NAME}.*RUNNING"; then
        echo -e "${RED}❌ Horizon did not start. Logs: tail -f $LOG_FILE${NC}"
        exit 1
    fi
fi

# Final tips
echo ""
echo -e "${BLUE}📌 Horizon Management:${NC}"
echo -e "   ✅ Status:    ${GREEN}sudo supervisorctl status | grep 'horizon_${SUPERVISOR_SAFE_NAME}'${NC}"
echo -e "   🔄 Restart:   ${YELLOW}sudo supervisorctl restart horizon_${SUPERVISOR_SAFE_NAME}${NC}"
echo -e "   🛑 Stop:      ${RED}sudo supervisorctl stop horizon_${SUPERVISOR_SAFE_NAME}${NC}"
echo -e "   📜 Logs:      ${BLUE}tail -f $LOG_FILE${NC}"
