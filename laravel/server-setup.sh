#!/usr/bin/env bash
set -Eeuo pipefail

### ===== UI =====
RED='\033[0;31m'; GREEN='\033[0;32m'; YEL='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
log(){ echo -e "${BLU}➤ $*${NC}"; }
ok(){ echo -e "${GREEN}✔ $*${NC}"; }
warn(){ echo -e "${YEL}⚠ $*${NC}"; }
err(){ echo -e "${RED}✖ $*${NC}" >&2; }
section(){ echo -e "\n${YEL}==> $*${NC}"; }

### ===== Self-escalate so you can run ./server-setup.sh =====
if [[ ${EUID:-$UID} -ne 0 ]]; then
  log "Re-running with sudo…"
  exec sudo -E bash "$0" "$@"
fi

### ===== Lock & trap =====
exec 9>"/tmp/server-setup.lock"; flock -n 9 || { err "Another setup is running."; exit 1; }
trap 'err "Failed at line $LINENO"; exit 1' ERR

### ===== Helpers (DRY) =====
ask_yn(){ local q="$1" def="${2:-Y}" a p; [[ "$def" == Y ]] && p="[Y/n]" || p="[y/N]"; while read -rp "$q $p: " a; do case "$a" in "" ) [[ $def == Y ]] && return 0 || return 1;; [Yy]) return 0;; [Nn]) return 1;; *) echo "Please answer y or n.";; esac; done; }
ask(){ local p="$1" d="$2" a; read -rp "$p [$d]: " a; echo "${a:-$d}"; }
exists(){ command -v "$1" >/dev/null 2>&1; }
apt_update_once(){ [[ -f /tmp/.apt_updated ]] || { apt-get update -y || true; touch /tmp/.apt_updated; }; }
pkg(){ apt_update_once; DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" || { warn "apt failed to install: $*"; return 0; }; }
enable_and_start(){ systemctl enable "$1" >/dev/null 2>&1 || true; systemctl start "$1" >/dev/null 2>&1 || true; }
ensure_dir(){ mkdir -p "$1"; }
ufw_allow(){ ufw allow "$1" >/dev/null 2>&1 || warn "UFW: failed to allow $1"; }
php_minor(){ php -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;' 2>/dev/null || echo "8.3"; }

# Detect invoking user and home (works under sudo)
detect_user(){ echo "${SUDO_USER:-$USER}"; }  # SUDO_USER is set by sudo to original user
detect_home(){
  local u="$1"; local h
  h="$(getent passwd "$u" | cut -d: -f6)"
  [[ -n "$h" ]] && echo "$h" || echo "/home/$u"
}

# Nginx fastcgi target detection: prefer FPM socket; fallback to TCP
detect_fastcgi_pass(){
  local ver; ver="$(php_minor)"
  local sock="/run/php/php${ver}-fpm.sock"
  [[ -S "$sock" ]] && { echo "unix:${sock}"; return; }
  # last resort: TCP
  echo "127.0.0.1:9000"
}

### ===== Inputs =====
TARGET_USER="$(detect_user)"
TARGET_HOME="$(detect_home "$TARGET_USER")"  # e.g., /home/syed
DEFAULT_PROJECTS="${TARGET_HOME%/}/projects"

DOMAIN="$(ask 'Primary domain (no scheme)' 'example.com')"
ADD_WWW=false;  ask_yn "Also serve www.${DOMAIN}?" "Y" && ADD_WWW=true
PROJECT_PATH="$(ask 'Path to project' "${DEFAULT_PROJECTS}/${DOMAIN}")"

# Default docroot: /home/$USER/projects/<domain>/public if it exists; else project root
USE_PUBLIC=true; [[ -d "${PROJECT_PATH%/}/public" ]] || USE_PUBLIC=false
ask_yn "Use ${PROJECT_PATH%/}/public as docroot?" "$([[ $USE_PUBLIC == true ]] && echo Y || echo N)" || USE_PUBLIC=false
DOCROOT="$PROJECT_PATH"; $USE_PUBLIC && DOCROOT="${PROJECT_PATH%/}/public"

INSTALL_DB=false; ask_yn "Install local MariaDB (choose N if using RDS)?" "N" && INSTALL_DB=true
CONFIG_UFW=true;  ask_yn "Configure UFW (open SSH/HTTP/HTTPS)?" "Y" || CONFIG_UFW=false
ENABLE_SSL=false; ask_yn "Enable HTTPS with Let's Encrypt (Certbot) now?" "Y" && ENABLE_SSL=true
EMAIL=""; $ENABLE_SSL && EMAIL="$(ask 'Admin email for Let’s Encrypt' "admin@${DOMAIN}")"

### ===== Sections =====
install_base(){
  section "🧰 Base packages"
  pkg software-properties-common curl ca-certificates unzip git lsb-release apt-transport-https gnupg
  ok "Base packages checked."
}

install_nginx(){
  section "🌐 Nginx"
  pkg nginx
  if exists nginx; then
    enable_and_start nginx
    ok "Nginx installed & running."
  else
    warn "Nginx not present; skipping vhost configuration."
  fi
}

install_php(){
  section "🐘 PHP-FPM & extensions (Ubuntu 24.04 ships PHP 8.3)"
  pkg php8.3-fpm php8.3-cli php8.3-xml php8.3-mbstring php8.3-curl php8.3-zip php8.3-gd php8.3-intl php8.3-bcmath php8.3-mysql php8.3-pgsql php8.3-sqlite3 php-redis
  # Start FPM if installed
  local ver svc; ver="$(php_minor)"; svc="php${ver}-fpm"
  systemctl list-unit-files | grep -q "^${svc}.service" && enable_and_start "$svc" || true
  ok "PHP $(php -v 2>/dev/null | head -n1 || echo 'unknown') checked."
}

install_composer(){
  section "🎼 Composer"
  if ! exists composer; then
    if apt-get install -y composer >/dev/null 2>&1; then
      ok "Composer installed via apt."
    else
      warn "apt composer unavailable—using official installer."
      local exp act
      exp="$(curl -fsSL https://getcomposer.org/installer.sig)" || exp=""
      php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');" || true
      act="$(php -r 'echo @hash_file("sha384","composer-setup.php");' 2>/dev/null || true)"
      if [[ -n "$exp" && "$exp" == "$act" ]]; then
        php composer-setup.php --install-dir=/usr/local/bin --filename=composer || warn "Composer installer run failed"
        rm -f composer-setup.php
        exists composer && ok "Composer installed via getcomposer.org." || warn "Composer not found after install."
      else
        rm -f composer-setup.php
        warn "Composer installer signature mismatch—skipping."
      fi
    fi
  else
    ok "Composer already present: $(composer -V)"
  fi
}

install_node(){
  section "🟢 Node.js (apt)"
  # Use Ubuntu repo (simple & stable). Installs npm too.
  pkg nodejs npm
  if exists node; then
    ok "Node: $(node -v) • npm: $(npm -v 2>/dev/null || echo '-')"
  else
    warn "nodejs not present after apt; you can install via NodeSource/NVM later if needed."
  fi
}

install_mariadb(){
  $INSTALL_DB || return 0
  section "🗄️ MariaDB (local)"
  pkg mariadb-server
  systemctl list-unit-files | grep -q '^mariadb.service' && enable_and_start mariadb || true
  warn "Consider running: mysql_secure_installation"
}

prepare_project_dir(){
  section "📁 Project directory & permissions"
  ensure_dir "$PROJECT_PATH"
  # Prefer ownership by invoking user; grant group write to www-data
  chown -R "$TARGET_USER":"www-data" "$PROJECT_PATH" || true
  chmod -R g=rwX "$PROJECT_PATH" || true
  ok "Project path ready: $PROJECT_PATH (docroot: $DOCROOT)"
}

write_nginx_vhost(){
  exists nginx || return 0
  section "📝 Nginx server block"
  local SITES_AVAILABLE="/etc/nginx/sites-available"
  local SITES_ENABLED="/etc/nginx/sites-enabled"
  local VHOST="${SITES_AVAILABLE}/${DOMAIN}"
  local SERVER_NAMES="${DOMAIN}"; $ADD_WWW && SERVER_NAMES="${DOMAIN} www.${DOMAIN}"
  local FASTCGI; FASTCGI="$(detect_fastcgi_pass)"

  cat > "$VHOST" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};

    root ${DOCROOT};
    index index.php index.html;

    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";

    location / {
        try_files \$uri \$uri/ /index.php?\$query_string;
    }

    location ~ \.php\$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass ${FASTCGI};
    }

    location ~ /\.ht {
        deny all;
    }

    client_max_body_size 64M;
}
NGINX

  ln -sf "$VHOST" "${SITES_ENABLED}/${DOMAIN}"
  [[ -e ${SITES_ENABLED}/default ]] && rm -f ${SITES_ENABLED}/default
  nginx -t && systemctl reload nginx || warn "nginx -t failed; check config."
  ok "Vhost enabled for ${SERVER_NAMES}"
}

