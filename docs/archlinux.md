---
title: 🚀 Arch Linux Developer Automation Setup
description: Automate your complete Arch Linux workstation for Laravel, Valet, Git, databases, dev tools, and more with modular bash scripts.
---

# 🖥️ Arch Linux – Complete Developer Setup Automation

A modular, bash-powered system to fully automate your **Laravel development environment** on **Arch Linux / Manjaro**, covering:

- ✅ Git identity and credential configuration
- 🧠 Zsh dev-friendly aliases and helpers
- 🐘 PHP + Composer + Valet installation
- 🧩 Laravel-ready folder scaffolding
- 🛠 System tweaks and SSD optimizations
- 📦 IDEs, browsers, productivity tools
- 🔐 MariaDB + PostgreSQL secure setup
- 🔌 Udev rules for Android & iOS
- 🤖 Ollama + Open WebUI (LLM interface)

---

## 📁 Directory Structure

```bash
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
├── run_all.sh                   # Run everything in order
└── lib/
    └── lib-logger.sh            # Centralized logger used in all scripts
````

---

## ✅ Step-by-Step Script Breakdown

### 1. 🧰 System Setup

> `01-system-setup.sh`

* Enables UFW firewall
* Configures SSD trim timer
* Tunes swappiness to `10`
* Updates GRUB (`quiet splash`)

```bash
./01-system-setup.sh
```

---

### 2. 📦 Install Developer Packages

> `02-install-packages.sh`

* Pacman + Pamac-based install
* Includes: IDEs, browsers, VMs, tools
* All packages are categorized and logged

```bash
./02-install-packages.sh
```

---

### 3. 🧑‍💻 Git Setup

> `03-git-setup.sh`

* Prompts for Git username & email
* Uses Git Credential Manager
* Verifies and logs settings

```bash
./03-git-setup.sh
```

---

### 4. 🖋️ Zsh Laravel Shortcuts

> `04-zshrc-config.sh`

* Adds `artisan`, `vbin`, `pint`, `sail` aliases
* Includes `--install-if-missing` flag
* Backs up `.zshrc` safely

```bash
./04-zshrc-config.sh
```

---

### 5. 🐘 MariaDB Setup

> `05-mariadb-setup.sh`

* Installs & initializes MariaDB
* Enables and verifies the service
* Prompts for secure `mariadb-secure-installation`

```bash
./05-mariadb-setup.sh
```

---

### 6. 🐘 PostgreSQL Setup

> `06-postgres-setup.sh`

* Installs & initializes Postgres
* Prompts for password and applies it
* Enables and verifies the service

```bash
./06-postgres-setup.sh
```

---

### 7. 🧪 PHP + Valet + Composer

> `07-php-valet-setup.sh`

* Installs:

  * PHP 8.x with Laravel-required extensions
  * Composer from repo
  * Valet (via Composer)
  * Node.js, NPM, NVM
* Adds Composer global bin to `.zshrc`
* Applies `custom.ini` for performance

```bash
./07-php-valet-setup.sh
```

---

### 8. 🗂️ Laravel Project Structure

> `08-project-sites-setup.sh`

Creates structured folders for projects under:

```bash
~/Documents/Project-Sites/
```

* Subfolders: `Local`, `Staging`, `Packages-Own`, etc.
* Runs `valet park` automatically inside `Local`, `Staging`, etc.

```bash
./08-project-sites-setup.sh
```

---

### 9. 📌 Taskbar Pinning (KDE Plasma)

> `09-taskbar-setup.sh`

* Scans `.desktop` files for dev apps
* Adds them to pinned KDE Task Manager
* Restarts `plasmashell` for changes to apply

```bash
./09-taskbar-setup.sh
```

---

### 10. 🔌 Udev USB Rules (iOS + Android)

> `10-udev-rules-setup.sh`

* Configures rules based on vendor/product IDs
* Avoids mount, MTP, camera interference
* Restarts `usbmuxd` and reloads `udevadm`

```bash
./10-udev-rules-setup.sh
```

---

### 11. 🤖 Ollama + Open WebUI

> `11-ollama-openwebui-setup.sh`

* Installs Docker and Ollama
* Enables Ollama server (`0.0.0.0`)
* Runs Open WebUI on port `3000`
* Pulls `deepseek-coder-v2:16b` model by default

```bash
./11-ollama-openwebui-setup.sh
```

---

## 🔁 Run All at Once

> Run everything in recommended order:

```bash
chmod +x run_all.sh
./run_all.sh
```

You can also run scripts individually depending on your stage.

---

## 🪵 Logs

All logs are written to:

```bash
~/logs/
├── git_setup.log
├── php_valet_composer_setup.log
├── postgres_setup.log
├── ollama_openwebui_install.log
└── ...
```

Each script sets its own filename automatically via `lib-logger.sh`.

---

## 🧠 Requirements

* Arch Linux or Manjaro (Plasma preferred)
* Sudo access
* Internet connection

---

## 🤝 Contributions

Feel free to submit:

* Additional installer modules
* Performance tweaks
* README improvements

---

## 🧡 License

[MIT License](https://opensource.org/license/mit)

---

Made with ❤️ and `bash` by [@abbasmashaddy72](https://github.com/abbasmashaddy72)

---

Let me know if you'd like this exported as a `README.md` file, rendered for preview, or published via GitHub Pages/Docs.
