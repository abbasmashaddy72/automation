#!/usr/bin/env bash
set -euo pipefail

# ================== CONFIGURATION BLOCK ===================
PROJECTS_DIR="${HOME}/docker-projects"
SUPPORTED_PHP_VERSIONS=("5.6" "7.2" "7.4" "8.0" "8.1" "8.2" "8.3" "8.4")
SUPPORTED_WEBSERVERS=("nginx" "apache")
declare -A WEBSERVER_IMAGE_MAP=( ["nginx"]="nginx:latest" ["apache"]="httpd:latest" )
SUPPORTED_DBS=("mariadb" "postgres" "none")
NGINX_PORT_START=8080
APACHE_PORT_START=9080

# --- Detect Docker Compose CLI (v2 preferred, fallback to v1) ---
detect_compose() {
  if command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE_BIN="docker-compose"
    return
  fi
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    DOCKER_COMPOSE_BIN="docker compose"
    return
  fi
  echo "Docker Compose not found. Attempting auto-install..."

  # Try to auto-install based on distro
  if [[ -f /etc/arch-release ]]; then
    sudo pacman -Sy --needed --noconfirm docker-compose
  elif [[ -f /etc/debian_version ]]; then
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin docker-compose
  elif [[ -f /etc/redhat-release ]] || [[ -f /etc/centos-release ]]; then
    sudo dnf install -y docker-compose
  else
    echo "Unsupported OS for auto-install. Please install docker-compose manually."
    exit 1
  fi

  # Try again!
  if command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE_BIN="docker-compose"
    return
  fi
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    DOCKER_COMPOSE_BIN="docker compose"
    return
  fi

  echo "Docker Compose could not be installed automatically."
  exit 1
}

# ========== HELPER/UTILITY FUNCTIONS ===========
pause() { read -rp "Press Enter to continue..."; }
title() { echo -e "\n\033[1;36m$*\033[0m"; }
info()  { echo -e "\033[1;34m$*\033[0m"; }
warn()  { echo -e "\033[1;33m$*\033[0m"; }
err()   { echo -e "\033[1;31m$*\033[0m"; }
success(){ echo -e "\033[1;32m$*\033[0m"; }

# List existing projects
list_projects() {
  title "Existing Docker Projects"
  if [[ ! -d "$PROJECTS_DIR" ]] || [[ -z "$(ls -A "$PROJECTS_DIR" 2>/dev/null)" ]]; then
    echo "No projects found in $PROJECTS_DIR."
  else
    PS3="Choose a project: "
    select project in $(ls "$PROJECTS_DIR"); do
      [[ -n "$project" ]] && break
      warn "Invalid selection!"
    done
  fi
}

# ========== MAIN MENU ===========
main_menu() {
  clear
  title "🟦 PHP Docker Project Wizard"
  info "This tool will create, run, or remove isolated PHP dev environments using Docker!"
  echo "1) Create a new project"
  echo "2) Start an existing project"
  echo "3) Stop an existing project"
  echo "4) Restart an existing project"
  echo "5) Delete an existing project"
  echo "6) List projects"
  echo "7) Recreate an existing project (override config)"
  echo "8) Quit"
  read -rp "Choose an option [1-8]: " opt
  case "$opt" in
    1) create_project ;;
    2) start_existing ;;
    3) stop_existing ;;
    4) restart_existing ;;
    5) delete_existing ;;
    6) list_projects ; pause ; main_menu ;;
    7) recreate_existing_project ;;
    8) exit 0 ;;
    *) warn "Invalid input!" ; pause ; main_menu ;;
  esac
}

