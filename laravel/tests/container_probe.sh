#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${AUTOMATION_DISPOSABLE_CONTAINER:-}" == yes && -f /run/.containerenv ]] || { echo 'Disposable rootless-container opt-in required' >&2; exit 4; }
export DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1
cp -a /portable-laravel /opt/laravel-toolkit
cd /tmp
umask 027
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 git ca-certificates

# This adapter drives actual daemons, not a real systemd instance. Timer/autostart
# lifecycle remains simulated and is reported explicitly by the outer harness.
dpkg-divert --local --rename --add /usr/bin/systemctl
cat > /usr/bin/systemctl <<'SH'
#!/bin/bash
set -e
case "${1:-}" in daemon-reload|daemon-reexec|--system|--version|preset|disable|mask|unmask|is-enabled) exit 0 ;; esac
operation="${1:-}"; shift || true
unit="${!#}"; unit="${unit%.service}"
case "$unit" in
    php*-fpm) version="${unit#php}"; version="${version%-fpm}"; pid="/run/php/php${version}-fpm.pid"
        case "$operation" in
            is-active) test -r "$pid" && kill -0 "$(cat "$pid")" ;;
            reload) kill -USR2 "$(cat "$pid")" ;;
            enable|start) if [[ "$*" == *--now* || "$operation" == start ]]; then mkdir -p /run/php; if ! test -r "$pid" || ! kill -0 "$(cat "$pid")" 2>/dev/null; then "php-fpm${version}" -D; fi; fi ;;
            *) exit 0 ;;
        esac ;;
    nginx)
        case "$operation" in is-active) test -r /run/nginx.pid && kill -0 "$(cat /run/nginx.pid)" ;; reload) nginx -s reload ;; enable|start) if [[ "$*" == *--now* || "$operation" == start ]]; then if ! test -r /run/nginx.pid || ! kill -0 "$(cat /run/nginx.pid)" 2>/dev/null; then nginx; fi; fi ;; esac ;;
    postgresql)
        version="$(find /etc/postgresql -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -1)"
        case "$operation" in is-active) pg_isready -q ;; enable|start) pg_ctlcluster "$version" main status >/dev/null 2>&1 || pg_ctlcluster "$version" main start ;; esac ;;
    firewalld) exit 3 ;;
    *) exit 0 ;;
esac
SH
chmod 755 /usr/bin/systemctl

provision=(bash /opt/laravel-toolkit/laravel-provision.sh --domain example.test --site-root /srv/laravel-fixture --database postgresql --database-name fixture_app --php-version 8.3 --scheduler --yes --approve-service-changes)
printf 'LARAVEL_STAGE=first-provision\n'
"${provision[@]}"
bash /opt/laravel-toolkit/laravel-provision.sh --init-config --yes
chown deploy:deploy /opt/laravel-toolkit/.env
runuser -u deploy -- python3 -B /opt/laravel-toolkit/scripts/validate.py > /tmp/laravel-offline-validation.json
python3 - <<'CHECK'
import json
report=json.load(open("/tmp/laravel-offline-validation.json"))
assert report["summary"]["fail"]==0
print("INDEPENDENT_UBUNTU_TESTS=yes")
CHECK
sha256sum /etc/nginx/conf.d/automation-laravel-*.conf > /tmp/config-before
"${provision[@]}"
sha256sum --check /tmp/config-before
nginx -t
php-fpm8.3 -tt
runuser -u postgres -- psql -Atqc "SELECT 1 FROM pg_database WHERE datname='fixture_app'" | grep -qx 1
printf 'FRESH_PROVISION=yes\nREPEAT_PROVISION=yes\nNATIVE_NGINX_FPM_POSTGRES=yes\nCONFIG_PRESERVED=yes\n'

