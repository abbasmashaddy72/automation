#!/usr/bin/env bash
set -euo pipefail

# ============ CONFIG =============
PROJECTS_DIR="${HOME}/docker-projects"
DOCKER_COMPOSE_BIN="docker compose" # Compose v2 (preferred). Change to "docker-compose" for v1.
SUPPORTED_PHP_VERSIONS=("5.6" "7.2" "7.4" "8.0" "8.1" "8.2" "8.3" "8.4")
SUPPORTED_WEBSERVERS=("nginx" "apache")
SUPPORTED_DBS=("mariadb" "postgres" "none")
NGINX_PORT_START=8080
APACHE_PORT_START=9080

# ========== FUNCTIONS =============

pause() { read -rp "Press Enter to continue..."; }

title() { echo -e "\n\033[1;36m$*\033[0m"; }
info()  { echo -e "\033[1;34m$*\033[0m"; }
warn()  { echo -e "\033[1;33m$*\033[0m"; }
err()   { echo -e "\033[1;31m$*\033[0m"; }
success(){ echo -e "\033[1;32m$*\033[0m"; }

# --------- Main Menu -----------
main_menu() {
  clear
  title "🟦 PHP Docker Project Wizard"
  info "This tool will create, run, or remove isolated PHP dev environments using Docker!"
  echo "1) Create a new project"
  echo "2) Start an existing project"
  echo "3) Stop an existing project"
  echo "4) Delete an existing project"
  echo "5) List projects"
  echo "6) Quit"
  read -rp "Choose an option [1-6]: " opt
  case "$opt" in
    1) create_project ;;
    2) start_existing ;;
    3) stop_existing ;;
    4) delete_existing ;;
    5) list_projects ; pause ; main_menu ;;
    6) exit 0 ;;
    *) warn "Invalid input!" ; pause ; main_menu ;;
  esac
}

list_projects() {
  title "Existing Docker Projects"
  if [[ ! -d "$PROJECTS_DIR" ]] || [[ -z "$(ls -A $PROJECTS_DIR 2>/dev/null)" ]]; then
    echo "No projects found in $PROJECTS_DIR."
  else
    ls "$PROJECTS_DIR"
  fi
}

# --------- Create Project --------
create_project() {
  mkdir -p "$PROJECTS_DIR"
  title "🆕 New Project Setup"
  # Project Name
  while true; do
    read -rp "Enter project name (no spaces): " PROJECT
    [[ "$PROJECT" =~ ^[A-Za-z0-9_-]+$ ]] || { warn "Only letters, numbers, - and _ allowed."; continue; }
    PROJECT_DIR="$PROJECTS_DIR/$PROJECT"
    [[ -d "$PROJECT_DIR" ]] && { warn "That project exists. Start/stop/delete from main menu!"; main_menu; }
    break
  done

  # Code Source
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
      # Nothing, already created
      ;;
    *) warn "Invalid input!"; rm -rf "$PROJECT_DIR"; main_menu ;;
  esac

  # PHP Version
  title "Choose PHP version"
  select PHPV in "${SUPPORTED_PHP_VERSIONS[@]}"; do
    [[ -n "$PHPV" ]] && break
    warn "Invalid selection."
  done

  # Web Server
  title "Choose web server"
  select WSS in "${SUPPORTED_WEBSERVERS[@]}"; do
    [[ -n "$WSS" ]] && break
    warn "Invalid selection."
  done

  # DB
  title "Database Engine"
  select DB in "${SUPPORTED_DBS[@]}"; do
    [[ -n "$DB" ]] && break
    warn "Invalid selection."
  done

  # DB Details (local or container)
  DB_HOST="db"
  DB_PORT="" DB_NAME="" DB_USER="" DB_PASS=""
  if [[ "$DB" == "mariadb" || "$DB" == "postgres" ]]; then
    echo "Where is your database?"
    echo "1) Use separate Docker DB (self-contained)"
    echo "2) Connect to existing local DB (host machine)"
    read -rp "Choose [1-2]: " dbwhere
    if [[ "$dbwhere" == "2" ]]; then
      DB_HOST="host.docker.internal"
      if [[ "$DB" == "mariadb" ]]; then DB_PORT="3306"; else DB_PORT="5432"; fi
      read -rp "DB name: " DB_NAME
      read -rp "DB user: " DB_USER
      read -rsp "DB password: " DB_PASS; echo
      # Auto create db if possible
      if [[ "$DB" == "mariadb" ]]; then
        mysql -u"$DB_USER" -p"$DB_PASS" -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;" || warn "Couldn't create DB (maybe not local?)"
      else
        PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -h "$DB_HOST" -c "CREATE DATABASE $DB_NAME;" || warn "Couldn't create DB (maybe not local?)"
      fi
    else
      DB_NAME="${PROJECT}_db"
      DB_USER="${PROJECT}_user"
      DB_PASS="$(openssl rand -hex 8)"
      [[ "$DB" == "mariadb" ]] && DB_PORT="3306" || DB_PORT="5432"
    fi
  fi

  # Nginx/Apache Port
  if [[ "$WSS" == "nginx" ]]; then
    PORT=$((NGINX_PORT_START + RANDOM % 1000))
  else
    PORT=$((APACHE_PORT_START + RANDOM % 1000))
  fi

  # Composer/NPM Commands
  title "Extra Commands (optional)"
  echo "Detecting Composer & NPM..."
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
  # Artisan
  ARTISAN_CMDS=()
  if [[ -f "artisan" ]]; then
    echo "artisan found."
    echo "Enter Laravel artisan commands (NO 'php artisan', just the command, e.g. migrate;db:seed):"
    read -rp "Artisan commands: " acmd
    [[ -n "$acmd" ]] && IFS=';' read -ra ARTISAN_CMDS <<< "$acmd"
  fi
  popd >/dev/null

  # .env Handling
  ENV_FILE=""
  if [[ -f "$PROJECT_DIR/.env" ]]; then ENV_FILE="$PROJECT_DIR/.env";
  elif [[ -f "$PROJECT_DIR/.env.example" ]]; then cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"; ENV_FILE="$PROJECT_DIR/.env";
  fi
  if [[ -n "$ENV_FILE" ]]; then
    warn ".env found; auto-patching for DB..."
    if [[ "$DB" != "none" ]]; then
      sed -i "s/^DB_CONNECTION=.*/DB_CONNECTION=$DB/" "$ENV_FILE"
      sed -i "s/^DB_HOST=.*/DB_HOST=$DB_HOST/" "$ENV_FILE"
      sed -i "s/^DB_PORT=.*/DB_PORT=$DB_PORT/" "$ENV_FILE"
      sed -i "s/^DB_DATABASE=.*/DB_DATABASE=$DB_NAME/" "$ENV_FILE"
      sed -i "s/^DB_USERNAME=.*/DB_USERNAME=$DB_USER/" "$ENV_FILE"
      sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PASS/" "$ENV_FILE"
    fi
  fi

  # Nginx/Apache Host root
  WEBSERVER_ROOT="public"
  if [[ -f "$PROJECT_DIR/public/index.php" ]]; then WEBSERVER_ROOT="public";
  elif [[ -f "$PROJECT_DIR/index.php" ]]; then WEBSERVER_ROOT="."
  fi

  # Docker Compose YAML
  DOCKER_YML="$PROJECT_DIR/docker-compose.yml"
  cat > "$DOCKER_YML" <<EOF
