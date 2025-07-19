#!/bin/bash

set -euo pipefail

LOGFILE="$HOME/logs/ollama_openwebui_install.log"
mkdir -p "$(dirname "$LOGFILE")"

log()   { echo "$(date '+%F %T') | $*" | tee -a "$LOGFILE"; }
error() { echo "$(date '+%F %T') | ❌ $*" | tee -a "$LOGFILE"; exit 1; }

log "🚀 Starting setup of Ollama + Open WebUI..."

# === 1. Install Docker ===
if ! command -v docker &>/dev/null; then
    log "📦 Installing Docker..."
    sudo pacman -S --noconfirm docker || error "Failed to install Docker"
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    log "✅ Docker installed and started"
else
    log "✅ Docker already installed"
fi

# === 2. Install Ollama ===
if ! command -v ollama &>/dev/null; then
    log "📦 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh || error "Ollama installation failed"
    log "✅ Ollama installed"
else
    log "✅ Ollama already installed"
fi

# === 3. Enable Ollama to listen on 0.0.0.0 ===
SERVICE_FILE="/etc/systemd/system/ollama.service"
ENV_LINE='Environment="OLLAMA_HOST=0.0.0.0"'

if grep -q 'OLLAMA_HOST=0.0.0.0' "$SERVICE_FILE"; then
    log "✅ OLLAMA_HOST already set in ollama.service"
else
    log "🔧 Adding OLLAMA_HOST=0.0.0.0 to $SERVICE_FILE"
    sudo sed -i "/^Environment=/a $ENV_LINE" "$SERVICE_FILE" || error "Failed to update $SERVICE_FILE"
    sudo systemctl daemon-reexec
    sudo systemctl daemon-reload
    sudo systemctl restart ollama || error "Failed to restart ollama.service"
    log "✅ Updated and restarted ollama.service with OLLAMA_HOST=0.0.0.0"
fi

# === 4. Start Ollama if not running ===
if ! ss -tuln | grep -q ':11434'; then
    log "▶️ Starting Ollama manually..."
    sudo pkill ollama || true
    OLLAMA_HOST=0.0.0.0 ollama serve & disown
    sleep 3
    ss -tuln | grep -q ':11434' || error "Ollama failed to start on port 11434"
    log "✅ Ollama running on 0.0.0.0:11434"
else
    log "✅ Ollama already running on port 11434"
fi

# === 5. Run Open WebUI container ===
log "🐳 Running Open WebUI Docker container..."

docker rm -f open-webui &>/dev/null || true

docker run -d \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main || error "Failed to run Open WebUI container"

log "✅ Open WebUI is running on http://localhost:3000"
log "🧠 You can now access Ollama via http://localhost:11434"

# === 6. Health check ===
log "🔎 Checking Open WebUI health..."

sleep 2
curl --silent --fail http://localhost:3000 &>/dev/null && log "✅ Open WebUI is responding" || error "Open WebUI did not respond"

# === 7. Pull Default Coding Model ===
DEFAULT_MODEL="deepseek-coder-v2:16b"

log "📥 Pulling default Ollama model: $DEFAULT_MODEL..."
if ollama list | grep -q "$DEFAULT_MODEL"; then
    log "✅ $DEFAULT_MODEL already pulled"
else
    ollama pull "$DEFAULT_MODEL" || error "Failed to pull model: $DEFAULT_MODEL"
    log "✅ Model $DEFAULT_MODEL pulled successfully"
fi

log "💡 You can run the model anytime using:"
log "    ollama run $DEFAULT_MODEL"

log "🎉 Setup complete!"
