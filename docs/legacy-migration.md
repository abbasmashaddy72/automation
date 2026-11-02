# Migration from the removed installers

The `modules/legacy/` directory and all 14 remaining source files are removed.
The unified CLI uses maintained libraries directly; no installer was relocated or
retained behind a compatibility dispatcher. Existing user installations, units,
keys, models, caches, shell files, databases and projects are preserved.

## Owner-approved scope

The owner approved retiring standalone database initialization/password setup,
mirror/system/GRUB/firewall tuning, Valet installation and native vLLM/Playground
installation, and selected Lerd completely for the development stack. Removal is
therefore a combination of verified replacements and explicit retirement; it is
not a claim that every old host mutation has a new implementation.

PHP/Composer, Node/npm, databases, cache services and the local web stack use
Lerd's public interfaces. Selecting compatible Lerd suppresses overlapping native
packages. Existing installations are never uninstalled or stopped. Generic native
package mappings and the explicitly reviewed `--allow-standalone-dev` escape hatch
remain available under the package contract; they do not restore the removed
standalone provisioning workflows.

Lerd does not manage USB permissions. The automatic USB installer is retired;
optional exact-ID review exports remain separate manual device configuration.
No replacement writes `/etc`, reloads device rules, changes a firewall/bootloader,
switches login shells or initializes existing databases.

## Source disposition and verification

Paths in the first column are historical names, not runnable entrypoints.

| Removed source under `modules/legacy/archlinux/` | Maintained replacement or approved retirement | Evidence / limits |
|---|---|---|
| `01-system-setup.sh` | Host upgrades, mirror, GRUB, sysctl, firewall, timers and hardware provisioning retired | No equivalent host mutation is advertised; existing host state preserved |
| `04-shellrc-dev-setup.sh` | `developer shell`, exact-block recovery, shell-backup import/restore and optional owned-agent socket | Bash/Zsh/Fish fixtures, syntax-only checks, conflict-safe private receipts; remote plugin execution and forced shell switching retired |
| `20-php-runtime-setup.sh` | Lerd PHP; `configuration php` gives public CLI guidance | Standalone PHP/FPM/Nginx exports and activation retired; tests enforce no export even with old `--standalone --yes` flags |
| `21-node-runtime-setup.sh` | Lerd runtime selection and Node tooling | Existing host Node/npm/nvm preserved; no version-manager adoption or package removal |
| `22-mariadb-setup.sh` | Public Lerd service catalogue/preset operations | Standalone initialization, credential rewriting and database purge retired |
| `23-postgres-setup.sh` | Public Lerd PostgreSQL service operations | Existing clusters and roles never changed; standalone initialization/password setup retired |
| `24-valkey-setup.sh` | Select a supported service from the public Lerd catalogue | No assumed preset equivalence, generated Quadlets or host service changes |
| `61-project-sites-setup.sh` | `projects layout`, safe project templates and public Lerd park/link | Eight-folder layout, conflict/link checks, repeat invocation and existing-project preservation tested; Valet provisioning and phpinfo generation retired |
| `82-udev-rules-setup.sh` | Automatic provisioning retired; optional `configuration udev` review export | Exact IDs, private modes, checksums, no writes on check/dry-run and no overwrite tested; actual device activation remains manual and is not a Lerd feature |
| `91-ollama-openwebui-setup.sh` | Portable Ollama plus explicit rootless pinned-image WebUI lifecycle/recovery/recreation | Ownership, interrupted receipts, altered-resource refusal and preservation regressions; actual slim-image auth/recovery/account/session/key persistence and teardown passed, recorded by `scripts/webui_sandbox.py` in normal validation output |
| `92-vllm-playground-setup.sh` | Reviewed existing vLLM executable, bounded unit-settings import, owned lifecycle, auth/context and verified model copies | CPU runtime integration previously verified; native vLLM/PyTorch/Playground installation retired; GPU and actual host user-manager operation not certified |
| `93-llamacpp-setup.sh` | CPU build, owned units, keys, checksummed complete GGUF bundles and old selection/settings import | Actual tiny-model CPU inference/auth/context and genuine shard recovery previously verified; old-unit repair/uninstall is not performed on foreign units |
| `llm-api-key.py` | Shared native private-key operations and explicit raw/env import | Private modes, unsafe paths, key preservation/rotation/revocation and protected endpoint checks covered; secrets never copied into releases |
| `llm-api-smoke.py` | Shared bounded loopback HTTP diagnostics and inference sandbox | Redirect/proxy/response/auth contracts plus actual CPU inference; dry-run sends no prompts |

