#!/usr/bin/env bash
set -Eeuo pipefail

##############################################################################
# 91-ollama-openwebui-setup.sh
#
# Purpose
# -------
# Automated setup for:
# - Ollama (local LLM API, systemd service)
# - Open WebUI (Docker container)
# - Optional pulls of multiple Ollama models
#
# Defaults
# --------
# - Models: dolphin3:8b
# - Open WebUI port: 3000
# - Ollama listens on: 127.0.0.1:11434 by default (safer)
#
# Safety / Reliability
# --------------------
# - Idempotent: safe to re-run
# - Supports --uninstall (best-effort rollback)
# - Avoids forcing OLLAMA_HOST=0.0.0.0 unless you explicitly request it
# - Firewall rules:
#     * If firewalld is active → do NOT use ufw
#     * If ufw exists and firewalld is NOT active → apply minimal rules
#     * If neither exists → skip firewall config cleanly
# - Docker group:
#     * If you’re not in docker group, script can continue using sudo docker
#       (no hard exit). It warns you to re-login for group to apply.
#
# Requires
# --------
# - ../lib/lib-logger.sh
# - ../lib/lib-platform.sh
#
# Usage
# -----
#   ./91-ollama-openwebui-setup.sh
#   ./91-ollama-openwebui-setup.sh --models=dolphin3:8b,deepseek-r1:8b
#   ./91-ollama-openwebui-setup.sh --port=3000
#   ./91-ollama-openwebui-setup.sh --ollama-host=0.0.0.0
#   ./91-ollama-openwebui-setup.sh --uninstall
##############################################################################

### ─────────────────────────────────────────────────────────────────────────
### Crash context (so errors aren’t a mystery)
### ─────────────────────────────────────────────────────────────────────────
on_err() { echo "❌ Error on line $1 while running: $2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

### ─────────────────────────────────────────────────────────────────────────
### Logger & platform detection
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
section "🚀 Ollama + Open WebUI setup for $PLATFORM_STRING"

### ─────────────────────────────────────────────────────────────────────────
### Defaults / args
### ─────────────────────────────────────────────────────────────────────────
DEFAULT_MODELS="dolphin3:8b"
MODEL_LIST="${OLLAMA_MODELS:-}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-3000}"
UNINSTALL="n"

# Safer default: only local machine
OLLAMA_HOST_BIND="${OLLAMA_HOST_BIND:-127.0.0.1}"

for arg in "$@"; do
    case "$arg" in
        --model=*)  MODEL_LIST="${arg#*=}" ;;     # legacy single model → treated as list of 1
        --models=*) MODEL_LIST="${arg#*=}" ;;
        --port=*)   OPENWEBUI_PORT="${arg#*=}" ;;
        --ollama-host=*) OLLAMA_HOST_BIND="${arg#*=}" ;;   # 127.0.0.1 or 0.0.0.0
        --uninstall) UNINSTALL="y" ;;
        -h|--help)
      cat <<EOF
Usage:
  $0 [options]

Options:
  --models=a,b,c        Comma-separated models to pull (default: dolphin3:8b)
  --port=3000           Open WebUI host port (default: 3000)
  --ollama-host=IP      Bind Ollama host (default: 127.0.0.1; use 0.0.0.0 if you know why)
  --uninstall           Remove Open WebUI container/volume and uninstall packages (best-effort)

Env overrides:
  OLLAMA_MODELS         same as --models
  OPENWEBUI_PORT        same as --port
  OLLAMA_HOST_BIND      same as --ollama-host
EOF
            exit 0
        ;;
    esac
done

if [[ -z "${MODEL_LIST// }" ]]; then
    MODEL_LIST="$DEFAULT_MODELS"
fi

# Port validation (basic)
if ! [[ "$OPENWEBUI_PORT" =~ ^[0-9]{2,5}$ ]] || (( OPENWEBUI_PORT < 1 || OPENWEBUI_PORT > 65535 )); then
    fail "Invalid --port value: $OPENWEBUI_PORT"
fi

### ─────────────────────────────────────────────────────────────────────────
### Sudo upfront
### ─────────────────────────────────────────────────────────────────────────
log "🔐 Please enter your sudo password to continue..."
sudo -v || fail "❌ Failed to authenticate sudo."

### ─────────────────────────────────────────────────────────────────────────
### Helpers
### ─────────────────────────────────────────────────────────────────────────
have_cmd() { command -v "$1" &>/dev/null; }

