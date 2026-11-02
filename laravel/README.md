# Portable Laravel server toolkit

Copy this entire folder to an Ubuntu Server or another repository. It uses no parent files, root `.env`, automation libraries, Forge account, subscription, token or endpoint. Run either Bash entrypoint by its absolute or relative path from any working directory. Python 3.9+, Bash and Ubuntu 22.04/24.04/26.04 on amd64/arm64 are supported provisioning targets; only Ubuntu 24.04 currently has native container integration evidence.

The two public entrypoints and Python bootstrap are Bash. Bundled standard-library Python handles bounded configuration parsing, HTTPS verification, filesystem receipts, locks and atomic symlink operations, avoiding shell evaluation and fragile data escaping. No pip dependencies or parent Python package is required.

```
laravel/
  laravel-provision.sh
  laravel-deploy.sh
  .env                       # private, ignored, initialized explicitly
  config/defaults.env
  lib/bootstrap.sh
  src/laravel_toolkit/
  templates/
  scripts/                   # internal launcher and independent test runners
  tests/
  docs/
```

## Configuration and prerequisites

```bash
bash laravel-provision.sh --help
bash laravel-provision.sh --init-config --dry-run
bash laravel-provision.sh --init-config --yes
```

The single toolkit configuration is `.env` beside these entrypoints. `config/defaults.env` is a public defaults template. Initialization merges missing fields, preserves existing bytes/values and writes mode 0600; configuration is parsed as allowlisted data, never sourced or expanded. CLI flags override configuration. Relative manifest paths resolve from this folder. No parent `.env` or `PYTHONPATH` is used. Run initialization as the user who will maintain the copied folder; keep it out of source control and release artifacts. Do not put application passwords in this file.

Each **application** separately retains its existing private `SITE_ROOT/shared/.env`, containing its production credentials and APP_KEY. The toolkit never generates or replaces that application configuration. The deploying user must own and be able to read the toolkit `.env`; root can read it for provisioning. For an existing server using another deployment account, set `LARAVEL_DEPLOY_USER` or pass `--deploy-user` explicitly.

Checks, help and dry runs never install dependencies or initialize configuration. If Python is absent, an approved `--yes` operation can bootstrap it using Ubuntu's configured native repositories, using root or available `sudo -n`. Provisioning installs its exact missing package list after service-change approval. Deployment preflights Git, Composer, PHP and, unless `--frontend=none`, Node/npm; approved installation uses existing administrator sudo policy and native packages only. `--no-auto-prerequisites` disables deployment bootstrap. Missing privilege or unavailable versions fails with instructions; no repository is silently added. No passwords are passed to sudo. APT uses a bounded native lock wait rather than retrying arbitrary failed transactions.

## Provision directly

Review the plan first, then run provisioning as root through your normal administrator access:

```bash
bash laravel-provision.sh --domain=example.com --database=postgresql --database-name=example_app --dry-run
sudo bash laravel-provision.sh --domain=example.com --database=postgresql --database-name=example_app --yes --approve-service-changes
```

Default site directory: `/var/www/DOMAIN`; account: `deploy`; database/cache/queue: **none**. Native PHP defaults are 8.1 (22.04), 8.3 (24.04), 8.5 (26.04), always checked against actual enabled package availability. These defaults do not establish application compatibility. Choose a supported application/OS/PHP combination. `--php-version=8.5` on Ubuntu 24.04 will fail unless the version is actually available; an external repository requires a reviewed `--php-repository` JSON manifest and `--approve-repository` (see [operations](docs/operations.md)).

Provisioning prepares Nginx, a dedicated PHP-FPM pool, Composer, Node/npm, scoped service reload permission and log rotation. Only the selected MariaDB/PostgreSQL and Redis/Valkey are installed. `--database-name` creates the named database only; configure an application-specific least-privilege role and credentials separately using your secret-management procedure. Existing users, websites, databases and service data are preserved; conflicting site configuration or ownership is refused. Working configurations are tracked by private hash receipts and backed up before replacement; subsequent manual edits require review. Interrupted file transactions recover only unchanged receipt-owned output.

Optional flags include `--queue=queue|horizon`, `--scheduler`, `--firewall`, `--harden-ssh --admin-user=ADMIN --confirmed-admin-key-access`, and `--tls-email=ADMIN_EMAIL --approve-tls`. SSH requires an existing private authorized_keys file and independently verified access. Firewall changes are additive and preserve discovered SSH ports. Service changes require `--approve-service-changes`. TLS uses Certbot webroot, requires public DNS/network access, and preserves existing HTTPS across repeated provisioning. Public certificate issuance, administrator SSH access, firewall behavior and real systemd session/timer operation require a disposable VM/staging server review before production adoption.

## Provision using a reviewed HTTPS script

```bash
sudo bash laravel-provision.sh --provision-url=https://your-domain.example/provision.sh --sha256=INDEPENDENTLY_VERIFIED_SHA256 --yes
# Inspect the saved private script identified in /var/lib/automation-toolkit/laravel/external/.
sudo bash laravel-provision.sh --provision-url=https://your-domain.example/provision.sh --sha256=INDEPENDENTLY_VERIFIED_SHA256 --yes --allow-external-code --approve-service-changes
```