# ========== CREATE NEW PROJECT ===========
create_project() {
  mkdir -p "$PROJECTS_DIR"
  title "🆕 New Project Setup"

  # --- Project Name ---
  while true; do
    read -rp "Enter project name (no spaces): " PROJECT
    [[ "$PROJECT" =~ ^[A-Za-z0-9_-]+$ ]] || { warn "Only letters, numbers, - and _ allowed."; continue; }
    PROJECT_DIR="$PROJECTS_DIR/$PROJECT"
    [[ -d "$PROJECT_DIR" ]] && { warn "That project exists. Start/stop/delete from main menu!"; main_menu; }
    break
  done

  # --- Project Code Source ---
  echo "How would you like to add your code?"
  echo "1) Clone from Git repository"
  echo "2) Copy from local folder"
  echo "3) Create empty folder"
  read -rp "Choose [1-3]: " srcopt
  mkdir -p "$PROJECT_DIR"
  case "$srcopt" in
    1)
      read -rp "Enter git clone URL: " GIT_URL
      git clone "$GIT_URL" "$PROJECT_DIR"
      ;;
    2)
      read -rp "Enter local path to copy from: " SRC_PATH
      cp -a "$SRC_PATH"/. "$PROJECT_DIR"/
      ;;
    3)
      # Already created
      ;;
    *) warn "Invalid input!"; rm -rf "$PROJECT_DIR"; main_menu ;;
  esac

  # --- PHP Version ---
  title "Choose PHP version"
  select PHPV in "${SUPPORTED_PHP_VERSIONS[@]}"; do
    [[ -n "$PHPV" ]] && break
    warn "Invalid selection."
  done

  # --- Web Server ---
  title "Choose web server"
  select WSS in "${SUPPORTED_WEBSERVERS[@]}"; do
    [[ -n "$WSS" ]] && break
    warn "Invalid selection."
  done

  # Get correct image for webserver (nginx/httpd)
  WEBSERVER_IMAGE="${WEBSERVER_IMAGE_MAP[$WSS]}"

  # --- DB Engine ---
  title "Database Engine"
  select DB in "${SUPPORTED_DBS[@]}"; do
    [[ -n "$DB" ]] && break
    warn "Invalid selection."
  done

  # --- DB Details ---
  USE_DOCKER_DB=0
  DB_HOST="db"
  DB_PORT="" DB_NAME="" DB_USER="" DB_PASS=""
  if [[ "$DB" == "mariadb" || "$DB" == "postgres" ]]; then
    echo "Where is your database?"
    echo "1) Use separate Docker DB (self-contained)"
    echo "2) Connect to existing local DB (host machine)"
    read -rp "Choose [1-2]: " dbwhere
    if [[ "$dbwhere" == "2" ]]; then
      # Get DB connection details
      if [[ "$(uname)" == "Linux" ]]; then
        DB_HOST="172.17.0.1"  # Linux host machine IP
      else
        DB_HOST="host.docker.internal"  # macOS / Windows
      fi

      # Get DB connection details
      if [[ "$DB" == "mariadb" ]]; then
        DB_PORT="3306"
      else
        DB_PORT="5432"
      fi

      read -rp "DB name: " DB_NAME
      read -rp "DB user: " DB_USER
      read -rsp "DB password: " DB_PASS; echo
      USE_DOCKER_DB=0
      # Auto create DB if possible (ignore failures)
      if [[ "$DB" == "mariadb" ]]; then
        mysql -u"$DB_USER" -p"$DB_PASS" -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\`;" || warn "Couldn't create DB (maybe not local?)"
      else
        PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -h "$DB_HOST" -c "CREATE DATABASE \"$DB_NAME\";" || warn "Couldn't create DB (maybe not local?)"
      fi
    else
      DB_NAME="${PROJECT}_db"
      DB_USER="${PROJECT}_user"
      DB_PASS="$(openssl rand -hex 8)"
      [[ "$DB" == "mariadb" ]] && DB_PORT="3306" || DB_PORT="5432"
      USE_DOCKER_DB=1
    fi
  fi

  # --- Port Selection ---
  if [[ "$WSS" == "nginx" ]]; then
    PORT=$((NGINX_PORT_START + RANDOM % 1000))
  else
    PORT=$((APACHE_PORT_START + RANDOM % 1000))
  fi

  # --- Extra Commands ---
  title "Extra Commands (optional)"
  pushd "$PROJECT_DIR" >/dev/null
  COMPOSER_CMDS=()
  if [[ -f "composer.json" ]]; then
    echo "composer.json found."
    echo "Enter composer commands to run after container starts (separate with ;):"
    echo "Examples: dump-autoload; test"
    read -rp "Composer commands: " ccmd
    [[ -n "$ccmd" ]] && IFS=';' read -ra COMPOSER_CMDS <<< "$ccmd"
  fi
  NPM_CMDS=()
  if [[ -f "package.json" ]]; then
    echo "package.json found."
    echo "Enter npm/yarn/pnpm commands (separate with ;):"
    read -rp "NPM commands: " ncmd
    [[ -n "$ncmd" ]] && IFS=';' read -ra NPM_CMDS <<< "$ncmd"
  fi
  ARTISAN_CMDS=()
  if [[ -f "artisan" ]]; then
    echo "artisan found."
    echo "Enter Laravel artisan commands (NO 'php artisan', just the command, e.g. migrate;db:seed):"
    read -rp "Artisan commands: " acmd
    [[ -n "$acmd" ]] && IFS=';' read -ra ARTISAN_CMDS <<< "$acmd"
  fi
  popd >/dev/null

  # --- .env Handling ---
  ENV_FILE=""
  if [[ -f "$PROJECT_DIR/.env" ]]; then ENV_FILE="$PROJECT_DIR/.env";
  elif [[ -f "$PROJECT_DIR/.env.example" ]]; then cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"; ENV_FILE="$PROJECT_DIR/.env";
  fi

  # Set LARAVEL_DB_CONNECTION for use in .env (mysql if mariadb, else as-is)
  if [[ "$DB" == "mariadb" ]]; then
    LARAVEL_DB_CONNECTION="mysql"
  else
    LARAVEL_DB_CONNECTION="$DB"
  fi

  if [[ -n "$ENV_FILE" ]]; then
    warn ".env found; auto-patching for DB..."
    if [[ "$DB" != "none" ]]; then
      sed -i "s/^DB_CONNECTION=.*/DB_CONNECTION=$LARAVEL_DB_CONNECTION/" "$ENV_FILE"
      sed -i "s/^DB_HOST=.*/DB_HOST=$DB_HOST/" "$ENV_FILE"
      sed -i "s/^DB_PORT=.*/DB_PORT=$DB_PORT/" "$ENV_FILE"
      sed -i "s/^DB_DATABASE=.*/DB_DATABASE=$DB_NAME/" "$ENV_FILE"
      sed -i "s/^DB_USERNAME=.*/DB_USERNAME=$DB_USER/" "$ENV_FILE"
      sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PASS/" "$ENV_FILE"
    fi
  fi

  # --- Document Root Detection ---
  WEBSERVER_ROOT="public"
  if [[ -f "$PROJECT_DIR/public/index.php" ]]; then WEBSERVER_ROOT="public";
  elif [[ -f "$PROJECT_DIR/index.php" ]]; then WEBSERVER_ROOT="."
  fi

  # --- NGINX/Apache Config Generation ---
  mkdir -p "$PROJECT_DIR/docker"

  # --- NGINX Configuration ---
  if [[ "$WSS" == "nginx" ]]; then
    NGINX_CONF="$PROJECT_DIR/docker/nginx.conf"
    cat > "$NGINX_CONF" <<EOF
server {
    listen 80 default_server;
    server_name localhost;
    root /var/www/html/$WEBSERVER_ROOT;
    index index.php index.html;
    location / {
        try_files \$uri \$uri/ /index.php?\$query_string;
    }
    location = /phpinfo.php {
        fastcgi_pass app:9000;
        fastcgi_index phpinfo.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME \$document_root/phpinfo.php;
    }
    location ~ \.php\$ {
        fastcgi_pass app:9000;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;
    }
    location ~ /\.ht {
        deny all;
    }
}
EOF
  fi

  # --- Apache Configuration ---
  if [[ "$WSS" == "apache" ]]; then
    APACHE_CONF="$PROJECT_DIR/docker/apache.conf"
    cat > "$APACHE_CONF" <<EOF
ServerRoot "/usr/local/apache2"
Listen 80
LoadModule mpm_event_module modules/mod_mpm_event.so
LoadModule dir_module modules/mod_dir.so
LoadModule mime_module modules/mod_mime.so
LoadModule rewrite_module modules/mod_rewrite.so
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_fcgi_module modules/mod_proxy_fcgi.so

ServerAdmin you@example.com
ServerName localhost

DocumentRoot "/var/www/html/$WEBSERVER_ROOT"
<Directory "/var/www/html/$WEBSERVER_ROOT">
    AllowOverride All
    Require all granted
    Options Indexes FollowSymLinks
    DirectoryIndex index.php
</Directory>

# Proxy PHP to app:9000 (php-fpm)
<FilesMatch \.php$>
    SetHandler "proxy:fcgi://app:9000"
</FilesMatch>

ErrorLog /proc/self/fd/2
CustomLog /proc/self/fd/1 common
EOF
  fi

  # --- Ensure phpinfo.php Exists ---
  if [[ ! -f "$PROJECT_DIR/${WEBSERVER_ROOT}/phpinfo.php" ]]; then
    mkdir -p "$PROJECT_DIR/$WEBSERVER_ROOT"
    echo "<?php phpinfo();" > "$PROJECT_DIR/${WEBSERVER_ROOT}/phpinfo.php"
  fi

  # --- Dockerfile Generation ---
    cat > "$PROJECT_DIR/docker/Dockerfile" <<EOF
FROM php:${PHPV}-fpm

# Install required dependencies for PHP extensions
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libxml2-dev \
    libicu-dev \
    libxslt-dev \
    libzip-dev \
    libpq-dev \
    libonig-dev \
    && apt-get clean

# Install PHP extensions
RUN docker-php-ext-install pdo pdo_mysql pdo_pgsql mysqli mbstring bcmath zip gd exif xsl opcache intl

# Enable PHP extensions
RUN docker-php-ext-enable pdo pdo_mysql pdo_pgsql mysqli mbstring bcmath zip gd exif xsl opcache intl
EOF

  # --- Docker Compose File Generation ---
  DOCKER_YML="$PROJECT_DIR/docker-compose.yml"
  cat > "$DOCKER_YML" <<EOF
services:
  app:
    build:
      context: .
      dockerfile: docker/Dockerfile
    image: php:${PHPV}-fpm
    container_name: ${PROJECT}_php
    volumes:
      - ./:/var/www/html
    working_dir: /var/www/html
    expose:
      - "9000"
    environment:
      - DB_CONNECTION=${LARAVEL_DB_CONNECTION}
      - DB_HOST=${DB_HOST}
      - DB_PORT=${DB_PORT}
      - DB_DATABASE=${DB_NAME}
      - DB_USERNAME=${DB_USER}
      - DB_PASSWORD=${DB_PASS}
EOF

  # Only include depends_on and db service if using Docker DB
  if [[ "$USE_DOCKER_DB" == "1" ]]; then
    cat >> "$DOCKER_YML" <<EOF
    depends_on:
      - db
EOF
  fi

  # Web server config (with custom mount for Apache)
  cat >> "$DOCKER_YML" <<EOF

  web:
    image: ${WEBSERVER_IMAGE}
    container_name: ${PROJECT}_${WSS}
    ports:
      - "${PORT}:80"
    depends_on:
      - app
    volumes:
      - ./:/var/www/html
EOF

  if [[ "$WSS" == "nginx" ]]; then
    cat >> "$DOCKER_YML" <<EOF
      - ./docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    command: ["nginx", "-g", "daemon off;"]
EOF
  elif [[ "$WSS" == "apache" ]]; then
    cat >> "$DOCKER_YML" <<EOF
      - ./docker/apache.conf:/usr/local/apache2/conf/httpd.conf:ro
    command: ["httpd-foreground"]
EOF
  fi

  # --- Add DB service if required ---
  if [[ "$USE_DOCKER_DB" == "1" ]]; then
    if [[ "$DB" == "mariadb" ]]; then
      cat >> "$DOCKER_YML" <<EOF

  db:
    image: mariadb:10.11
    restart: always
    environment:
      MARIADB_ROOT_PASSWORD: ${DB_PASS}
      MARIADB_DATABASE: ${DB_NAME}
      MARIADB_USER: ${DB_USER}
      MARIADB_PASSWORD: ${DB_PASS}
    ports:
      - "${DB_PORT}:3306"
    volumes:
      - db_data:/var/lib/mysql
EOF
    elif [[ "$DB" == "postgres" ]]; then
      cat >> "$DOCKER_YML" <<EOF

  db:
    image: postgres:16
    restart: always
    environment:
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
    ports:
      - "${DB_PORT}:5432"
    volumes:
      - db_data:/var/lib/postgresql/data
EOF
    fi

    cat >> "$DOCKER_YML" <<EOF

volumes:
  db_data:
EOF
  fi

  # --- Start Docker Compose Services ---
  title "Bringing up Docker Compose..."
  pushd "$PROJECT_DIR" >/dev/null
  detect_compose
  $DOCKER_COMPOSE_BIN up -d --build
  popd >/dev/null
  success "Project up and running!"

  # --- Set permissions if Laravel detected ---
  if [[ -d "$PROJECT_DIR/storage" ]] && [[ -d "$PROJECT_DIR/bootstrap/cache" ]]; then
    info "✱ Setting host-side write permissions on storage/ and bootstrap/cache/ …"
    chmod -R a+rw "$PROJECT_DIR/storage" "$PROJECT_DIR/bootstrap/cache" \
      || warn "⚠️  Could not chmod host directories; check your user permissions."
  fi

  # --- Run post-start commands ---
  for cmd in "${COMPOSER_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app composer $cmd
  done
  for cmd in "${NPM_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app npm $cmd
  done
  for cmd in "${ARTISAN_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app php artisan $cmd
  done

  # --- Summary Output ---
  info "======================================"
  info "Project: $PROJECT"
  info "Host directory: $PROJECT_DIR"
  info "Web: http://localhost:$PORT/"
  info "PHP Info: http://localhost:$PORT/phpinfo.php"
  if [[ "$DB" != "none" ]]; then
    info "DB Type: $DB  |  User: $DB_USER  |  Pass: $DB_PASS"
    info "DB Host: $DB_HOST:$DB_PORT  |  DB: $DB_NAME"
  fi
  info "--------------------------------------"
  info "Edit code directly in $PROJECT_DIR."
  info "Changes are live in the container!"
  info "Use main menu to start/stop/delete projects."
  info "======================================"
  pause
  main_menu
}

# ========== RECREATE EXISTING PROJECT ===========
recreate_existing_project() {
  list_projects
  read -rp "Project to recreate: " P
  PDIR="$PROJECTS_DIR/$P"
  
  # Check if the project directory exists
  if [[ ! -d "$PDIR" ]]; then
    warn "No such project."
    pause
    main_menu
    return
  fi
  
  # Confirm overwrite before proceeding
  read -rp "Are you sure you want to recreate this project and overwrite existing config? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    warn "Recreation cancelled."
    pause
    main_menu
    return
  fi

  # Remove existing Docker containers and volumes
  pushd "$PDIR" >/dev/null
  $DOCKER_COMPOSE_BIN down -v  # Remove containers and volumes
  popd >/dev/null
  
  success "Old containers and volumes removed."

  # Recreate the Docker environment (rebuild and restart)
  create_project

  success "Project recreated and running with new config."
  pause
  main_menu
}

# ========== START PROJECT ===========
start_existing() {
  list_projects
  PDIR="$PROJECTS_DIR/$project"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }

  pushd "$PDIR" >/dev/null
  detect_compose
  $DOCKER_COMPOSE_BIN up -d
  popd >/dev/null
  success "$project started."
  pause
  main_menu
}

# ========== STOP PROJECT ===========
stop_existing() {
  list_projects
  PDIR="$PROJECTS_DIR/$project"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }
  
  pushd "$PDIR" >/dev/null
  detect_compose
  $DOCKER_COMPOSE_BIN down
  popd >/dev/null
  success "$project stopped."
  pause
  main_menu
}

# ========== RESTART PROJECT ===========
restart_existing() {
  list_projects
  PDIR="$PROJECTS_DIR/$project"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }

  pushd "$PDIR" >/dev/null
  detect_compose
  $DOCKER_COMPOSE_BIN down
  $DOCKER_COMPOSE_BIN up -d --build
  popd >/dev/null
  success "$project restarted."
  pause
  main_menu
}

# ========== DELETE PROJECT ===========
delete_existing() {
  list_projects
  PDIR="$PROJECTS_DIR/$project"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }
  
  pushd "$PDIR" >/dev/null
  $DOCKER_COMPOSE_BIN down -v
  popd >/dev/null
  rm -rf "$PDIR"
  success "$project deleted (container and files removed)."
  pause
  main_menu
}

# ==================== ENTRY POINT ====================
main_menu
