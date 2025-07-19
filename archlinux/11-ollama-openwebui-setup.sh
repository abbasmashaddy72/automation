#!/bin/bash
set -euo pipefail

# === Logger Setup ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/lib-logger.sh"

section "🚀 Starting setup of Ollama + Open WebUI..."

# === 1. Install Docker ===
if ! command -v docker &>/dev/null; then
    log "📦 Installing Docker..."
    sudo pacman -S --noconfirm docker || fail "Failed to install Docker"
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    ok "Docker installed and started"
else
    ok "Docker already installed"
fi

# === 2. Install Ollama ===
if ! command -v ollama &>/dev/null; then
    log "📦 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh || fail "Ollama installation failed"
    ok "Ollama installed"
else
    ok "Ollama already installed"
fi

# === 3. Set Ollama to listen on all interfaces ===
SERVICE_FILE="/etc/systemd/system/ollama.service"
ENV_LINE='Environment="OLLAMA_HOST=0.0.0.0"'

if grep -q 'OLLAMA_HOST=0.0.0.0' "$SERVICE_FILE"; then
    ok "OLLAMA_HOST already set in ollama.service"
else
    log "🔧 Configuring OLLAMA_HOST in $SERVICE_FILE..."
    sudo sed -i "/^Environment=/a $ENV_LINE" "$SERVICE_FILE" || fail "Failed to update $SERVICE_FILE"
    sudo systemctl daemon-reexec
    sudo systemctl daemon-reload
    sudo systemctl restart ollama || fail "Failed to restart ollama.service"
    ok "OLLAMA_HOST configured and service restarted"
fi

# === 4. Start Ollama if not running ===
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

# === 5. Run Open WebUI ===
log "🐳 Running Open WebUI Docker container..."

docker rm -f open-webui &>/dev/null || true

docker run -d \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main || fail "Failed to run Open WebUI container"

ok "Open WebUI is running at http://localhost:3000"
log "🧠 Ollama is accessible at http://localhost:11434"

# === 6. Health Check ===
log "🔎 Checking Open WebUI status..."
sleep 2
curl --silent --fail http://localhost:3000 &>/dev/null && ok "Open WebUI is responding" || fail "Open WebUI is not responding"

# === 7. Pull Default Model ===
DEFAULT_MODEL="deepseek-coder-v2:16b"

log "📥 Pulling default Ollama model: $DEFAULT_MODEL..."
if ollama list | grep -q "$DEFAULT_MODEL"; then
    ok "$DEFAULT_MODEL already pulled"
else
    ollama pull "$DEFAULT_MODEL" || fail "Failed to pull model: $DEFAULT_MODEL"
    ok "$DEFAULT_MODEL pulled successfully"
fi

log "💡 You can now run the model using:"
log "    ollama run $DEFAULT_MODEL"

ok "🎉 Ollama + Open WebUI setup complete!"
