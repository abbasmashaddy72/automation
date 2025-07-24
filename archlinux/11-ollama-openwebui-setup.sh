#!/bin/bash
set -euo pipefail

##############################################################################
# 09-ollama-openwebui-setup.sh
#   - Automated setup for Ollama LLM API + Open WebUI via Docker
#   - Handles install, Docker group config, service restarts, health checks
#   - Forward-compatible for automation and manual usage
##############################################################################

### ─── Logger & Platform Detection ─────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/../lib/lib-logger.sh" ]]; then
    echo "Logger library not found! Exiting." >&2
    exit 1
fi
source "$SCRIPT_DIR/../lib/lib-logger.sh"
if [[ ! -f "$SCRIPT_DIR/../lib/lib-platform.sh" ]]; then
    fail "Platform library not found! Exiting."
fi
source "$SCRIPT_DIR/../lib/lib-platform.sh"

# === Distro Check: Only Supported Platforms ===
ensure_supported_platform arch manjaro
section "🚀 Starting setup of Ollama + Open WebUI for $PLATFORM_STRING"

### ─── CLI Args and Defaults ──────────────────────────────────────────────

DEFAULT_MODEL="${OLLAMA_MODEL:-deepseek-r1:8b}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-3000}"
UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --model=*) DEFAULT_MODEL="${arg#*=}" ;;
        --port=*) OPENWEBUI_PORT="${arg#*=}" ;;
        --uninstall) UNINSTALL=1 ;;
    esac
done

### ─── Uninstall Routine ──────────────────────────────────────────────────

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

### ─── Ensure Docker Installed and Running ────────────────────────────────

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
    log "Run: 'id -nG' after login to verify docker group, or use 'sudo docker ...' in this session."
    docker info || true
    exit 1
fi

### ─── Install Ollama (if missing) ───────────────────────────────────────

if ! command -v ollama &>/dev/null; then
    log "📦 Installing Ollama (from official script)..."
    curl -fsSL https://ollama.com/install.sh | sh || fail "Ollama installation failed"
    ok "Ollama installed"
else
    ok "Ollama already installed"
fi

### ─── Ollama Network Binding ─────────────────────────────────────────────

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

### ─── Ensure Ollama Running (Port 11434) ────────────────────────────────

if ! ss -tuln | grep -q ':11434'; then
    log "▶️ Restarting Ollama service..."
    sudo systemctl restart ollama
    sleep 3
    ss -tuln | grep -q ':11434' || fail "Ollama failed to start on port 11434"
    ok "Ollama running on 0.0.0.0:11434"
else
    ok "Ollama already running on port 11434"
fi

### ─── UFW (Firewall) Rules (Optional but Recommended) ───────────────────

if command -v ufw &>/dev/null; then
    log "🔐 Configuring UFW for Docker <-> Ollama"
    sudo ufw allow in on lo to any port 11434 proto tcp || warn "Failed to allow 11434 on lo"
    if ip link show docker0 &>/dev/null; then
        sudo ufw allow in on docker0 to any port 11434 proto tcp || warn "Failed to allow 11434 on docker0"
    else
        warn "docker0 interface not found — skipping docker0 UFW rule"
    fi
    sudo ufw allow "$OPENWEBUI_PORT"/tcp || warn "Failed to allow port $OPENWEBUI_PORT"
    sudo ufw reload || warn "Failed to reload UFW"
    ok "UFW rules applied for Ollama and Open WebUI"
else
    warn "ufw not found, skipping firewall configuration"
fi

### ─── Run Open WebUI Docker Container ───────────────────────────────────

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

### ─── Wait for Open WebUI Container Health ──────────────────────────────

log "🔎 Waiting for Open WebUI container to report healthy..."

MAX_HEALTH_WAIT=60  # seconds
SECONDS_WAITED=0
HEALTH_STATUS="starting"

while [[ "$SECONDS_WAITED" -lt "$MAX_HEALTH_WAIT" ]]; do
  HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' open-webui 2>/dev/null || echo "not-found")
  case "$HEALTH_STATUS" in
    healthy)
      ok "Open WebUI container is healthy"
      break
      ;;
    unhealthy)
      fail "Open WebUI container is unhealthy"
      ;;
    not-found)
      fail "Open WebUI container not found"
      ;;
    *)
      sleep 2
      ((SECONDS_WAITED+=2))
      ;;
  esac
done

if [[ "$HEALTH_STATUS" != "healthy" ]]; then
  fail "Timed out waiting for Open WebUI to become healthy"
fi

### ─── HTTP Readiness Probe for Open WebUI ───────────────────────────────

log "🔎 Verifying Open WebUI is responding on http://localhost:$OPENWEBUI_PORT..."

for i in {1..10}; do
  if curl --silent --fail "http://localhost:$OPENWEBUI_PORT" &>/dev/null; then
    ok "Open WebUI is responding"
    break
  fi
  sleep 2
done || fail "Open WebUI did not respond after container became healthy"

### ─── Pull Default Model for Ollama ─────────────────────────────────────

log "📥 Pulling Ollama model: $DEFAULT_MODEL..."
if ollama list | grep -q "$DEFAULT_MODEL"; then
    ok "$DEFAULT_MODEL already pulled"
else
    ollama pull "$DEFAULT_MODEL" || fail "Failed to pull model: $DEFAULT_MODEL"
    ok "$DEFAULT_MODEL pulled successfully"
fi

### ─── Recap / Output Final Access URLs ──────────────────────────────────

section "🌐 Access URLs"
log "🟢 Ollama REST:   http://localhost:11434"
log "🟢 Open WebUI:    http://localhost:$OPENWEBUI_PORT"

ok "🎉 Ollama + Open WebUI setup complete!"

# End of script. Your local LLM dev server is now enterprise-class.
