---
title: Laravel Deploy & Horizon Automation
description: A complete Laravel deployment and queue management toolkit using Bash scripts for dev, production, and CI/CD.
---

# 🚀 Laravel Deploy & Horizon Automation

Managing Laravel deployments and queues shouldn’t be a pain. This toolkit includes two powerful Bash scripts:

- `deploy-local.sh`: A full deployment CLI for local & production use
- `horizonctl.sh`: A robust Laravel Horizon Supervisor manager

Together, they automate everything from Git pulls, migrations, seeding, Horizon control, and PHP-FPM reloading.

---

## 🧰 Scripts Included

| Script            | Description                                             |
| ----------------- | ------------------------------------------------------- |
| `deploy-local.sh` | Laravel deploy script with env-aware operations         |
| `horizonctl.sh`   | Horizon setup via Supervisor, including restart/removal |

---

## ✨ Key Features

- ✅ Auto-detects environment via `--env=dev|prod`
- 🔁 Dynamically switches Git branch (`main`/`development`)
- 💾 Runs migrations, seeders, and tenant commands
- 🔐 Respects `--force` for production safety
- ⚙️ Fully manages Laravel Horizon with Supervisor
- 🚀 Perfect for Git deployments or local dev
- 🧩 Extensible via `--extra` commands

---

## ⚙️ CLI Options – `deploy-local.sh`

Make the script executable:

```bash
chmod +x deploy-local.sh
```

Run it:

```bash
./deploy-local.sh --env=prod --force
```

| Flag                      | Description                                             |
| ------------------------- | ------------------------------------------------------- |
| `--path=/var/www/laravel` | Laravel project path (default: current dir)             |
| `--branch=main`           | Git branch to pull (defaults to `development` if `dev`) |
| `--env=dev \| prod`       | Laravel environment                                     |
| `--php=php8.2`            | PHP binary to use                                       |
| `--composer=composer2`    | Composer binary to use                                  |
| `--php-fpm=php-fpm`       | PHP-FPM service to reload                               |
| `--fresh`                 | Run `migrate:fresh`                                     |
| `--seed`                  | Run `db:seed`                                           |
| `--force`                 | Add `--force` to artisan commands in prod               |
| `--skip-tenants`          | Skip tenant migration & seeders                         |
| `--force-tenants`         | Use `tenants:migrate-fresh` instead of `migrate-job`    |
| `--extra='cmd1;cmd2'`     | Run extra shell commands                                |
| `--help`                  | Show help                                               |

---

## 🔄 Example Workflows

### ✅ Dev Deploy

```bash
./deploy-local.sh --env=dev
```

### ✅ Production Deploy

```bash
./deploy-local.sh --env=prod --fresh --seed --force
```

### ✅ Skip Tenants

```bash
./deploy-local.sh --env=prod --skip-tenants
```

### ✅ With Extra Commands

```bash
./deploy-local.sh --env=prod --extra="php artisan queue:restart;php artisan storage:link"
```

---

## ⚙️ CLI Options – `horizonctl.sh`

```bash
chmod +x horizonctl.sh
./horizonctl.sh --env=production --force
```

| Flag                      | Description                                 |
| ------------------------- | ------------------------------------------- |
| `--path=/path/to/project` | Path to Laravel project                     |
| `--env=staging`           | Environment suffix for supervisor config    |
| `--remove`                | Remove Supervisor config and stop Horizon   |
| `--status`                | Only show Horizon status                    |
| `--wait-seconds=5`        | Delay after supervisor reload (default: 2s) |
| `--force`                 | Run non-interactively                       |
| `--help`                  | Show help message                           |

---

## 🛠 Horizonctl Usage Examples

### 🌐 Setup for Environment

```bash
./horizonctl.sh --env=staging
```

### 📁 Setup Another Laravel Project

```bash
./horizonctl.sh --path=/var/www/my-app
```

### ⚡ CI/CD Compatible

```bash
./horizonctl.sh --path=/var/www/my-app --env=production --force
```

### ❌ Remove Horizon Config

```bash
./horizonctl.sh --remove --env=staging
```

### ✅ Check Status

```bash
./horizonctl.sh --status --env=production
```

---

## 🧱 Directory Structure

No manual config required — Horizon logs and Supervisor `.ini` are auto-generated:

```txt
your-laravel-project/
├── artisan
├── logs/
│   └── horizon.log
```

Supervisor config:

```txt
/etc/supervisord.d/horizon_{project}_{env}.ini
```

---

## 🧪 CI/CD Deploy Example

```bash
#!/bin/bash
git pull origin main
./deploy-local.sh --env=prod --force
./horizonctl.sh --env=prod --path=/var/www/laravel --force
```

---

## 💬 Feedback & Contributions

Have ideas or want to improve it?

- Fork this repo
- Submit PRs
- Open issues

We love community ❤️

---

## 🔐 License

MIT — Use it, extend it, share it.

---

## 🧡 Thanks!

Built by Laravel developers, for Laravel developers.
Feel free to fork it, improve it, and make Horizon dev-life easier for everyone.

Happy queuing ⚡