Earlier removed package, Git/SSH, taskbar, checklist, Hub catalogue, GGUF and
snapshot helpers are covered by shared package/source adapters, developer/SSH
operations, desktop adapters, manual checklist, `ai/models.py`, `ai/gguf.py` and
`ai/snapshots.py`. Their regression tests remain. All three old openSUSE entrypoints
are also removed; native zypper support never adds repositories or reproduces the
old security-policy/credential downgrades.

## Developer migration commands

```bash
bash setup.sh packages plan --profile=developer --dry-run
bash setup.sh lerd status
bash setup.sh lerd php:list
bash setup.sh lerd service list
bash setup.sh lerd service preset
bash setup.sh projects layout "$HOME/Documents/Project-Sites" --dry-run
bash setup.sh developer status
bash setup.sh configuration php
```

For PHP settings, use the official `lerd php:ini` or `lerd php:ini shared` after
review. The upstream editor action can restart affected FPM containers; this
toolkit does not invoke it implicitly. Lerd service selection/start and site
park/link remain separate approved actions. The toolkit never edits Lerd's
Quadlets, DNS, certificates, databases or PHP images.

Current references: [Lerd PHP](https://lerd.sh/usage/php),
[services](https://lerd.sh/getting-started/services),
[site registration](https://lerd.sh/usage/sites).

## Recover existing user state without old source code

The removed source directory is distinct from old state in your home directory.
Keep original data and back it up before migrating. Maintained bounded data
readers remain intentionally available:

- `developer import-git-backup`, `import-shell-backup`, exact paired shell-block migration and conflict-safe restore.
- `ai ... key-import` for an explicitly selected private key; originals are preserved.
- `ai llamacpp|vllm legacy-plan/legacy-import` for supported stopped/disabled old units. Stop/disable the original yourself after review; imports never execute or delete it.
- Read-only Hub inventory and independently verified snapshot copies; no external cache deletion.
- `gguf-legacy-list/import` for old GGUF markers/selection/context; markers never grant deletion ownership.

The maintained file `ai/legacy.py` is a data parser, not the removed installer
module. Historical unit marker strings and CLI import flags remain so existing
users can recover their settings. Removing these would strand user data.
See [usage and recovery](unified-setup.md) and
[WebUI recovery](configuration-and-webui.md).

## Validation boundaries

Unit tests, non-root read-only distro probes, disposable package workflows,
actual CPU AI tests, actual WebUI tests and real host integrations are distinct
gates. Normal validator output records current runs. ShellCheck/shfmt absence
on the host is a skip, not a pass. Container testing does not establish real
GNOME/KDE writes, host systemd/autostart, real USB access, GPU acceleration, Jan GUI
or unrestricted production deployment certification.

Laravel production workflows are now independently maintained in `laravel/`; they
are not the removed `modules/legacy` module. Optional setup integration delegates
to their standalone entrypoints. See [portable verification](../laravel/docs/verification.md);
no destructive host or production-data test is performed.

## Existing update archives

No new ZIP or standalone delivery report is generated for local refactoring.
Existing checksummed archive tools and transactional recovery remain available:

```bash
bash scripts/update.sh --check /absolute/existing-patch.zip
bash scripts/update.sh --apply /absolute/existing-patch.zip
bash scripts/update.sh --rollback
bash scripts/update.sh --recover
```

Use the new updater with `--root /absolute/old-toolkit` when an old updater has
incompatible policy. Temporary archive fixtures test checksums, malicious paths,
conflicts, deletions, interrupted recovery and preservation of subsequent edits.
