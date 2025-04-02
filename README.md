# 🧰 Developer Automation Toolkit

Welcome to the **Automation Toolkit** — a modular, scriptable, and customizable collection of Bash-based automation tools for:

- 🐘 Laravel deployment (local & production)
- 🐧 openSUSE development machine setup
- 🅰️ Arch Linux automation with full ZSH, PHP, MariaDB, and Valet support

This repository is structured for clarity, documentation, and GitHub Pages compatibility.

---

## 📁 Folder Structure

| Folder       | Description                                       |
| ------------ | ------------------------------------------------- |
| `laravel/`   | Laravel deployment and Horizon Supervisor tooling |
| `opensuse/`  | System automation for openSUSE dev environments   |
| `archlinux/` | Modular automation scripts for Arch-based systems |
| `docs/`      | Markdown documentation for GitHub Pages rendering |

---

## 🚀 Getting Started

Clone this repository and navigate into the directory:

```bash
git clone https://github.com/YOUR_USERNAME/automations.git
cd automations
```

---

## ⚙️ Laravel

📁 [`laravel/`](./laravel)

Scripts:

- `deploy-local.sh`: Laravel deployment script for `dev` and `prod` with:
  - Environment-aware optimization
  - Horizon restart support
  - Migration & seeding
  - Multi-tenancy support
- `horizonctl.sh`: Supervisor-based Horizon management tool

📖 [Laravel Setup Guide →](./docs/laravel.md)

---

## 🐧 openSUSE

📁 [`opensuse/`](./opensuse)

Scripts:

- `install-script.sh`: System-level setup (repos, packages, services)
- `extra-config.sh`: Git, AppArmor, Nginx, Valet, project cloning
- `zsh-install.sh`: ZSH + Oh-My-Zsh + plugins setup

📖 [openSUSE Setup Guide →](./docs/opensuse.md)

---

## 🅰️ Arch Linux

📁 [`archlinux/`](./archlinux)

Scripts:

- `run_all_setup.sh`: Master script that calls the rest in order
- `system_setup.sh`: Base system tweaks and power settings
- `git_setup.sh`: Git config and credential setup
- `install_packages.sh`: Desktop/dev software via pacman
- `mariadb_setup.sh`: MariaDB setup and secure install
- `php_valet_composer_setup.sh`: PHP, Composer, and Valet
- `udev_rules_setup.sh`: Device rules setup
- `zshrc_config.sh`: ZSH shell enhancements

📖 [Arch Linux Setup Guide →](./docs/archlinux.md)

---

## 📝 Documentation

All usage documentation is stored in the [`docs/`](./docs) folder, and is ready for GitHub Pages hosting.

| Guide      | Path                                       |
| ---------- | ------------------------------------------ |
| Home Index | [`docs/index.md`](./docs/index.md)         |
| Laravel    | [`docs/laravel.md`](./docs/laravel.md)     |
| openSUSE   | [`docs/opensuse.md`](./docs/opensuse.md)   |
| Arch Linux | [`docs/archlinux.md`](./docs/archlinux.md) |

---

## 📦 License

MIT License — free to use, share, and modify.

---

## 👨‍💻 Author

Made with 💻 + ☕ by [@abbasmashaddy72](https://github.com/abbasmashaddy72)

---

🚀 **Automate once. Reuse forever.**
