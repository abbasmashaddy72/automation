---
title: 🚀 Arch Linux Developer Automation Setup
description: Automate your complete Arch Linux workstation for Laravel, Valet, Git, databases, dev tools, and more with modular bash scripts.
---

# 🖥️ Arch Linux – Complete Developer Setup Automation

A modular, bash-powered system to fully automate your **Laravel development environment** on **Arch Linux/Manjaro** (and all Arch-based distros!), covering:

- ✅ Git identity and credential configuration
- 🧠 Zsh/Fish dev-friendly aliases and helpers
- 🐘 PHP + Composer + Valet + Valkey (Redis-compatible) installation
- 🧩 Laravel-ready folder scaffolding
- 🛠 System tweaks and SSD optimizations
- 📦 IDEs, browsers, productivity tools
- 🔐 MariaDB + PostgreSQL secure setup
- 🔌 Udev rules for Android & iOS
- 🤖 Ollama + Open WebUI (multi-model, local LLM interface)
- 📝 Interactive post-setup checklist

---

## ⚠️ Platform Safety

All scripts **refuse to run** on any OS except **Arch Linux, Manjaro, and other Arch-based distros**.
Strictly enforced via `lib/lib-platform.sh`.

---

## 📁 Directory Structure

```
archlinux/
├── 01-system-setup.sh               # System optimizations, UFW, SSD, GRUB, AUR support
├── 02-install-packages.sh           # Developer tools, browsers, AUR helper, fonts, VirtualBox, etc.
├── 03-git-setup.sh                  # Git install, credential manager, backup/rollback, config
├── 04-shellrc-dev-setup.sh          # Zsh/Fish Laravel/PHP aliases and dev helpers
├── 05-mariadb-setup.sh              # MariaDB install, enable, secure, skip if running
├── 06-postgres-setup.sh             # PostgreSQL install, password set, verify
├── 07-php-valet-valkey-setup.sh     # PHP (latest), Composer, Valet, Valkey (Redis), Node.js/NPM
├── 08-project-sites-setup.sh        # Laravel project dirs, valet park, customizable location
├── 09-taskbar-setup.sh              # KDE taskbar dev app pinning, backup/restore
├── 10-udev-rules-setup.sh           # Android/iOS USB rules, interactive/auto
├── 11-ollama-openwebui-setup.sh     # Ollama LLM, Open WebUI, multi-model install, uninstall
├── 12-setup-checklist.sh            # Interactive, post-setup desktop/dev checklist
└── ../lib/
    ├── lib-aur-helper.sh            # AUR helper abstraction
    ├── lib-logger.sh                # Centralized logger for all scripts
    └── lib-platform.sh              # Platform guard: Arch/Manjaro only
```

---

## ✅ Features & Usage (Per Script)

---

### 01-system-setup.sh — Features & Usage

Automates core Arch/Manjaro system setup for devs. Handles mirrors, upgrades, firewall, SSD trim, swappiness, GRUB tweaks, language tools, and AUR support — all idempotent and safe.

#### 🚀 Features

- Fastest `pacman` mirror selection (`pacman-mirrors`)
- Full system package upgrade
- Enables SSD TRIM (`fstrim.timer`)
- Swappiness set to 10 for devs
- Installs & enables UFW firewall (+ GUFW GUI)
- GRUB “quiet splash” boot fix
- Installs spelling/thesaurus/grammar tools
- Enables AUR and auto-update checks in Pamac
- Platform guard: runs _only_ on Arch/Manjaro
- Logs everything

#### ⚡ Usage

```bash
./01-system-setup.sh
```

---

### 02-install-packages.sh — Features & Usage

One-command installer for all your dev/daily apps: IDEs, browsers, DB tools, virtualization, fonts, remote tools, and more. Handles official repo and AUR with summary logs and idempotency.

#### 🚀 Features

- Installs a full suite of developer essentials (IDEs, browsers, DB clients, fonts, VMs, remote access, password managers, etc.)
- Detects or auto-installs an AUR helper (yay, pikaur, paru)
- Skips already-installed packages, never double-installs
- Handles both repo and AUR packages
- Summarizes everything installed/skipped/failed
- Adds user to `vboxusers` group for VirtualBox if needed
- Runs only on Arch-based distros
- Logs for troubleshooting

