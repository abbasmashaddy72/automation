# Linux Automation Toolkit

Set up and maintain Linux from a local dashboard or the terminal. The toolkit uses your distribution’s native package manager and previews changes before you approve them.

## Get started

Run these commands from the checkout. Use Bash to launch them from Fish or Zsh as well. The toolkit requires Bash 4.4+ and Python 3.9+. The Bash-only prerequisites command works before Python is installed.

```bash
bash setup.sh --help
bash setup.sh prerequisites check
bash setup.sh --check
bash setup.sh dashboard open
```

For a terminal interface, run `bash setup.sh menu`. If Python is missing, review `bash setup.sh prerequisites install --dry-run`, then apply with `--yes`. The dashboard listens on loopback. Keep its launching terminal available for sudo authentication and AUR recipe review.

![Linux Setup dashboard showing package selection](docs/images/setup-dashboard.png)

## Workflows

| Workflow                                      | Where to start                                                      | Guide                                                                                                                                                                                                                          |
| --------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Packages and prerequisites                    | **Packages** or `bash setup.sh wizard`                              | [Package selection, search, aliases, and sources](docs/packages.md)                                                                                                                                                            |
| Smart Backup                                  | **Maintenance → Smart Backup** or `bash setup.sh smart-backup`      | [Home presets, folder tree, Copy, ZIP, and restore](docs/smart-backup.md)                                                                                                                                                      |
| System, checklist, and cleanup                | **System**, **Maintenance**, and the **Setup checklist** drawer     | [Dashboard and maintenance](docs/unified-setup.md#dashboard-review-and-apply)                                                                                                                                                  |
| Git, SSH, and shells                          | **Configure → Terminal** or `bash setup.sh developer status`        | [Shell and developer configuration](docs/unified-setup.md#local-configuration-and-services)                                                                                                                                    |
| Lerd, Project Sites, and desktop integrations | **Configure** or `bash setup.sh lerd status`                        | [Development services and project directories](docs/configuration-and-webui.md), [desktop favorites](docs/unified-setup.md#desktop-favorites), [USB configuration](docs/configuration-and-webui.md#optional-usb-review-export) |
| System profile backup and import              | **System → Export Profile / Import Profile**                        | [Profile sections, migration, and restore](docs/workflows.md#system-profile-backup-and-import)                                                                                                                                 |
| Zed and package recovery                      | **Configure → Zed settings** or **Maintenance → Package inventory** | [Zed backups and package replay](docs/workflows.md#zed-settings)                                                                                                                                                               |
| Local AI and chat                             | **Local AI** or `bash setup.sh ai server plan`                      | [Managed llama.cpp](docs/llama-cpp.md), [ChatGPT Lite](chatgpt-lite/README.md), [Open WebUI](docs/configuration-and-webui.md#rootless-open-webui)                                                                              |
| Laravel production servers                    | `bash setup.sh laravel provision` or `bash setup.sh laravel deploy` | [Standalone Laravel toolkit](laravel/README.md)                                                                                                                                                                                |
| Toolkit updates and recovery                  | `bash scripts/update.sh --help`                                     | [Update migration and recovery](docs/legacy-migration.md#existing-update-archives)                                                                                                                                             |

Smart Backup starts at Home and suggests a mounted writable external drive when one is available. Expand **Documents** to review its subfolders. The standard preset copies Documents and saves Project-Sites as a separate ZIP. Use **Preview backup** before creating a snapshot.

## Distributions

| Family                              | Native package manager |
| ----------------------------------- | ---------------------- |
| Arch, CachyOS, EndeavourOS, Manjaro | pacman                 |
| Debian, Ubuntu, Mint                | APT                    |
| Fedora, RHEL, Rocky, AlmaLinux      | DNF                    |
| openSUSE                            | Zypper                 |
| Alpine                              | APK                    |

Package-adapter support and host features have separate requirements. Check the [compatibility and validation matrix](docs/validation.md) for what was exercised. Lerd and managed llama.cpp have their own host compatibility checks. llama.cpp is the managed inference engine. ChatGPT Lite and Open WebUI are optional clients.

## Configuration and maintenance

- The toolkit reads public defaults from `config/defaults.env`. Use `bash setup.sh config show` to inspect effective settings and `bash setup.sh config init --yes` to add missing values to the private root `.env`.
- Preview commands leave the host unchanged. Review the exact package and source before approving installation. A saved plan or a similar name does not authorize a substitute.
- Run `python3 scripts/validate.py --mode offline` for local checks. For contribution and repository structure, see [AGENTS.md](AGENTS.md) and the [architecture guide](docs/unified-architecture.md).

## Troubleshooting and recovery

- If dashboard installation waits for authentication or package review, check the launching terminal. Use `bash setup.sh --check` to inspect the current system and `bash setup.sh --dry-run --profile=minimal` to review the minimal package plan.
- A profile import previews the selected sections before applying them. Use the returned backup IDs to restore toolkit or Zed settings. Check the [profile schema and compatibility guide](docs/workflows.md#system-profile-backup-and-import).
- Use `bash setup.sh ai server status` for managed llama.cpp and `bash setup.sh ai server key-status` for masked LAN gateway status. Use the [service and API key workflow](docs/llama-cpp.md#existing-services-and-api-credentials) to review an existing endpoint or rotate a key.

See the [changelog](CHANGELOG.md) for the project timeline.
