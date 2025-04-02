---
title: 🧠 Automation Scripts for Laravel Devs
description: DevOps automation for Laravel, Arch Linux, and openSUSE — terminal-first, hassle-free development environments.
---

# 🛠️ Automation for Laravel & Dev Workstations

Welcome to your **one-stop automation suite** for Laravel-powered development environments. Whether you're on **Arch Linux**, **openSUSE**, or managing **Laravel** apps across environments, this repo has you covered.

---

## 📁 Available Automations

| Platform                     | Description                                                           |
| ---------------------------- | --------------------------------------------------------------------- |
| [Laravel](./laravel.md)      | Bash-based deployment & Horizon management scripts                    |
| [openSUSE](./opensuse.md)    | Complete workstation setup: dev tools, repos, zsh, AppArmor, Valet    |
| [Arch Linux](./archlinux.md) | Modular setup for PHP, Valet, Git, databases, zsh, packages, and more |

---

## ✅ Features Across All Platforms

- 🚀 **Laravel-ready setup** with Valet and Composer
- 🧩 **Zsh & shell enhancements** for artisan/sail/dev flows
- ⚙️ **Database, firewall, and udev automation**
- 🧰 **Essential dev tools** like VS Code, Chrome, Docker, etc.
- 🧠 Designed for **silent installs & repeatability**
- 🔒 **Security tweaks**: UFW, AppArmor, secure MariaDB, etc.

---

## 🧠 Philosophy

These scripts are:

- 🧼 **Idempotent** — re-run safe
- 💬 **Interactive where needed** (with good defaults)
- 🧪 **Modular** — run only what you need
- 🔐 **Secure-first** by default
- 📝 **Logged** to `~/logs/`

---

## 📂 Repository Structure

```bash
automation/
├── laravel/      # Laravel deployment & Horizon scripts
├── opensuse/     # Full-stack openSUSE setup
├── archlinux/    # Arch Linux dev environment automation
└── docs/         # Documentation for each environment
```

---

## 🧭 Getting Started

Each directory (`laravel/`, `opensuse/`, `archlinux/`) contains self-contained automation.

Example:

```bash
cd archlinux
chmod +x *.sh
./system_setup.sh
```

Scripts are modular — run only what applies to your system or workflow.

---

## 💬 Feedback

This project is open-source and maintained by the Laravel + Linux community.
Feel free to:

- 🤝 Submit issues or pull requests
- ✨ Suggest tools you'd like included
- 🔍 Open ideas for cross-distro enhancements

---

## 🧡 License

MIT — do anything you want, improve what you can.
Please credit where possible. Cheers ☕

---

Made with 💻 and 🧠 by [@abbasmashaddy72](https://github.com/abbasmashaddy72)