configure_ufw(){
  $CONFIG_UFW || return 0
  section "🧱 UFW firewall"
  pkg ufw
  ufw_allow "OpenSSH"
  ufw_allow "80/tcp"
  ufw_allow "443/tcp"
  ask_yn "Enable UFW now?" "Y" && ufw --force enable || true
}

enable_https(){
  $ENABLE_SSL || return 0
  exists nginx || { warn "Nginx missing; skipping Certbot."; return 0; }
  section "🔐 Let's Encrypt (Certbot via apt)"
  pkg certbot python3-certbot-nginx
  if exists certbot; then
    local DOMARGS="-d ${DOMAIN}"; $ADD_WWW && DOMARGS="$DOMARGS -d www.${DOMAIN}"
    certbot --nginx $DOMARGS -m "$EMAIL" --agree-tos -n --redirect || warn "Certbot issuance failed; retry later."
    systemctl reload nginx || true
    ok "SSL attempted for ${DOMAIN}"
  else
    warn "Certbot not available; skipping SSL."
  fi
}

reload_php(){
  section "♻️ Reload PHP-FPM"
  local ver svc; ver="$(php_minor)"; svc="php${ver}-fpm"
  systemctl list-unit-files | grep -q "^${svc}.service" && systemctl reload "$svc" || warn "PHP-FPM service not found: $svc"
}

### ===== Main =====
main(){
  install_base
  install_nginx
  install_php
  install_composer
  install_node
  install_mariadb
  prepare_project_dir
  write_nginx_vhost
  configure_ufw
  enable_https
  reload_php

  ok "Server setup complete."
  echo -e "${GREEN}HTTP:  http://${DOMAIN}${NC}"
  [[ $ENABLE_SSL == true ]] && echo -e "${GREEN}HTTPS: https://${DOMAIN}${NC}"
}

main "$@"