#### ⚡ Usage

```bash
./02-install-packages.sh
```

---

### 03-git-setup.sh — Features & Usage

Automates Git installation, credential management, config, and backups — with interactive prompts and instant rollback.

#### 🚀 Features

- Installs Git (repo first, AUR fallback)
- Sets up Git Credential Manager (secure credential storage)
- Prompts for username/email (validates both)
- Backs up existing `.gitconfig` (timestamped) before any changes
- Rollback: `--rollback` instantly restores the last backup
- Idempotent: never duplicates config or prompts if already set
- Only runs on Arch-based distros
- Logs all actions

#### ⚡ Usage

```bash
# Set up and configure Git
./03-git-setup.sh

# Roll back to your previous .gitconfig
./03-git-setup.sh --rollback
```

---

### 04-shellrc-dev-setup.sh — Features & Usage

Boost your shell for Laravel/PHP dev. Adds aliases, helpers, and Composer bin to Zsh or Fish. Backs up configs, is safe for reruns, and logs everything.

#### 🚀 Features

- **Auto-detects your shell** (supports Zsh and Fish).
- Adds **Laravel/PHP helper aliases and functions** (`artisan`, `vbin`, `pint`, `sail`, `fixer`, `pest`, `phpunit`).
- Adds **Composer global bin** to your PATH—only if missing.
- **Backs up your config** before any change (timestamped).
- **Idempotent:** Won’t duplicate if re-run.
- **Warns & exits** if not using Zsh or Fish.
- **Logs all actions.**

#### ⚡ Usage

```bash
./04-shellrc-dev-setup.sh
```

---

### 05-mariadb-setup.sh — Features & Usage

Handles MariaDB server install, initialization, service enable, root password security, and uninstall/cleanup.

#### 🚀 Features

- Installs MariaDB server (idempotent)
- Initializes DB if needed
- Enables & starts the MariaDB service
- Secure installation with **interactive password prompt** for root
- Enforces root password (even if secure install fails)
- Prints MariaDB version and service status
- **Uninstall/cleanup:** `--uninstall` flag fully removes MariaDB and data
- Logs every step

#### ⚡ Usage

```bash
./05-mariadb-setup.sh

# To uninstall:
./05-mariadb-setup.sh --uninstall
```

---

### 06-postgres-setup.sh — Features & Usage

Installs PostgreSQL, initializes, enables service, prompts for root password, and supports uninstall.

#### 🚀 Features

- Installs PostgreSQL (idempotent)
- Initializes the DB cluster if needed
- Enables and starts the PostgreSQL service
- Prompts to set/confirm password for `postgres` user
- Shows running version and service status
- **Uninstall:** `--uninstall` removes PostgreSQL and data
- Logs all actions

#### ⚡ Usage

```bash
./06-postgres-setup.sh

# To uninstall:
./06-postgres-setup.sh --uninstall
```

---

### 07-php-valet-valkey-setup.sh — Features & Usage

Automates the installation and setup of PHP, Composer, Laravel Valet, Valkey (Redis replacement), Node/NPM/NVM. Rollback/uninstall supported.

#### 🚀 Features

- Installs latest **PHP** from Arch repo
- Installs **Composer** (global PHP package manager)
- Installs **Laravel Valet** for local Laravel dev
- Installs **Valkey** (modern Redis alternative)
- Installs **Node.js**, **npm**, and **nvm**
- Adds Composer global bin to shell config (if missing)
- Applies `zzz-custom.ini` for PHP tweaks
- **Uninstall:** `--uninstall` removes all installed tools/configs
- Idempotent and logs everything

#### ⚡ Usage

```bash
./07-php-valet-valkey-setup.sh
./07-php-valet-valkey-setup.sh --uninstall
```

---

### 08-project-sites-setup.sh — Features & Usage

Sets up a Laravel project directory tree and “parks” folders for Valet. Customizable location.

#### 🚀 Features

