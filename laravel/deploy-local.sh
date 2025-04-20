#!/bin/bash

set -e

# === Defaults ===
DEPLOY_PATH=$(pwd)
GIT_BRANCH="main"
PHP_BIN="php"
COMPOSER_BIN="composer"
PHP_FPM_SERVICE="php-fpm"
APP_ENV="dev"
RUN_FRESH=false
RUN_SEED=false
SKIP_TENANTS=false
FORCE_TENANTS=false
FORCE_ENABLED=false
EXTRA_COMMANDS=()
HAS_ERROR=false
START_TIME=$(date +%s)

# === Colors ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# === Helpers ===
log() { echo -e "${BLUE}➤ $1${NC}"; }
ok() { echo -e "${GREEN}✔ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() {
    echo -e "${RED}✖ $1${NC}"
    HAS_ERROR=true
}
section() { echo -e "\n${YELLOW}==> $1${NC}"; }

# === Parse CLI Args ===
for arg in "$@"; do
    case $arg in
    --path=*) DEPLOY_PATH="${arg#*=}" ;;
    --branch=*) GIT_BRANCH="${arg#*=}" ;;
    --php=*) PHP_BIN="${arg#*=}" ;;
    --composer=*) COMPOSER_BIN="${arg#*=}" ;;
    --php-fpm=*) PHP_FPM_SERVICE="${arg#*=}" ;;
    --env=*) APP_ENV="${arg#*=}" ;;
    --extra=*) IFS=';' read -ra EXTRA_COMMANDS <<<"${arg#*=}" ;;
    --fresh) RUN_FRESH=true ;;
    --seed) RUN_SEED=true ;;
    --force) FORCE_ENABLED=true ;;
    --skip-tenants) SKIP_TENANTS=true ;;
    --force-tenants) FORCE_TENANTS=true ;;
    --help)
        echo -e "${BLUE}Laravel Local Deployment Script${NC}"
        echo ""
        echo "Usage: ./deploy-local.sh [options]"
        echo ""
        echo "Options:"
        echo "  --path=/path/to/project        Laravel project root (default: pwd)"
        echo "  --branch=main                  Git branch to pull (default: main)"
        echo "  --php=php8.2                   PHP binary (default: php)"
        echo "  --composer=composer2           Composer binary (default: composer)"
        echo "  --php-fpm=php-fpm              PHP-FPM service name (default: php-fpm)"
        echo "  --env=dev|prod                 Laravel environment (default: dev)"
        echo "  --fresh                        Run migrate:fresh"
        echo "  --seed                         Run db:seed"
        echo "  --force                        Force artisan operations (only applies in prod)"
        echo "  --skip-tenants                 Skip tenant migrations/seeders"
        echo "  --force-tenants                Use tenants:migrate-fresh instead of migrate-job"
        echo "  --extra='cmd1;cmd2'            Extra shell commands to run"
        echo "  --help                         Show this help message"
        exit 0
        ;;
    esac
done

# Track if --branch was passed explicitly
BRANCH_EXPLICIT=false

# Re-parse args specifically to track --branch
for arg in "$@"; do
    [[ "$arg" == --branch=* ]] && BRANCH_EXPLICIT=true
done

# Apply dynamic fallback for APP_ENV=dev
if [[ "$APP_ENV" == "dev" && "$BRANCH_EXPLICIT" == false ]]; then
    GIT_BRANCH="development"
fi

# === Start ===
section "🔧 Starting deployment in: $DEPLOY_PATH"
cd "$DEPLOY_PATH" || {
    error "Invalid path: $DEPLOY_PATH"
    exit 1
}

# Validate Laravel project
[[ -f artisan && -f composer.json ]] || {
    error "Not a Laravel project (artisan or composer.json missing)"
    exit 1
}

# Git Pull
section "📥 Pulling latest code from branch: $GIT_BRANCH"
git pull origin "$GIT_BRANCH" || error "Git pull failed"

