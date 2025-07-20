---
title: 🚀 Arch Linux Developer Automation Setup
description: Automate your complete Arch Linux workstation for Laravel, Valet, Git, databases, dev tools, and more with modular bash scripts.
---

# 🖥️ Arch Linux – Complete Developer Setup Automation

A modular, bash-powered system to fully automate your **Laravel development environment** on **Arch Linux / Manjaro**, covering:

* ✅ Git identity and credential configuration
* 🧠 Zsh dev-friendly aliases and helpers
* 🐘 PHP + Composer + Valet installation
* 🧩 Laravel-ready folder scaffolding
* 🛠 System tweaks and SSD optimizations
* 📦 IDEs, browsers, productivity tools
* 🔐 MariaDB + PostgreSQL secure setup
* 🔌 Udev rules for Android & iOS
* 🤖 Ollama + Open WebUI (LLM interface)

---

## ⚠️ Platform Safety

All scripts **refuse to run** on any OS except **Arch Linux or Manjaro**.
This is enforced via `lib/lib-platform.sh` at the start of every script.

---

## 📁 Directory Structure

archlinux/
├── 01-system-setup.sh           # UFW, swappiness, SSD trim, GRUB
├── 02-install-packages.sh       # Pacman + Pamac developer tools
├── 03-git-setup.sh              # Git username, email, credential setup
├── 04-zshrc-config.sh           # Laravel-friendly ZSH aliases + helpers
├── 05-mariadb-setup.sh          # MariaDB install + secure setup
├── 06-postgres-setup.sh         # PostgreSQL install + password config
├── 07-php-valet-setup.sh        # PHP, Composer, Valet, dev INI tweaks
├── 08-project-sites-setup.sh    # Creates Laravel project directories + valet park
├── 09-taskbar-setup.sh          # Pins dev apps to KDE taskbar
├── 10-udev-rules-setup.sh       # Android/iOS USB rules setup
├── 11-ollama-openwebui-setup.sh # LLM interface: Open WebUI + Ollama setup
├── run\_all.sh                   # Run everything in order
└── lib/
├── lib-logger.sh            # Centralized logger used in all scripts
└── lib-platform.sh          # Platform guard: Ensures only Arch/Manjaro allowed

---

## ✅ Features, Flags & Safety

* **Platform guard:** All scripts use a strict Arch/Manjaro detection and will exit on any other distro.
* **Idempotency:** You can safely re-run scripts — they skip or update only when needed.
* **Uninstall/rollback:** Major scripts support a `--uninstall` flag to roll back all changes.
* **Parameterization:** Scripts support CLI args/ENV variables (e.g., `--dir=`, `--apps=`, `--model=`, etc.)
* **Automatic backups:** All user config changes are backed up before modification (e.g., `.zshrc`, `.gitconfig`).
* **Per-script logs:** Every script logs its actions to `~/logs/` with per-run timestamps.
* **KDE/Plasma checks:** KDE-specific scripts auto-detect the desktop and refuse to run elsewhere.

---

## ✅ Step-by-Step Script Breakdown

### 1. 🧰 System Setup

`01-system-setup.sh`

* Enables UFW firewall
* Configures SSD trim timer
* Tunes swappiness to `10`
* Updates GRUB (`quiet splash`)
* **Fails fast if not Arch/Manjaro**

  ./01-system-setup.sh

---

### 2. 📦 Install Developer Packages

`02-install-packages.sh`

* Pacman + Pamac-based install
* Includes: IDEs, browsers, VMs, tools
* All packages are categorized and logged
* **Platform guard active**

  ./02-install-packages.sh

---

### 3. 🧑‍💻 Git Setup

`03-git-setup.sh`

* Prompts for Git username & email (validates non-empty/valid)
* Uses Git Credential Manager
* Backs up `.gitconfig` before writing
* Verifies and logs settings
* **Supports rollback with `--uninstall`**
* **Platform guard active**

  ./03-git-setup.sh

---

### 4. 🖋️ Zsh Laravel Shortcuts

`04-zshrc-config.sh`

* Adds `artisan`, `vbin`, `pint`, `sail` aliases
* Includes `--install-if-missing` flag to auto-install zsh
* Backs up `.zshrc` safely
* Checks for existing config before duplicating
* **Platform guard active**

  ./04-zshrc-config.sh

---

### 5. 🐘 MariaDB Setup

`05-mariadb-setup.sh`