version: "3.8"
services:
  app:
    image: php:${PHPV}-fpm
    container_name: ${PROJECT}_php
    volumes:
      - ./:/var/www/html
    working_dir: /var/www/html
    environment:
      - DB_CONNECTION=${DB}
      - DB_HOST=${DB_HOST}
      - DB_PORT=${DB_PORT}
      - DB_DATABASE=${DB_NAME}
      - DB_USERNAME=${DB_USER}
      - DB_PASSWORD=${DB_PASS}
    depends_on:
EOF

  if [[ "$DB" == "mariadb" ]]; then
    cat >> "$DOCKER_YML" <<EOF
      - db
EOF
  elif [[ "$DB" == "postgres" ]]; then
    cat >> "$DOCKER_YML" <<EOF
      - db
EOF
  else
    echo "      # none" >> "$DOCKER_YML"
  fi

  # Webserver
  cat >> "$DOCKER_YML" <<EOF

  web:
    image: ${WSS}:latest
    container_name: ${PROJECT}_${WSS}
    ports:
      - "${PORT}:80"
    volumes:
      - ./:/var/www/html
EOF
  if [[ "$WSS" == "nginx" ]]; then
    cat >> "$DOCKER_YML" <<EOF
    depends_on:
      - app
    command: [ "nginx", "-g", "daemon off;" ]
EOF
  fi

  # DB service (if any)
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

  # Volumes
  if [[ "$DB" == "mariadb" || "$DB" == "postgres" ]]; then
    cat >> "$DOCKER_YML" <<EOF

volumes:
  db_data:
EOF
  fi

  # PHP Info File
  if [[ ! -f "$PROJECT_DIR/${WEBSERVER_ROOT}/phpinfo.php" ]]; then
    mkdir -p "$PROJECT_DIR/$WEBSERVER_ROOT"
    echo "<?php phpinfo();" > "$PROJECT_DIR/${WEBSERVER_ROOT}/phpinfo.php"
  fi

  # Compose up
  title "Bringing up Docker Compose..."
  pushd "$PROJECT_DIR" >/dev/null
  $DOCKER_COMPOSE_BIN up -d --build
  popd >/dev/null
  success "Project up and running!"

  # Post-Start Commands
  CONTAINER_NAME="${PROJECT}_php"
  for cmd in "${COMPOSER_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app composer $cmd
  done
  for cmd in "${NPM_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app npm $cmd
  done
  for cmd in "${ARTISAN_CMDS[@]}"; do
    $DOCKER_COMPOSE_BIN exec app php artisan $cmd
  done

  # Summary
  info "======================================"
  info "Project: $PROJECT"
  info "Host directory: $PROJECT_DIR"
  info "Web: http://localhost:$PORT/"
  info "PHP info: http://localhost:$PORT/phpinfo.php"
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

# ------------- Start/Stop/Delete -------------

start_existing() {
  list_projects
  read -rp "Project to start: " P
  PDIR="$PROJECTS_DIR/$P"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }
  pushd "$PDIR" >/dev/null
  $DOCKER_COMPOSE_BIN up -d
  popd >/dev/null
  success "$P started."
  pause
  main_menu
}

stop_existing() {
  list_projects
  read -rp "Project to stop: " P
  PDIR="$PROJECTS_DIR/$P"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }
  pushd "$PDIR" >/dev/null
  $DOCKER_COMPOSE_BIN down
  popd >/dev/null
  success "$P stopped."
  pause
  main_menu
}

delete_existing() {
  list_projects
  read -rp "Project to delete: " P
  PDIR="$PROJECTS_DIR/$P"
  [[ -d "$PDIR" ]] || { warn "No such project."; pause; main_menu; }
  pushd "$PDIR" >/dev/null
  $DOCKER_COMPOSE_BIN down -v
  popd >/dev/null
  rm -rf "$PDIR"
  success "$P deleted (container and files removed)."
  pause
  main_menu
}

# ==================== ENTRY ====================
main_menu