printf 'LARAVEL_STAGE=framework-fixture\n'
runuser -u deploy -- composer create-project --prefer-dist --no-install --no-scripts --no-interaction laravel/laravel /tmp/laravel-source 12.0.0
runuser -u deploy -- sh -c 'cd /tmp/laravel-source && composer install --no-dev --no-scripts --no-interaction --prefer-dist'
cat > /tmp/laravel-source/package.json <<'JSON'
{"name":"deployment-fixture","version":"1.0.0","private":true,"scripts":{"production-build":"node -e \"require('fs').writeFileSync('public/built.txt','fixture')\""}}
JSON
chown deploy:deploy /tmp/laravel-source/package.json
runuser -u deploy -- sh -c 'cd /tmp/laravel-source && npm install --package-lock-only --ignore-scripts --no-audit --no-fund && git init -b main && git config user.name Fixture && git config user.email fixture@example.invalid && git add . && git commit -qm initial'
python3 - <<'PY'
import base64,os,pwd,json,hashlib
from pathlib import Path
root=Path('/srv/laravel-fixture');user=pwd.getpwnam('deploy')
environment=('APP_ENV=production\nAPP_DEBUG=false\nAPP_KEY=base64:'+base64.b64encode(os.urandom(32)).decode()+'\nAPP_URL=http://example.test\nDB_CONNECTION=sqlite\nDB_DATABASE=/srv/laravel-fixture/shared/database.sqlite\nCACHE_STORE=file\nSESSION_DRIVER=file\nQUEUE_CONNECTION=database\nLOG_CHANNEL=single\n')
for path,data in ((root/'shared/.env',environment),(root/'shared/database.sqlite','')):
    path.write_text(data);path.chmod(0o600);os.chown(path,user.pw_uid,user.pw_gid)
files={str(path.relative_to('/tmp/laravel-source/database/migrations')):hashlib.sha256(path.read_bytes()).hexdigest() for path in Path('/tmp/laravel-source/database/migrations').glob('*.php')}
manifest=Path('/tmp/reviewed-migrations.json')
manifest.write_text(json.dumps({'schema':1,'backward_compatible':True,'files':files}))
manifest.chmod(0o600);os.chown(manifest,user.pw_uid,user.pw_gid)
PY
deploy=(runuser -u deploy -- bash /opt/laravel-toolkit/laravel-deploy.sh --site-root /srv/laravel-fixture --domain example.test --repository /tmp/laravel-source --allow-local-repository --health-url http://127.0.0.1/up --build-script production-build --php-version 8.3 --fpm-service php8.3-fpm.service --approve-service-changes --migrations compatible --approve-migrations --backward-compatible --migration-manifest /tmp/reviewed-migrations.json --yes)
runuser -u deploy -- test -r /tmp/reviewed-migrations.json
printf 'LARAVEL_STAGE=first-deployment\n'
"${deploy[@]}"
first="$(readlink /srv/laravel-fixture/current)"
runuser -u deploy -- sh -c 'printf first-upload > /srv/laravel-fixture/shared/storage/app/public/upload.txt; cd /tmp/laravel-source; printf second > public/version.txt; git add .; git commit -qm second'
"${deploy[@]}"
second="$(readlink /srv/laravel-fixture/current)"
[[ "$first" != "$second" ]]
runuser -u deploy -- bash /opt/laravel-toolkit/laravel-deploy.sh --site-root /srv/laravel-fixture --rollback --fpm-service php8.3-fpm.service --approve-service-changes --yes
[[ "$(readlink /srv/laravel-fixture/current)" == "$first" ]]
grep -qx first-upload /srv/laravel-fixture/shared/storage/app/public/upload.txt
[[ -f /srv/laravel-fixture/current/public/built.txt ]]
printf 'REAL_LARAVEL_COMPOSER_NPM=yes\nATOMIC_RELEASES=yes\nDATABASE_MIGRATIONS=yes\nROLLBACK_HEALTH=yes\nSHARED_UPLOAD_PRESERVED=yes\nSYSTEMD_MANAGER=simulated-native-daemons\nACME_PUBLIC_ISSUANCE=unverified\n'