* Installs & initializes MariaDB
* Enables and verifies the service
* Prompts for secure `mariadb-secure-installation`
* Checks if already installed and running
* **Platform guard active**

  ./05-mariadb-setup.sh

---

### 6. 🐘 PostgreSQL Setup

`06-postgres-setup.sh`

* Installs & initializes Postgres
* Prompts for password and applies it
* Enables and verifies the service
* Checks if already installed and running
* **Platform guard active**

  ./06-postgres-setup.sh

---

### 7. 🧪 PHP + Valet + Composer

`07-php-valet-setup.sh`

* Installs:

  * PHP (multi-version via CLI arg)
  * Composer from repo
  * Valet (via Composer)
  * Node.js, NPM, NVM
* Adds Composer global bin to `.zshrc` (only if missing, with backup)
* Applies `custom.ini` for PHP performance
* Supports uninstall with `--uninstall`
* **Platform guard active**

  ./07-php-valet-setup.sh
  ./07-php-valet-setup.sh php74       # (for a different PHP version)
  ./07-php-valet-setup.sh --uninstall # (uninstall/rollback)

---

### 8. 🗂️ Laravel Project Structure

`08-project-sites-setup.sh`

* Creates structured folders for projects under customizable location:

  * Default: `~/Documents/Project-Sites/`
  * Override: `./08-project-sites-setup.sh --dir=/mnt/fastdisk/Project-Sites`
* Subfolders: `Local`, `Staging`, `Packages-Own`, etc.
* Runs `valet park` automatically in selected subfolders
* Skips/doesn’t duplicate folders
* **Platform guard active**

  ./08-project-sites-setup.sh --dir=/your/custom/path

---

### 9. 📌 Taskbar Pinning (KDE Plasma)

`09-taskbar-setup.sh`

* Scans `.desktop` files for dev apps (partial/near match, not case-sensitive)
* Adds them to pinned KDE Task Manager (`plasma-org.kde.plasma.desktop-appletsrc`)
* Restarts `plasmashell` for changes to apply
* Supports `--apps=Firefox,Chrome,Kate` override or env `PIN_APPS`
* Supports `--uninstall` (restore last backup)
* **Fails fast if not on KDE/Plasma or not on Arch/Manjaro**

  ./09-taskbar-setup.sh --apps=Firefox,Chrome
  ./09-taskbar-setup.sh --uninstall

---

### 10. 🔌 Udev USB Rules (iOS + Android)

`10-udev-rules-setup.sh`

* Configures rules based on vendor/product IDs (interactive or `--auto`)
* Avoids mount, MTP, camera interference
* Backs up old rules before overwrite
* Restarts `usbmuxd` and reloads `udevadm`
* Supports `--auto` for unattended
* **Platform guard active**

  ./10-udev-rules-setup.sh --auto

---

### 11. 🤖 Ollama + Open WebUI

`11-ollama-openwebui-setup.sh`

* Installs Docker and Ollama
* Enables Ollama server (`0.0.0.0`)
* Runs Open WebUI on port `3000` (change with `--port=4000`)
* Pulls model of choice (`--model=phi3`)
* Supports uninstall (`--uninstall`)
* **Platform guard active**

  ./11-ollama-openwebui-setup.sh --model=llama3:8b --port=4001
  ./11-ollama-openwebui-setup.sh --uninstall

---

## 🔁 Run All at Once

Run everything in recommended order, with platform/distro checks:

```
chmod +x run_all.sh
./run_all.sh
```

To skip a script (comma-separated):

```
./run_all.sh --exclude=05-mariadb-setup.sh,07-php-valet-setup.sh
```

A summary table is printed at the end (success/fail/skipped for each script).

---

## 🪵 Logs

All logs are written to:

\~/logs/
├── git\_setup.log
├── php\_valet\_composer\_setup.log
├── postgres\_setup.log
├── ollama\_openwebui\_install.log
└── ...

Each script sets its own filename automatically via `lib-logger.sh`.
Logs are timestamped and per-script for easy debugging.

---

## 🧠 Requirements

* Arch Linux or Manjaro (KDE Plasma strongly recommended for full feature set)
* Sudo access
* Internet connection
* Bash v5+ (for associative arrays, etc.)

---

## 🤝 Contributions

Feel free to submit:

* Additional installer modules
* Performance tweaks
* README improvements

---

## 🧡 License

MIT License: [https://opensource.org/license/mit](https://opensource.org/license/mit)

---

Made with ❤️ and `bash` by [@abbasmashaddy72](https://github.com/abbasmashaddy72)