prompt_yn() {
    local prompt="${1:-Continue?}"
    local default="${2:-y}"
    local reply=""
    while true; do
        if [[ "$default" == "y" ]]; then
            read -r -p "$prompt [Y/n]: " reply
            reply="${reply:-y}"
        else
            read -r -p "$prompt [y/N]: " reply
            reply="${reply:-n}"
        fi
        case "${reply,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

docker_cmd() {
    # If user is in docker group, use docker directly, else sudo docker.
    if groups "$USER" 2>/dev/null | grep -qw docker; then
        docker "$@"
    else
        sudo docker "$@"
    fi
}

is_systemd_unit_present() {
    local unit="$1"
    systemctl list-unit-files | grep -q "^${unit}\.service"
}

is_firewalld_active() {
    systemctl is-active --quiet firewalld 2>/dev/null
}

is_ufw_active_or_present() {
    have_cmd ufw
}

### ─────────────────────────────────────────────────────────────────────────
### Uninstall routine (best-effort)
### ─────────────────────────────────────────────────────────────────────────
run_uninstall() {
    section "🧹 Uninstalling Ollama + Open WebUI (best-effort)"
    
    # Open WebUI
    if have_cmd docker || sudo -v >/dev/null 2>&1; then
        docker_cmd rm -f open-webui >/dev/null 2>&1 || warn "No open-webui container to remove"
        docker_cmd volume rm open-webui >/dev/null 2>&1 || warn "No open-webui volume to remove"
    fi
    
    # Ollama service
    if is_systemd_unit_present ollama; then
        sudo systemctl stop ollama >/dev/null 2>&1 || warn "ollama service not running"
        sudo systemctl disable ollama >/dev/null 2>&1 || warn "ollama service not enabled"
    fi
    
    # Remove packages (won’t fail hard)
    sudo pacman -Rs --noconfirm ollama docker >/dev/null 2>&1 || warn "Could not remove docker/ollama (maybe not installed or deps locked)"
    
    ok "✅ Uninstall done."
}

if [[ "$UNINSTALL" == "y" ]]; then
    run_uninstall
    exit 0
fi

### ─────────────────────────────────────────────────────────────────────────
### Ensure base tools
### ─────────────────────────────────────────────────────────────────────────
section "📦 Ensuring base packages"

# Docker (pacman)
if ! have_cmd docker; then
    log "Installing Docker..."
    sudo pacman -S --noconfirm --needed docker || fail "Failed to install Docker"
    ok "Docker installed."
else
    ok "Docker already installed."
fi

# Enable docker service
sudo systemctl enable --now docker || fail "Failed to enable/start docker.service"
ok "Docker service running."

# Docker group handling (don’t hard exit)
if ! groups "$USER" | grep -qw docker; then
    warn "You are not in the 'docker' group. I can continue using 'sudo docker' for this run."
    if prompt_yn "Add $USER to docker group now? (recommended)" "y"; then
        sudo usermod -aG docker "$USER" || warn "Failed to add user to docker group"
        warn "Group changes require logout/login to take effect for non-sudo docker usage."
    fi
else
    ok "$USER is in docker group."
fi

### ─────────────────────────────────────────────────────────────────────────
### Install Ollama (pacman first; fallback to official script optional)
### ─────────────────────────────────────────────────────────────────────────
section "🧠 Ensuring Ollama is installed"

if ! have_cmd ollama; then
    if sudo pacman -Si ollama >/dev/null 2>&1; then
        log "Installing Ollama via pacman..."
        sudo pacman -S --noconfirm --needed ollama || fail "Failed to install Ollama via pacman"
        ok "Ollama installed via pacman."
    else
        warn "Ollama package not available via pacman on this distro/repo."
        warn "Falling back to official installer script (network required)."
        have_cmd curl || sudo pacman -S --noconfirm --needed curl || fail "curl required for official installer"
        curl -fsSL https://ollama.com/install.sh | sh || fail "Ollama installation failed"
        ok "Ollama installed via official script."
    fi
else
    ok "Ollama already installed."
fi

### ─────────────────────────────────────────────────────────────────────────
### Configure Ollama bind (systemd drop-in, safer than editing unit file)
### ─────────────────────────────────────────────────────────────────────────
section "🔧 Configuring Ollama bind address"

if [[ "$OLLAMA_HOST_BIND" != "127.0.0.1" && "$OLLAMA_HOST_BIND" != "0.0.0.0" ]]; then
    warn "OLLAMA_HOST_BIND is '$OLLAMA_HOST_BIND'."
    warn "Only '127.0.0.1' or '0.0.0.0' are officially supported in this script."
    fail "Invalid --ollama-host value."
fi

# Use systemd drop-in to avoid editing /etc/systemd/system/ollama.service directly.
DROPIN_DIR="/etc/systemd/system/ollama.service.d"
DROPIN_FILE="$DROPIN_DIR/override.conf"

sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN_FILE" >/dev/null <<EOF
[Service]
Environment="OLLAMA_HOST=${OLLAMA_HOST_BIND}:11434"
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ollama || fail "Failed to enable/start ollama.service"
ok "Ollama service started with OLLAMA_HOST=${OLLAMA_HOST_BIND}:11434"

### ─────────────────────────────────────────────────────────────────────────
### Ensure Ollama listening
### ─────────────────────────────────────────────────────────────────────────
section "🧪 Verifying Ollama is listening on 11434"

# ss might not exist in minimal installs; iproute2 provides it. Ensure.
if ! have_cmd ss; then
    sudo pacman -S --noconfirm --needed iproute2 >/dev/null 2>&1 || true
fi

if have_cmd ss; then
    if ! ss -tuln | grep -q ':11434'; then
        warn "Port 11434 not detected yet. Restarting Ollama..."
        sudo systemctl restart ollama
        sleep 2
        ss -tuln | grep -q ':11434' || fail "Ollama failed to start on port 11434"
    fi
else
    warn "ss not available; skipping socket check."
fi
ok "Ollama appears to be up."

### ─────────────────────────────────────────────────────────────────────────
### Firewall rules (only if ufw exists AND firewalld is NOT active)
### ─────────────────────────────────────────────────────────────────────────
section "🛡️ Firewall configuration (optional)"

if is_firewalld_active; then
    warn "firewalld is active. Skipping ufw configuration (per your rule)."
    elif is_ufw_active_or_present; then
    log "Configuring UFW rules for Open WebUI port ($OPENWEBUI_PORT)."
    
    # Only open WebUI port; Ollama is accessed from container via host-gateway.
    # If you bind Ollama to 0.0.0.0, you may choose to open 11434 too, but we don't by default.
    sudo ufw allow "${OPENWEBUI_PORT}/tcp" >/dev/null 2>&1 || warn "Failed to allow port $OPENWEBUI_PORT"
    sudo ufw reload >/dev/null 2>&1 || warn "Failed to reload UFW"
    ok "UFW rules applied (best-effort)."
else
    warn "No ufw detected and firewalld not active. Skipping firewall configuration."
fi

### ─────────────────────────────────────────────────────────────────────────
### Run Open WebUI container
### ─────────────────────────────────────────────────────────────────────────
section "🐳 Running Open WebUI via Docker"

docker_cmd rm -f open-webui >/dev/null 2>&1 || true

# Use host-gateway mapping for Linux so container can reach host Ollama reliably.
# OLLAMA_BASE_URL points to host's 11434.
docker_cmd run -d \
-p "${OPENWEBUI_PORT}:8080" \
--add-host=host.docker.internal:host-gateway \
-e "OLLAMA_BASE_URL=http://host.docker.internal:11434" \
-v open-webui:/app/backend/data \
--name open-webui \
--restart always \
ghcr.io/open-webui/open-webui:main || fail "Failed to run Open WebUI container"

ok "Open WebUI container started."
ok "Open WebUI: http://localhost:${OPENWEBUI_PORT}"
log "Ollama:     http://localhost:11434 (bind: ${OLLAMA_HOST_BIND})"

### ─────────────────────────────────────────────────────────────────────────
### Container health/readiness (best-effort; not all images expose healthcheck)
### ─────────────────────────────────────────────────────────────────────────
section "🩺 Waiting for Open WebUI readiness"

MAX_WAIT=180
WAITED=0

while (( WAITED < MAX_WAIT )); do
    # If no healthcheck exists, docker inspect will error; treat as "unknown" and continue.
    status="$(docker_cmd inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' open-webui 2>/dev/null || echo "unknown")"
    case "$status" in
        healthy)
            ok "Open WebUI container reports healthy."
            break
        ;;
        unhealthy)
            docker_cmd logs --tail 80 open-webui || true
            fail "Open WebUI container reports UNHEALTHY."
        ;;
        none|unknown)
            # No healthcheck in image; fall back to HTTP probe soon.
        ;;
        *)
        ;;
    esac
    sleep 2
    ((WAITED+=2))
