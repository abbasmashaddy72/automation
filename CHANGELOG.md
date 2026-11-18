# Changelog

Dates follow recorded Git author dates or the local date of changes still in the checkout. Related changes on the same day are grouped by workflow.

## 2026-11-18

- Kept read-only checklist refreshes from blocking another dashboard workflow.
- Verified installed RPM versions against cache-only DNF repository queries before reinstall.
- Deduplicated native package targets and extended validation for repeat installs, explicit reinstalls, profile restoration, checklist persistence, and backup contents.

- Added local and SSH inference endpoint inspection, masked managed gateway key status, verified credential replacement with rollback, and installed-build reuse by default.

- Added verified native findutils setup when a disposable regression fixture lacks find.
- Added versioned System profile export and reviewed import for toolkit defaults, dashboard choices, package mappings, and supported Zed settings. Imports migrate earlier CLI profiles and preserve unrelated configuration.

- Apply verified full releases through the shared updater without rebuilding the archive in memory. Validate their source files during preview.
- Skip generated directories and symlinks during source validation, and remove unused Python imports and ChatGPT Lite dependencies.
- Validate patch source before replacing files and preserve conflicting edits during recovery.
- Restrict LAN API key rotation to toolkit-owned gateways and restore the prior key if a restart fails.
- Verify that backup ZIPs contain the reviewed inventory and reject truncated Laravel health responses.
- Block direct AI installation when the model storage review fails and verify the workflow in an isolated CI browser session.
- Remove the unused AI resource planner and retired key-command dispatcher.
- Aligned the backup ID field with its restore preview action and stacked the controls on narrow screens.
- Standardized dashboard tab spacing, separated the AI execution target from the build controls, and grouped model storage checks.
- Displayed each selected package ID on a separate line.
- Grouped related setup, cleanup, telemetry and AI actions in responsive rows. System information lists drives individually in GiB and shows zram under Memory.

## 2026-11-17

### Smart Backup, dashboard layout, and documentation

- Added Smart Backup to the dashboard and interactive terminal, with a Home preset for common folders and visible top-level files. The preset copies Documents and archives `Documents/Project-Sites` separately.
- Added an expandable folder tree with per-folder Copy, ZIP, Skip, and hidden-file controls. Folder name and controls share a row, source and destination controls are grouped, and exclusions and verification have a collapsible section.
- Added read-only backup previews, mounted-drive discovery, verified copy and ZIP output, manifests, and safe handling of partial output.
- Removed unused shell wrappers, old package-resolution helpers, duplicate ChatGPT Lite hooks, and an unreferenced theme dropdown.
- Fixed terminal AI prompt parsing on older supported Python versions and kept native backup tests compatible with Python 3.9.
- Consolidated overlapping setup pages and changelogs into the README, this timeline, and linked [package](docs/packages.md), [backup](docs/smart-backup.md), and [llama.cpp](docs/llama-cpp.md) guides.

### Advanced setup and Laravel deployment

- Organized Advanced into Review & apply, Toolkit settings and Restore settings, with links to the original workflow pages.
- Added candidate Laravel readiness checks before atomic activation and a continuous HTTP test across failed activation, deployment and rollback. Shared compiled views stay available during deployment.
- Extended the Podman matrix with official derivative images and corrected the default Python package on openSUSE Leap 16.

### Dashboard and managed llama.cpp · 13:27 IST · `f11a7dc`

- Added the loopback setup dashboard and terminal menu. The dashboard covers hardware, package selection and reinstall, checklist progress, Lerd, Project Sites, Zed, terminal setup, telemetry, and separate toolkit and system cleanup previews.
- Added distro-specific package aliases, saved source mappings, native replay, and improved source verification and AUR review feedback.
- Standardized managed inference on llama.cpp. Replaced former inference installers with an owned systemd service, model and storage checks, GGUF discovery and verification, CPU/GPU build paths, generation measurement, and an optional authenticated LAN gateway.
- Added shared local/SSH AI selection, runtime and context diagnostics, and optional terminal AI commands and suggestions.
- Added ChatGPT Lite with browser-local history, model selection, and background controls. Updated the rootless Open WebUI workflow to use the llama.cpp API.
- Added a repository formatter, expanded dashboard and integration regressions, and refined package, update, and Laravel command validation.

## 2026-11-03 · `e64a410`

