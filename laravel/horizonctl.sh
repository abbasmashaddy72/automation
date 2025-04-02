#!/bin/bash

set -e

# Defaults
WAIT_SECONDS=2
FORCE_MODE=false
REMOVE=false
STATUS_ONLY=false
ENVIRONMENT=""
PROJECT_ROOT=$(pwd)
USER=$(whoami)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No color

# Help
show_help() {
    echo -e "${BLUE}Laravel Horizon Supervisor Helper${NC}"
    echo ""
    echo "Usage:"
    echo "  ./horizonctl.sh [options]"
    echo ""
    echo "Options:"
    echo "  --path=/path/to/project     Path to Laravel project (resolves artisan + logs)"
    echo "  --env=staging               Add environment suffix to supervisor config"
    echo "  --remove                    Remove Supervisor config and stop Horizon"
    echo "  --status                    Show Horizon Supervisor status"
    echo "  --wait-seconds=5            Wait after supervisor update (default: 2)"
    echo "  --force                     Run non-interactively (no confirmations)"
    echo "  --help                      Show this help message"
    exit 0
}

# Parse args
for arg in "$@"; do
    case $arg in
    --wait-seconds=*)
        WAIT_SECONDS="${arg#*=}"
        shift
        ;;
    --remove)
        REMOVE=true
        shift
        ;;
    --force)
        FORCE_MODE=true
        shift
        ;;
    --env=*)
        ENVIRONMENT="${arg#*=}"
        shift
        ;;
    --path=*)
        PROJECT_ROOT="${arg#*=}"
        shift
        ;;
    --status)
        STATUS_ONLY=true
        shift
        ;;
    --help) show_help ;;
    esac
done

# Resolve project variables
PROJECT_NAME=$(basename "$PROJECT_ROOT")
SUPERVISOR_SAFE_NAME=$(echo "$PROJECT_NAME" | tr -cd '[:alnum:]_')
[[ -n "$ENVIRONMENT" ]] && SUPERVISOR_SAFE_NAME="${SUPERVISOR_SAFE_NAME}_${ENVIRONMENT}"

ARTISAN_PATH="$PROJECT_ROOT/artisan"
LOGS_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOGS_DIR/horizon.log"
SUPERVISOR_DIR=$(sudo grep -Po '(?<=files = )[^ ]+' /etc/supervisord.conf 2>/dev/null | sed 's|/\*\.ini||')
SUPERVISOR_DIR=${SUPERVISOR_DIR:-"/etc/supervisord.d"}
SUPERVISOR_CONFIG="$SUPERVISOR_DIR/horizon_${SUPERVISOR_SAFE_NAME}.ini"

# Check if running as root
if [[ "$EUID" == 0 ]]; then
    echo -e "${RED}❌ Do not run this script as root. Run as the app user (e.g. forge, deploy, etc).${NC}"
    exit 1
fi

# Status only
if [[ "$STATUS_ONLY" == true ]]; then
    echo -e "${BLUE}📋 Horizon Status:${NC}"
    sudo supervisorctl status | grep "horizon_${SUPERVISOR_SAFE_NAME}" || echo -e "${RED}❌ Not running${NC}"
    exit 0
fi

# Remove
if [[ "$REMOVE" == true ]]; then
    echo -e "${YELLOW}🧹 Removing Supervisor config...${NC}"
    if [ -f "$SUPERVISOR_CONFIG" ]; then
        sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || true
        sudo rm -f "$SUPERVISOR_CONFIG"
        sudo supervisorctl reread
        sudo supervisorctl update
        echo -e "${GREEN}✅ Removed horizon_${SUPERVISOR_SAFE_NAME}${NC}"
    else
        echo -e "${BLUE}ℹ️ No config found to remove.${NC}"
    fi
    exit 0
fi

# Confirm
if [[ "$FORCE_MODE" == false ]]; then
    echo "⚠️  Configuring Laravel Horizon Supervisor:"
    echo "   📂 Project: $PROJECT_NAME"
    echo "   📍 Path: $PROJECT_ROOT"
    [[ -n "$ENVIRONMENT" ]] && echo "   🌐 Env: $ENVIRONMENT"
    read -p "❓ Continue? (y/N): " CONFIRM
    [[ ! "$CONFIRM" =~ ^[Yy]$ ]] && echo -e "${RED}🚫 Cancelled.${NC}" && exit 1
else
    echo -e "${YELLOW}⚙️  Force mode: no confirmations.${NC}"
fi

# Dependency checks
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
    echo -e "${YELLOW}⚠️  Supervisor not running. Trying to start...${NC}"
    sudo systemctl start supervisord || {
        echo -e "${RED}❌ Failed to start Supervisor. Start manually.${NC}"
        exit 1
    }
fi

# Prepare logs
mkdir -p "$LOGS_DIR"
touch "$LOG_FILE"
sudo chown "$USER:$USER" "$LOGS_DIR" "$LOG_FILE"
sudo chmod 755 "$LOGS_DIR"
sudo chmod 644 "$LOG_FILE"

# Supervisor config dir
sudo mkdir -p "$SUPERVISOR_DIR"
sudo chown root:root "$SUPERVISOR_DIR"
sudo chmod 755 "$SUPERVISOR_DIR"

# Handle existing config
if [ -f "$SUPERVISOR_CONFIG" ]; then
    if [[ "$FORCE_MODE" == true ]]; then
        echo -e "${YELLOW}⚙️  Overwriting existing config...${NC}"
        sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || true
        sudo rm -f "$SUPERVISOR_CONFIG"
    else
        echo -e "${YELLOW}⚠️ Config exists: $SUPERVISOR_CONFIG${NC}"
        read -p "❓ Overwrite? (y/N): " OVERWRITE
        if [[ "$OVERWRITE" =~ ^[Yy]$ ]]; then
            sudo supervisorctl stop "horizon_${SUPERVISOR_SAFE_NAME}" || true
            sudo rm -f "$SUPERVISOR_CONFIG"
        else
            echo -e "${GREEN}✅ Skipped setup.${NC}"
            exit 0
        fi
    fi
fi

# Write config
echo -e "${BLUE}📦 Writing Supervisor config...${NC}"
sudo tee "$SUPERVISOR_CONFIG" >/dev/null <<EOF
[program:horizon_${SUPERVISOR_SAFE_NAME}]
process_name=%(program_name)s_%(process_num)02d
command=php $ARTISAN_PATH horizon
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

# Reload Supervisor
echo -e "${YELLOW}🔄 Reloading Supervisor...${NC}"
sudo supervisorctl reread
sudo supervisorctl update

echo -e "${BLUE}⏳ Waiting ${WAIT_SECONDS}s for Supervisor to register...${NC}"
sleep "$WAIT_SECONDS"

# Start Horizon
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
