#!/bin/bash
set -euo pipefail

# === Logger & Platform Detection ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/../lib/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
if [[ ! -f "$SCRIPT_DIR/../lib/lib-platform.sh" ]]; then
    echo "Platform library not found! Exiting." >&2
    exit 1
fi

source "$SCRIPT_DIR/../lib/lib-logger.sh"
source "$SCRIPT_DIR/../lib/lib-platform.sh"

# === Distro Check: Only Supported Platforms ===
ensure_supported_platform arch manjaro
section "🚀 Starting setup of Ollama + Open WebUI for $PLATFORM_STRING"

# === Args & Defaults ===
DEFAULT_MODEL="${OLLAMA_MODEL:-deepseek-coder-v2:16b}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-3000}"
UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --model=*) DEFAULT_MODEL="${arg#*=}" ;;
        --port=*) OPENWEBUI_PORT="${arg#*=}" ;;
        --uninstall) UNINSTALL=1 ;;
    esac
done

# === Uninstall Option ===
if [[ "$UNINSTALL" == "1" ]]; then
    section "🧹 Uninstalling Ollama and Open WebUI Docker setup"
    docker rm -f open-webui &>/dev/null || warn "No open-webui container to remove"
    docker volume rm open-webui &>/dev/null || warn "No open-webui volume to remove"
    sudo systemctl stop ollama &>/dev/null || warn "ollama service not running"
    sudo systemctl disable ollama &>/dev/null || warn "ollama service not enabled"
    sudo pacman -Rs --noconfirm docker ollama &>/dev/null || warn "Failed to remove docker/ollama (ignore if not present)"
    ok "Ollama and Open WebUI uninstalled and cleaned up."
    exit 0
fi

# === Ensure Docker Installed & Started ===
if ! command -v docker &>/dev/null; then
    log "📦 Installing Docker..."
    sudo pacman -S --noconfirm --needed docker || fail "Failed to install Docker"
    sudo systemctl enable --now docker
    ok "Docker installed and started"
else
    ok "Docker already installed"
fi

# === Docker Group Handling (must logout/login if added) ===
if ! groups "$USER" | grep -qw docker; then
    sudo usermod -aG docker "$USER"
    warn "Added $USER to docker group. You *must log out and log in* for this to take effect. Exiting."
    exit 1
fi

# === Install Ollama ===
if ! command -v ollama &>/dev/null; then
    log "📦 Installing Ollama (from official script)..."
    curl -fsSL https://ollama.com/install.sh | sh || fail "Ollama installation failed"
    ok "Ollama installed"
else
    ok "Ollama already installed"
fi

# === Set Ollama to listen on all interfaces ===
SERVICE_FILE="/etc/systemd/system/ollama.service"
ENV_LINE='Environment="OLLAMA_HOST=0.0.0.0"'
if [[ -f "$SERVICE_FILE" ]] && ! grep -q 'OLLAMA_HOST=0.0.0.0' "$SERVICE_FILE"; then
    log "🔧 Configuring OLLAMA_HOST in $SERVICE_FILE..."
    sudo sed -i "/^Environment=/a $ENV_LINE" "$SERVICE_FILE" || fail "Failed to update $SERVICE_FILE"
    sudo systemctl daemon-reexec
    sudo systemctl daemon-reload
    sudo systemctl restart ollama || fail "Failed to restart ollama.service"
    ok "OLLAMA_HOST configured and service restarted"
fi

# === Ensure Ollama running on port 11434 ===
if ! ss -tuln | grep -q ':11434'; then
    log "▶️ Starting Ollama manually..."
    sudo pkill ollama || true
    OLLAMA_HOST=0.0.0.0 ollama serve & disown
    sleep 3
    ss -tuln | grep -q ':11434' || fail "Ollama failed to start on port 11434"
    ok "Ollama running on 0.0.0.0:11434"
else
    ok "Ollama already running on port 11434"
fi

# === Run Open WebUI ===
log "🐳 Running Open WebUI Docker container on port $OPENWEBUI_PORT..."
docker rm -f open-webui &>/dev/null || true

docker run -d \
  -p "$OPENWEBUI_PORT":8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main || fail "Failed to run Open WebUI container"

ok "Open WebUI is running at http://localhost:$OPENWEBUI_PORT"
log "🧠 Ollama is accessible at http://localhost:11434"

# === Health Check ===
log "🔎 Checking Open WebUI status..."
sleep 2
curl --silent --fail http://localhost:$OPENWEBUI_PORT &>/dev/null && ok "Open WebUI is responding" || fail "Open WebUI is not responding"

# === Pull Default Model ===
log "📥 Pulling Ollama model: $DEFAULT_MODEL..."
if ollama list | grep -q "$DEFAULT_MODEL"; then
    ok "$DEFAULT_MODEL already pulled"
else
    ollama pull "$DEFAULT_MODEL" || fail "Failed to pull model: $DEFAULT_MODEL"
    ok "$DEFAULT_MODEL pulled successfully"
fi

section "🌐 Access URLs"
log "🟢 Ollama REST:   http://localhost:11434"
log "🟢 Open WebUI:    http://localhost:$OPENWEBUI_PORT"

ok "🎉 Ollama + Open WebUI setup complete!"
