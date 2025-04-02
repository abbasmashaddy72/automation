---
title: ⚙️ OpenSUSE Developer Workstation Automation
description: Fully automated development setup on OpenSUSE with PHP, Laravel Valet, ZSH, Composer, and more – ready to deploy with a single command.
---

# 🖥️ OpenSUSE Developer Workstation Automation

Turn your OpenSUSE machine into a full-featured developer workstation with **zero hassle**.  
These scripts automate:

- System dependencies
- PHP/Laravel + Valet Linux
- ZSH terminal enhancements
- Git + AppArmor config
- Common browsers, editors, and tools

Whether you're building Laravel apps, frontends, or cross-platform tools — this setup covers you.

---

## 📁 Folder Structure

```bash
opensuse/
├── system-setup.sh         # Installs packages, repos, dev tools
├── post-setup-config.sh    # Git setup, Valet park, AppArmor patch
├── zsh-setup.sh            # ZSH, plugins, Oh My Zsh, shell enhancements
```

---

## 🚀 Quick Start

Make scripts executable:

```bash
chmod +x *.sh
```

Run them in sequence:

```bash
./system-setup.sh --all
./zsh-setup.sh
./post-setup-config.sh --repos="user1/repo1,path1;user2/repo2,path2"
```

---

## 🛠️ Scripts Overview

### 1. `system-setup.sh`

> 🧩 Adds repos, installs all essential developer tools (PHP, Node, DB, IDEs, browsers, etc.)

#### ✅ Flags

| Option       | Description                                           |
| ------------ | ----------------------------------------------------- |
| `--all`      | Install everything below                              |
| `--dev`      | Install PHP, Node, Valet, DB, etc.                    |
| `--browsers` | Install Chrome, Brave, Firefox Dev                    |
| `--ides`     | Install VSCode, Android Studio, PyCharm, Sublime      |
| `--tools`    | Install DBeaver, FileZilla, Meld, Peek, Remmina, etc. |
| `--media`    | Include media tools (e.g., fonts, image libs)         |
| `--help`     | Show usage help                                       |

#### 📦 Core Stack Installed

- PHP 8 + common extensions
- NGINX + MariaDB + NodeJS
- Composer + Valet Linux
- Powerline Fonts
- Developer tools & editors

> Services like `php-fpm`, `nginx`, `mariadb` are enabled and started automatically.

---

### 2. `zsh-setup.sh`

> 🧑‍💻 Terminal setup with Oh My Zsh and essential plugins.

- Uses **agnoster** theme
- Adds plugins: git, laravel, composer, autosuggestions, syntax highlighting, autocomplete, etc.
- Configures `colorize` support with Chroma

Non-interactive and repeatable. Run it any time to refresh config.

---

### 3. `post-setup-config.sh`

> 🔧 Finalizes workstation config

- Sets global Git username/email + credential store
- Clones GitHub repos to `$HOME/Documents/Project-Sites`
- Creates a `phpinfo()` test page
- Appends missing AppArmor lines for PHP-FPM
- Reloads AppArmor & services
- Runs `valet park` inside `Clients`, `Personal`, `Testing`

#### 🧬 Example Repo Usage:

```bash
./post-setup-config.sh --repos="laravel/laravel,Clients/laravel;yourname/portfolio,Personal/portfolio"
```

You can clone as many repos as needed via the `--repos` flag.

---

## 💡 Advanced Features

- 🔐 AppArmor patching: ensures PHP-FPM can access all Valet sites and logs
- 🧼 Removes Discover
- ⚡ Fully silent (non-interactive) for scripting
- 🧩 Optional component flags let you customize install sets

---

## 📦 Software Available

| Category | Examples                                           |
| -------- | -------------------------------------------------- |
| Dev      | PHP 8, Node.js 20, Composer, Valet Linux           |
| Database | MariaDB, Secure setup                              |
| Web      | NGINX, php-fpm, Laravel support                    |
| Tools    | DBeaver, Remmina, FileZilla, Meld, Deluge, Peek    |
| Editors  | VS Code, Sublime Text, PyCharm, Android Studio     |
| Browsers | Chrome, Brave, Firefox Developer Edition           |
| Terminal | Oh My Zsh, autosuggestions, Chroma, plugin configs |

---

## 🔄 Automation Ready

- ✅ Scriptable
- ✅ Non-interactive
- ✅ Extendable via flags or CI/CD
- ✅ Compatible with dotfiles or git hooks

---

## 📜 Contributing

Want to add your own tools? PRs are welcome!

Suggestions Are highly appreciated!

---

## 👏 Shoutout

This setup is made with ❤️ to simplify OpenSUSE for web developers.

> Made with 💻 and terminal wizardry by [@abbasmashaddy72](https://github.com/abbasmashaddy72)

---