- Replaced separate Arch and openSUSE installer trees with the shared `setup.sh` entrypoint, native package adapters, Bash-only prerequisite bootstrap, and exact package planning and verification.
- Added private configuration, package receipts, profiles, offline artifact checks, checklist automation, Project Sites, desktop favorites, and reviewed Git, SSH, and shell state recovery. Routed development services through Lerd.
- Added GGUF verification, model receipts, AI API diagnostics, and authenticated rootless Open WebUI.
- Replaced six Laravel scripts with the standalone Ubuntu provisioning and release deployment toolkit. Added reviewed external provisioning, local provisioning, staged Git releases, health checks, and rollback.
- Added checksum-verified full and patch updates, recovery tests, CI validation, and disposable container workflows.

## 2026-06-03 · `e37f715`

- Added Okular to the Arch catalog, adjusted development-shell helpers, and refined PHP removal to check packages and remove managed extension fragments.

## 2026-05-26 · `d70f298`

- Expanded Git/SSH setup and Git configuration backup and restore. Updated shell helpers and PHP and Valkey setup, and added Project Sites setup options.

## 2026-02-03 · `1a2cc84`, `360e4d7`

- Reorganized Arch setup into system, packages, Git/SSH, shell, development runtime, projects, desktop, USB, AI, and checklist workflows.
- Separated PHP, Node.js, MariaDB, PostgreSQL, and Valkey setup and updated the earlier Laravel server script and Ollama/Open WebUI workflow.

## 2026-01-27 · `1e92a99`

- Added Tor Browser and FreeTube to the earlier Arch package or desktop selections.

## 2025-08-08 · `cd6b424`

- Extended platform checks to CachyOS and added a Laravel server setup script.

## 2025-07-30 · `acdf375`, `b2ca7d2`

- Added Docker Compose detection and project management to the Laravel Docker wizard. Made PHP limits and Nginx upload size configurable in the earlier Arch Valet workflow.

## 2025-07-28 · `4d8f4c6`, `731957e`

- Added Git configuration rollback, revised the earlier AUR and Ollama/Open WebUI setup, made the AUR helper executable, and introduced the Laravel PHP Docker wizard.

## 2025-07-25 · `ca02432`, `dd26dd7`, `3ca5995`

- Replaced the Zsh-specific setup with shared development-shell setup, extracted AUR helper code, added PHP extension enablement, and reorganized the setup checklist and Arch scripts.

## 2025-07-22 · `7bd5fa1`, `951f71c`

- Added Laravel scheduler controls and an interactive Arch checklist. Updated system upgrades, AUR settings, MariaDB security setup, Valet initialization, and taskbar handling.

## 2025-07-21

- Centralized script platform and logger checks and expanded configuration prompts for Git, databases, project folders, USB, and desktop setup. Added Valkey to the then-current PHP, Composer, and Valet workflow, plus fonts, build tools, and VirtualBox group setup. Commits `0a63a3c`, `84b958f`, `a47b928`, `858f527`.
- Iterated on sudo handling and error reporting. Temporary sudoers and askpass experiments were removed in favor of native sudo authentication prompts. Commits `78adaa5`, `e0e4b83`, `8e4fab1`, `c23283f`, `6406ae2`, `cb55091`, `e34cfde`, `cd8d8d6`, `52e8a53`.
- Improved exact installed-package checks and post-install verification for Pamac via pacman. Fixed reporting when no packages were installed, skipped, or failed. Commits `567d0ea`, `e8b298d`, `5e81662`, `2bcb72b`, `363b4e4`, `8972cfa`, `95d511e`, `1457ad4`, `17adc87`, `dd74107`, `c727e4e`.

## 2025-07-20 · `edd3345`, `084892e`, `33865ac`

- Added the Arch setup runner, PostgreSQL, Project Sites, taskbar, and earlier Ollama/Open WebUI setup. Ordered the scripts and shared logging and error handling.

## 2025-06-28 · `7f54fba`

- Added a Laravel package renaming helper that updated Composer package metadata.

## 2025-04-24 · `f38d484`

- Added restart and terminate operations to the earlier Laravel Horizon controller.

## 2025-04-20 · `1ade70d`

- Adjusted local Laravel deployment and its Horizon and scheduler restart commands.

## 2025-04-04 · `501bb6e`

- Updated Arch Git installation and Laravel deploy handling. Added supervisor-backed scheduler controls and refined Horizon management.

## 2025-04-03 · `88d0cfe`, `49c2233`

- Started the repository with a README and added separate Arch and openSUSE setup workflows, Laravel deployment tools, and setup guides.