- **Creates a full project folder tree** under `~/Documents/Project-Sites` (default) or custom dir with `--dir=PATH`
- Subfolders: Experiment, Local, Staging, Testing, Personal-Git, Packages-Git, Packages-Own, Other-Languages
- **Valet “park”** is run automatically in main subfolders
- Idempotent, only makes missing folders
- Logs and summary

#### ⚡ Usage

```bash
./08-project-sites-setup.sh
./08-project-sites-setup.sh --dir="/mnt/ssd/Project-Sites"
```

---

### 09-taskbar-setup.sh — Features & Usage

Automatically pins dev tools to KDE Plasma taskbar with backup/restore and customizable app list.

#### 🚀 Features

- Detects and backs up current KDE taskbar config
- Pins your favorite dev apps (editors, browsers, IDEs, DB clients, terminals, etc.)
- Custom app list: override via `--apps=Name1,Name2,...` or `PIN_APPS` env
- **Rollback:** `--uninstall` restores previous taskbar setup
- Restarts Plasma shell to apply changes
- Only runs if in KDE/Plasma and on Arch/Manjaro
- Logs everything

#### ⚡ Usage

```bash
./09-taskbar-setup.sh
./09-taskbar-setup.sh --apps="Firefox,Brave,Code,Kate,Terminal"
./09-taskbar-setup.sh --uninstall
```

---

### 10-udev-rules-setup.sh — Features & Usage

Automatically configures udev rules for both Android and iOS support.

#### 🚀 Features

- Adds all required vendor/product IDs for Android/iOS
- Reloads udev rules and restarts `usbmuxd`
- Interactive confirmation, warns before overwriting
- Idempotent, will not duplicate rules
- Logs all actions/errors

#### ⚡ Usage

```bash
./10-udev-rules-setup.sh
```

---

### 11-ollama-openwebui-setup.sh — Features & Usage

Full automation for Ollama LLM API + Open WebUI via Docker. Supports multi-model setup, custom ports, uninstall, and more.

#### 🚀 Features

- Installs Docker and Ollama if missing
- Sets up Open WebUI (customizable port: `--port=4001`, default: 3000)
- Pulls multiple models at once with `--models=llama3:8b,dolphin3:8b,gemma3n:e4b`
- Uninstall: `--uninstall` removes all (containers, images, config)
- Firewall/UFW setup for secure local use
- Idempotent, skips already-pulled models and existing containers
- Logs all actions and status

#### ⚡ Usage

```bash
./11-ollama-openwebui-setup.sh
./11-ollama-openwebui-setup.sh --models="llama3:8b,dolphin3:8b,gemma3n:e4b"
./11-ollama-openwebui-setup.sh --port=4001
./11-ollama-openwebui-setup.sh --uninstall
```

---

### 12-setup-checklist.sh — Features & Usage

Interactive, categorized checklist for all manual post-setup tweaks (desktop, login, configs, etc).

#### 🚀 Features

- Interactive and categorized for each type of post-install task
- Lets you mark done/skip for each task
- Final summary table at the end
- Ensures you never miss a manual desktop/config step
- Logs everything

#### ⚡ Usage

```bash
./12-setup-checklist.sh
```

---

## 🪵 Logs

All logs are written to:

```
~/logs/
├── git_setup.log
├── php_valet_valkey_composer_setup.log
├── postgres_setup.log
├── ollama_openwebui_install.log
└── ...
```

- Each script sets its own log filename via `lib-logger.sh`.
- Logs are timestamped for debugging.

---

## 🧠 Global Requirements

- **Supported:** Arch Linux, Manjaro, Garuda, CachyOS, AxOS, and all Arch-based distros
- **Desktop:** KDE Plasma recommended (for full taskbar features)
- **Shell:** Zsh or Fish for dev helpers; Bash v5+ for scripting
- **Sudo access** and **internet connection**
- Place `lib-logger.sh`, `lib-platform.sh`, `lib-aur-helper.sh` in `../lib/`

---

## 🤝 Contributions

Additional modules, performance tweaks, and README improvements are welcome!

---

## 🧡 License

MIT License: [https://opensource.org/license/mit](https://opensource.org/license/mit)

---

Made with ❤️ and `bash` by [@abbasmashaddy72](https://github.com/abbasmashaddy72)