Use a real public HTTPS destination and independently verified checksum, not the illustrative domain/checksum. URL credentials, query tokens, Forge endpoints, private/reserved IPs, redirects, invalid TLS and oversized responses are rejected. DNS is validated and pinned for the download. Content must match SHA-256 and pass UTF-8/shebang/Bash syntax validation before review; syntax/checksum do not prove semantic safety. No pipe-to-Bash. `--check` verifies without saving/executing; `--dry-run` makes no request. Execution needs the separate explicit authorization flags. Identical completed scripts are skipped; failed/interrupted execution requires inspection and `--retry-external`. An arbitrary external script's idempotency and side effects remain the administrator's responsibility. Status logs never contain credentials or external script output.

## Deploy and roll back

Deploy as the dedicated account, with trusted Git host keys/repository access already established and a private production `shared/.env` supplied. Deployment also works on compatible servers provisioned by other tools; there is no provisioning URL or provisioning receipt dependency.

```bash
bash laravel-deploy.sh --domain=example.com --repository=git@github.com:owner/project.git --health-url=http://127.0.0.1/up --dry-run
bash laravel-deploy.sh --domain=example.com --repository=git@github.com:owner/project.git --health-url=http://127.0.0.1/up --php-version=8.3 --fpm-service=php8.3-fpm.service --approve-service-changes --yes
bash laravel-deploy.sh --domain=example.com --rollback --fpm-service=php8.3-fpm.service --approve-service-changes --yes
```

```
SITE_ROOT/
  current -> releases/RELEASE/
  releases/RELEASE/
  shared/.env
  shared/storage/
```

A private lock prevents concurrent deployments. Each candidate is a fresh Git checkout pinned to the resolved branch commit, uses `composer install` with the committed lockfile and platform checks, and links persistent environment/storage. Git authentication never accepts fingerprints automatically. The actual npm `build` script is used when present; otherwise select `--build-script=ACTUAL_NAME` or explicitly `--frontend=none`. npm uses `ci`; pnpm/yarn require their corresponding lockfile, pinned packageManager and an already installed reviewed Corepack. Native Node/npm may not meet a modern project's engine requirements; provide a reviewed supported runtime where needed. Arbitrary extra build hooks are not supported. Dependency scripts are application code: deploy only trusted repositories/lockfiles.

Available Artisan cache commands and production environment are validated before activation. The current symlink switches atomically, services reload only when selected/approved, then a bounded proxy-free loopback health request checks HTTP 200 with the configured domain Host header. Use an appropriate readiness route; health requests never follow redirects. Select the PHP version used by your application, FPM unit and queue mode consistently. `--queue=queue|horizon` uses the real Artisan restart/terminate command; `--queue-service` additionally starts an exact toolkit unit with scoped privilege. Queue lifecycle must be verified on the target server.

Post-activation failure restores the prior release and checks it again. Failed candidates are retained for inspection. `--recover` reconciles an interrupted activation receipt without overwriting unrelated changes. Retention defaults to five ready releases (minimum two), preserves active/previous releases, and deletes only unchanged receipt-owned releases. Failed/unowned/edited directories are retained. Rollback never changes shared storage, secrets or database schema. New release code/static assets are readable by the web server; environment/state/receipts remain private. `bootstrap/cache` is private (0700) and its generated PHP files are mode 0600 because compiled configuration can contain secrets. PHP-FPM and queue/scheduler processes therefore run as the deployment account.

Migrations default to **disabled**. Compatible migrations require `--migrations=compatible --approve-migrations --backward-compatible --migration-manifest=PATH`. The reviewed JSON manifest must match every migration's exact relative filename and SHA-256 (see operations). The application must support isolated migration locking with a working cache lock backend. Use expand-and-contract changes; destructive schema changes require a separately reviewed maintenance operation. Symlink rollback cannot undo database migrations.

For SSH/CI, execute the same command remotely as the deployment account using a reviewed script path and trusted host keys. Store CI credentials in your CI secret store. No Forge API credentials or public shell webhook are needed.

## Independent tests

```bash
python3 scripts/validate.py
python3 scripts/podman_test.py --allow-install --allow-pull --output="$HOME/.local/state/portable-laravel-tests"
```

Run these paths **inside the copied folder**; no parent code is imported. Offline tests use temporary sites, real temporary Git and explicitly simulated commands to test failures, configuration preservation, recovery, locks and rollback. The Podman runner requires local rootless Podman, explicit package/dependency download authorization and an Ubuntu image (pull opt-in). It copies only this folder, excludes `.env`, keys and caches, mounts that copy read-only, and runs from `/tmp` after copying it inside the container. Native packages, official Laravel skeleton/dependencies, Composer/npm/Artisan, Nginx/PHP-FPM and PostgreSQL execute in the disposable container. The systemd manager is simulated; daemons are real. Fixture accounts/data are disposable. Teardown is verified. See [verification](docs/verification.md) for exact results and remaining gates.

The optional parent `setup.sh laravel provision|deploy ...` launcher delegates to these entrypoints; it is never needed. Templates, Python stdlib helpers, configuration, test harness and documentation are all bundled. Removed historical server/deploy/Horizon/scheduler/Docker/renamer scripts have no runtime role. See [reference review](docs/references.md).