# Composer Install
section "📦 Installing PHP dependencies"
COMPOSER_FLAGS="--no-interaction --prefer-dist --optimize-autoloader"
[[ "$APP_ENV" == "prod" ]] && COMPOSER_FLAGS="$COMPOSER_FLAGS --no-dev"
$COMPOSER_BIN install $COMPOSER_FLAGS || error "Composer install failed"

# Frontend Build
if [[ -f package.json ]]; then
    section "🧱 Building frontend assets"
    npm install || error "NPM install failed"
    npm run build || error "NPM build failed"

    if [[ "$APP_ENV" == "prod" ]]; then
        log "🧹 Cleaning node_modules (prod mode)..."
        rm -rf node_modules
    else
        log "📦 Keeping node_modules (dev mode)..."
    fi
fi

# Laravel Cache & Optimize
if [[ "$APP_ENV" == "prod" ]]; then
    section "⚙️ Laravel Production Optimization"
    $PHP_BIN artisan optimize:clear || warn "optimize:clear failed"
    $PHP_BIN artisan filament:optimize-clear || warn "filament:optimize-clear failed"
    $PHP_BIN artisan filament:optimize || warn "filament:optimize failed"
    $PHP_BIN artisan optimize || warn "optimize failed"
else
    section "🧹 Clearing Laravel & Filament caches (dev)"
    $PHP_BIN artisan optimize:clear || warn "optimize:clear failed"
    $PHP_BIN artisan filament:optimize-clear || warn "filament:optimize-clear failed"
fi

# Migrations
MIGRATE_FORCE=""
[[ "$APP_ENV" == "prod" && "$FORCE_ENABLED" == true ]] && MIGRATE_FORCE="--force"

if $RUN_FRESH; then
    section "💣 Running migrate:fresh"
    $PHP_BIN artisan migrate:fresh $MIGRATE_FORCE || error "migrate:fresh failed"
else
    section "🗃️ Running migrate"
    $PHP_BIN artisan migrate $MIGRATE_FORCE || error "migrate failed"
fi

# Seeders
if $RUN_SEED; then
    section "🌱 Seeding database"
    $PHP_BIN artisan db:seed $MIGRATE_FORCE || warn "db:seed failed"
fi

# Horizon Restart
section "🔄 Restarting Laravel Horizon"
$PHP_BIN artisan horizon:terminate || warn "Horizon terminate failed"

# Scheduler Restart
section "🔄 Restarting Laravel Scheduler"
$PHP_BIN artisan schedule:interrupt || warn "Scheduler restart failed"

# Tenants
if ! $SKIP_TENANTS && $PHP_BIN artisan list --raw 2>/dev/null | grep -q "tenants:migrate-job"; then
    if $FORCE_TENANTS; then
        section "🌍 Running tenant fresh migrations"
        $PHP_BIN artisan tenants:migrate-fresh || warn "tenant fresh migration failed"
    else
        section "🌍 Running tenant migrations"
        $PHP_BIN artisan tenants:migrate-job || warn "tenant migrations failed"
    fi

    section "🌱 Running tenant seeders"
    $PHP_BIN artisan tenants:seeder-job || warn "tenant seeders failed"
else
    $SKIP_TENANTS && log "⏭️ Skipping tenant commands (--skip-tenants)"
fi

# PHP-FPM Reload
section "♻️ Reloading PHP-FPM: $PHP_FPM_SERVICE"
(
    flock -w 10 9 || exit 1
    sudo systemctl reload "$PHP_FPM_SERVICE" || warn "PHP-FPM reload failed"
) 9>/tmp/fpmlock

# Extra Commands
if [[ ${#EXTRA_COMMANDS[@]} -gt 0 ]]; then
    section "🚀 Running extra commands"
    for CMD in "${EXTRA_COMMANDS[@]}"; do
        echo -e "${BLUE}→ $CMD${NC}"
        eval "$CMD" || warn "Extra command failed: $CMD"
    done
fi

# Final Result
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

if [[ "$HAS_ERROR" == true ]]; then
    error "Deployment finished with issues. ⏱ Took ${TOTAL_TIME}s"
    exit 1
else
    ok "Deployment completed successfully! ⏱ Took ${TOTAL_TIME}s"
fi
