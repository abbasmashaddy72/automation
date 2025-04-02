---
title: 🚀 Arch Linux Developer Automation Setup
description: Automate your complete Arch Linux workstation for Laravel, Valet, Git, databases, dev tools, and more with modular bash scripts.
---

# 🖥️ Arch Linux – Complete Developer Setup Automation

Automate your **Laravel-ready Arch Linux workstation** with a suite of modular bash scripts, covering:

- ✅ Git identity and credential configuration
- 🧠 Zsh customizations and dev-friendly aliases
- 🐘 PHP + Composer + Valet setup
- 🛠 Essential developer applications
- 🧰 Udev rules for Android & iPhone
- 🔐 Secure MariaDB installation
- ⚙️ System tweaks (UFW, mirrors, fstrim, GRUB, etc.)

---

## 📁 Directory Structure

```bash
archlinux/
├── git_setup.sh                 # Git username, email, credential setup
├── install_packages.sh          # Install essential tools (pacman + pamac + AUR)
├── mariadb_setup.sh             # MariaDB installation and security
├── php_valet_composer_setup.sh  # PHP, Valet, Composer install
├── system_setup.sh              # UFW, swappiness, GRUB config
├── udev_rules_setup.sh          # Android + iPhone USB rules
└── zshrc_config.sh              # Zsh aliases + Laravel helpers
```

---

## 🧩 1. Git Setup

> **Script**: `git_setup.sh`

Configures Git with:

- Username + email
- Credential storage (via Git Credential Manager)
- Validated user input

```bash
chmod +x git_setup.sh
./git_setup.sh
```

---

## 🖋️ 2. ZSH Laravel Dev Setup

> **Script**: `zshrc_config.sh`

Adds Laravel dev-friendly functions to `.zshrc`:

- ✅ `artisan`, `sail`, `pint`, `php-cs-fixer` functions
- ✅ `clean-npm`, `clean-composer` aliases
- ✅ Automatically logs and backs up `.zshrc`

```bash
./zshrc_config.sh
```

---

## 🧰 3. System Configuration

> **Script**: `system_setup.sh`

System-wide setup includes:

- UFW firewall setup and enable
- Enable `fstrim.timer` (SSD optimization)
- Sets swappiness to 10
- Configures GRUB (interactive edit)

```bash
./system_setup.sh
```

---

## 📦 4. Application Installer

> **Script**: `install_packages.sh`

Installs **core** and **optional** developer tools:

- ⚙️ Dev tools: DBeaver, Meld, VirtualBox, Timeshift, etc.
- 🧑‍💻 IDEs: PyCharm, VSCode, Android Studio, Sublime Text
- 🌐 Browsers: Chrome, Brave, Firefox Dev
- 🔐 Pamac / AUR support included

```bash
./install_packages.sh
```

---

## 🐘 5. PHP + Composer + Valet

> **Script**: `php_valet_composer_setup.sh`

Installs and configures:

- ✅ PHP 8 with Laravel-specific extensions
- ✅ Node.js + NPM
- ✅ Composer (via `pacman`, not URL)
- ✅ Valet Linux
- ✅ Adds `~/.config/composer/vendor/bin` to `PATH`

```bash
./php_valet_composer_setup.sh
```

---

## 🗃️ 6. MariaDB Secure Setup

> **Script**: `mariadb_setup.sh`

- Installs and initializes MariaDB
- Enables and starts service
- Runs interactive `mariadb-secure-installation`

```bash
./mariadb_setup.sh
```

---

## 🔌 7. USB Udev Rules

> **Script**: `udev_rules_setup.sh`

- Prompts you for **Android** and **iPhone** `idVendor` and `idProduct`
- Creates udev rules to prevent issues with device mounts / MTP
- Restarts `usbmuxd` and reloads udev

```bash
./udev_rules_setup.sh
```

---

## 🔁 Recommended Run Order

```bash
./git_setup.sh
./zshrc_config.sh
./system_setup.sh
./install_packages.sh
./php_valet_composer_setup.sh
./mariadb_setup.sh
./udev_rules_setup.sh
```

> ✅ All logs are saved in `~/logs/` for review.

---

## 💬 Feedback & Contributions

This project is maintained by the community — feel free to open PRs or submit feature requests!

---

## 🧡 License

MIT — Free to use, share, improve.

---

Made with ⚡ & bash magic by [@abbasmashaddy72](https://github.com/abbasmashaddy72)