done

# HTTP readiness probe
if ! have_cmd curl; then
    sudo pacman -S --noconfirm --needed curl >/dev/null 2>&1 || true
fi

log "Probing Open WebUI HTTP on http://localhost:${OPENWEBUI_PORT} ..."
ok_http="n"
for _ in {1..20}; do
    if curl --silent --fail "http://localhost:${OPENWEBUI_PORT}" >/dev/null 2>&1; then
        ok_http="y"
        break
    fi
    sleep 2
done

if [[ "$ok_http" != "y" ]]; then
    docker_cmd logs --tail 120 open-webui || true
    fail "Open WebUI did not respond on port ${OPENWEBUI_PORT}."
fi
ok "Open WebUI is responding."

### ─────────────────────────────────────────────────────────────────────────
### Pull requested models (comma-separated)
### ─────────────────────────────────────────────────────────────────────────
section "📥 Pulling requested Ollama models"

IFS=',' read -ra MODELS <<< "$MODEL_LIST"

for MODEL in "${MODELS[@]}"; do
  MODEL="$(echo "$MODEL" | xargs)" # trim
  [[ -n "$MODEL" ]] || continue

  log "Pulling: $MODEL"
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qxF "$MODEL"; then
    ok "$MODEL already present"
  else
    ollama pull "$MODEL" || fail "Failed to pull model: $MODEL"
    ok "$MODEL pulled"
  fi
done

### ─────────────────────────────────────────────────────────────────────────
### Recap
### ─────────────────────────────────────────────────────────────────────────
section "🌐 Access URLs"
log "🟢 Ollama REST: http://localhost:11434"
log "🟢 Open WebUI:  http://localhost:${OPENWEBUI_PORT}"

ok "🎉 Ollama + Open WebUI setup complete! Models: ${MODELS[*]}"
