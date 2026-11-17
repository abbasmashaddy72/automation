> **Historical reference (pre-v2.1):** For the current llama.cpp-only installation use [INSTALL-LLAMACPP-FIRST.md](../INSTALL-LLAMACPP-FIRST.md). Archived commands for Ollama/vLLM are not active in the upgraded toolkit.

# Unified setup

Run Bash scripts with `bash` from Bash, Fish or Zsh. Python 3.9+ is required after bootstrap.

```bash
bash setup.sh prerequisites check
bash setup.sh prerequisites install --dry-run
bash setup.sh prerequisites install --yes
bash setup.sh prerequisites install --with-ui --yes
bash setup.sh --check
bash setup.sh packages plan --profile=minimal --dry-run
bash setup.sh packages install --select git,curl --yes
bash setup.sh packages search git
bash setup.sh packages install --select REQUEST --replace REQUEST=EXACT_NATIVE --yes
```

Direct installation automatically preflights Python; llama.cpp builds also preflight Git, CMake, Make, C++ and CA certificates. Lerd installation checks Podman on eligible systemd hosts. Optional Gum is never installed implicitly by wizard preflight. All sources must already be configured and verified by their native manager. Offline cache absence reports unavailable; it never justifies repository additions. No fuzzy replacement is installed automatically. Exit 5 means at least one selection is unavailable.

In the wizard, use Space to check the categories you want and then press Enter. Choose **All categories** for a full catalog review. In the text wizard, enter category numbers or `all`. Choosing only **Browsers** checks only browser packages. The final review shows the package IDs and sources awaiting installation approval.

Open the graphical dashboard with `bash setup.sh dashboard open` or choose it from `bash setup.sh menu`. The dashboard opens on **System**, with operating system, hardware, storage and AI eligibility. In **Packages**, select from the searchable catalog or expand **Custom package** to look up configured sources. Choose **Next: preview selected packages** to review verified IDs and sources, then **Proceed with installation**. The package manager resolves dependencies at execution. Use **Previous** to revise the selection. Reinstall appears in the confirmation only for installed selections. **Download plan JSON** saves the resolved selections. The native replay workflow is `bash setup.sh packages restore PLAN.json --dry-run`; review the result before applying. Mixed-provider plans also record their sources and can be used as an inventory.

Launch the dashboard from your regular interactive terminal to apply changes. Each tab keeps its own operation output for the current dashboard session. A modal highlights pending sudo authentication or AUR recipe review. Respond in the launching terminal. The dashboard listens only on loopback. Press Ctrl+C in the terminal to close it. The existing `dashboard export REPORT.html` command creates a standalone report.

**Configure → Lerd** checks for the executable and host compatibility. On supported hosts, **Review and install Lerd** previews the official installer when the executable is missing. **Review Lerd setup or repair** previews running setup with the existing executable. The toolbar asks for confirmation before applying either action. [Lerd installation guide](https://lerd.sh/getting-started/installation)

**System** reads KDE, Qt, CPU and graphics details from KDE's system information when available. Other desktops use the Linux hardware inventory. Manufacturer, product and system version come from available firmware data.

An installed native alias satisfies the selection, including `intellij-idea-oss` for IntelliJ IDEA Community on Arch-based distributions. On Arch, missing packages use verified native repositories or an enabled exact AUR match. If neither resolves, review the search results and select the actual package ID. Flatpak installation on Arch requires the explicit Flatpak preference. Other supported distributions retain their configured Flatpak fallback.

On Arch-family distributions, the dashboard detects working Shelly, yay, paru and Pamac commands. Exact matches from working helpers can enter the reviewed plan without another enable prompt. Noninteractive CLI calls require `--enable-aur` or saved approval. [Shelly CLI reference](https://www.seafoam-labs.org/shelly-alpm/docs/cli-reference/#shelly-search-aur)

To approve the toolkit package plan from the CLI, add `--no-confirm` to `packages install` or `packages repair`. It has the same approval scope as `--yes` for those commands. For Postman via AUR:

```bash
bash setup.sh packages install --select postman-bin --enable-aur --no-confirm
```

Sudo authentication and Shelly's AUR prompts stay in the terminal. AUR installs using the toolkit flag require interactive terminal input. Shelly 3.2.1 uses its own `--no-confirm` to automatically accept ordinary recipe reviews and the final install transaction, so the toolkit leaves that flag off AUR helper commands. [Shelly AUR safety guide](https://www.seafoam-labs.org/shelly-alpm/docs/aur-safety/)

**Configure** includes Zed telemetry status, disable and restore. Restore uses a private receipt for the two Zed telemetry keys. **Maintenance** includes diagnostics, inventory and toolkit cache cleanup. **Local AI** detects llama.cpp, Ollama and vLLM through local executables, process names and systemd units. The toolkit manages llama.cpp. Preview the managed install, select an existing GGUF path, and install or control its owned service from the dashboard. Use the CLI for custom storage, model downloads, or tuning. See [managed llama.cpp](../INSTALL-LLAMACPP-FIRST.md).

### Local AI and Project Sites

Use **Local AI → AI Configuration** to choose this computer or a trusted SSH server. The selection is shared by installation, model storage and testing. **AI Installation** has two steps: **Check and build**, then **Configure service**. You can compile llama.cpp before choosing a model or let the first local installation build it. The service page links directly to the model picker, which offers a return to service configuration after selection. The eligibility preview shows a summary and detailed JSON.

The save confirmation on AI tabs means the dashboard stored the choices in this browser. **Build binary only** compiles the executable. In **Configure service**, choose a GGUF, use **Preview configuration**, then approve **Install and test** to save the host configuration, register the systemd service, enable it at boot and start it. A running service continues after closing the terminal and dashboard. The dashboard displays saved host configuration, service state, boot enablement and API readiness separately.

**Configure → Terminal** detects Bash, Fish and Zsh, offers native installation for missing shells, and has a separate account login-shell action. Apply toolkit settings separately to each shell you use. The Fish greeting, fetch banner, existing toolkit SSH agent and exact legacy-block migration are optional. Review changes before applying, then open a new terminal. The existing private developer backup and restore workflow protects previous settings. Lerd and the shells have dedicated dashboard pages, while existing CLI package plans still work.

Applying shell settings writes a short, marked source block into the startup file. It replaces an older toolkit-managed block and preserves surrounding settings. The helper stays in the toolkit checkout. If you move the checkout, reapply from its new location. Banner display and Terminal AI are interactive-only.

Use **Preview existing configuration** to inspect the selected shell's current startup file before reviewing a change. The read-only preview shows the path and distinguishes missing and empty files. It opens on request and keeps the contents out of operation output. Shell files can contain private values.

Choose each development command, cleanup alias and Terminal AI command in **Configure → Terminal**. A fresh toolkit block starts with no commands selected. Previously managed commands are loaded as saved. Lerd detection provides context for deciding whether to enable Sail. The optional Fish and Zsh cleanup aliases delete the corresponding dependency directory and lockfile when invoked, then reinstall. Existing definitions take precedence. When replacing recognized legacy blocks, select the commands to keep in the new toolkit block.

Dashboard links retain the current tab across refresh and support browser Back and Forward. For example, `#configure/terminal/zsh` opens Zsh settings and `#ai/ai-model-setup/testing` opens model testing.

With Terminal AI enabled and llama.cpp running, use `ai ask "How do I check port 8080?"` or `systemctl status automation-llamacpp | ai ask "Why is this failing?"`. Run `ai suggest "find large files in this directory"` to print one suggested command. In an interactive Bash, Fish or Zsh prompt, type a partial command or request and press **Ctrl+X**, then **Ctrl+A**. The suggestion fills the editable command line so you can review it before pressing Enter. Existing shortcut bindings take precedence. If another tool already uses `ai`, use `automation_ai`. Terminal AI sends your prompt or selected input to the local server without capturing terminal history.

The service port is the HTTP listener on the inference host's loopback interface, normally `http://127.0.0.1:8080/v1`. Leave it blank to retain the installed port or use 8080 for a new service. **Check loopback port** distinguishes a free port, a healthy llama.cpp API and a port that cannot be bound or verified. The toolkit LAN gateway requires the backend port 8080. SSH checks run against the server's own loopback.

**Local AI → Models & Testing → Storage & Downloads** scans the chosen data root and its immediate `models/` folder for reusable single-file GGUFs. It excludes symlinks and incomplete or split-model filenames. The searchable catalog fills each pinned download's URL, exact bytes and SHA-256. Custom local downloads require an independently verified SHA-256 and byte size. For SSH, choose a server-side file or use the reviewed download and install commands from the remote toolkit directory. Use an updated toolkit on both hosts for the new diagnostics.

**Models & Testing → Testing** shows the managed service's configured model, port and token budget. Verify API health and loaded models, read the effective context per slot from the running server, or approve a short generation test. To change context, review the total token budget and its estimated share per parallel slot. Increasing context needs verified GGUF training metadata and uses more RAM or VRAM. Approved changes restart the managed service, check runtime context and generation, and restore the prior settings if a check fails. For SSH targets, the dashboard previews the change and provides the command to apply in the server's interactive terminal.

The catalog prioritizes fitting 2026 Qwen3.5 0.8B, 2B, and 4B GGUF options, while retaining older models for compatibility. Qwen3.5 requires a recent compatible llama.cpp build. The catalog refreshes on open using the selected model folder and inference backend. Recommended entries account for CPU architecture, threads, vector instructions, current free RAM and disk, and usable VRAM when it can be measured for a compatible GPU build. The **All catalog models (manual selection)** list also includes fit warnings and the TeichAI Qwen3 4B math model distilled from DeepSeek V3.2 Speciale. The model card identifies it as a community Qwen3 distillation. [TeichAI model card](https://huggingface.co/TeichAI/Qwen3-4B-Thinking-2507-DeepSeek-v3.2-Speciale-Math-Distill-GGUF)

For hybrid CPU/GPU inference, start with automatic layer offload on a compatible CUDA build. Advanced users can set a layer count. Qwen3 4B Instruct 2507 has 36 transformer layers, so 25 of those layers is roughly 70%. That is a layer ratio, and actual GPU utilization and memory depend on context and other allocations. The small DeepSeek catalog entry is the R1-Distill-Qwen 1.5B variant. [llama.cpp GPU options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) · [DeepSeek model lineup](https://github.com/deepseek-ai/DeepSeek-R1#3-model-downloads)

**Local AI → Open WebUI** shows the rootless Podman deployment and its readiness. Choose **Review installation** to confirm the port, pinned image and data volume. The app runs independently of the dashboard. Use **Start Open WebUI** or **Stop Open WebUI** to control it, and **Test Open WebUI** to check the app and its sign-in requirement. Test model generation under **Models & Testing**. [Open WebUI Podman guide](https://docs.openwebui.com/getting-started/quick-start/)

**Local AI → ChatGPT Lite** distinguishes build output from a running server. After building, choose **Start preview** for a dashboard-session server or **Start in background** to keep it running after the dashboard closes. Background mode requires a systemd user manager and runs for its lifetime. The dashboard verifies the loopback page before showing the link. Use **Test ChatGPT Lite** to repeat the check.

**Configure → Configuration and Project Sites** previews every missing folder and file. The optional PHP checkbox creates `Testing/toolkit-php-check/index.php` only when absent. It returns a plain readiness message and exposes no PHP configuration. The same option is available with `bash setup.sh projects layout --php-sample --dry-run`. The sample requires a PHP-capable development server to execute.

### Source formatting

Run `python3 scripts/format.py --check` in a Git checkout to review formatting across supported source files. Use `--write` to apply formatting, or append checkout-relative paths to limit the scope, such as `python3 scripts/format.py --write lib/dashboard_ui`. The command uses Prettier for web assets, Markdown, JSON and YAML, Ruff for Python, and shfmt for shell scripts. It uses installed tools, including the existing ChatGPT Lite Prettier when available. It skips ignored untracked files, symlinks, generated dependency lockfiles, binary assets and templates.

`--check` overrides a mutating request; `--dry-run` cannot write exports, clear caches, send inference prompts or initialize configuration. Plan exports are deliberately disabled by the read-only contract. Use `packages export --output /tmp/plan.json`, profile export, or dashboard export explicitly when you want files written.

```bash
bash setup.sh config init --yes
bash setup.sh config show
bash setup.sh profiles list
bash setup.sh profiles export /tmp/my-profile.json
bash setup.sh profiles import /tmp/my-profile.json
bash setup.sh projects init python /tmp/new-project --dry-run
bash setup.sh desktop status
```

Default settings come from `config/defaults.env`, overridden by a saved profile, `.env`, environment, then CLI. `.env` initialization merges missing keys without changing existing values and writes private permissions. Local defaults contain no credentials. Invalid/duplicate keys, command interpolation and symlink config paths are refused.

Lerd, desktop favorites, AI commands and update examples are documented in the [README](../README.md), [llama.cpp guide](archlinux-llamacpp.md) and [migration guide](legacy-migration.md). Existing installed packages win over source preferences. Selecting Lerd suppresses standalone overlapping runtimes without stopping existing services. Inventory never grants automatic uninstall rights.

The compatibility boundaries below distinguish package-test evidence from remaining real-host limitations.

## Observed distribution differences

Tumbleweed currently packages the default Python runtime as `python313`; that release-specific mapping still requires an exact configured-repository check. Leap 15 retains its existing `python3` candidate. On Fedora/RHEL, an installed `curl-minimal` owning `/usr/bin/curl` is preserved using RPM ownership rather than forcing full-curl replacement.

Fedora 40+ provides `wget2-wget` for the wget command. It has different FTP/WARC behavior. This toolkit does not silently choose it when `wget` is unavailable; an explicit selection is required:

```bash
bash setup.sh packages install --select wget --replace wget=wget2-wget --yes
```

References: [Fedora change](https://fedoraproject.org/wiki/Changes/Wget2asWget), [RPM provider queries](https://ftp.rpm.org/max-rpm/ch-rpm-query.html), [openSUSE source package](https://src.opensuse.org/pool/python313).

## Local configuration and services

`developer git --name NAME --email EMAIL` edits only the current user's Git identity using Git's own parser. `developer shell --shell bash|zsh|fish` adds an idempotent managed PATH/function block, preserving existing aliases/functions and deduplicating PATH even when sourced repeatedly. `vbin TOOL ARGS...` executes the selected local vendor tool and preserves argument boundaries and its exit code; pint/sail/fixer/pest/phpunit shortcuts are added only when absent. `--banner fastfetch|neofetch` enables an already installed tool in interactive sessions only; the default is none. Apply with confirmation/`--yes`, preview with `--dry-run`, and use `developer restore BACKUP.json --yes` to restore a private backup while refusing subsequent user edits. Login shells and existing SSH keys are never changed implicitly.

## SSH and old Git backups

```bash
bash setup.sh prerequisites check --runtime-only --with-ssh --without-ui
bash setup.sh developer ssh-generate --identity-file "$HOME/.ssh/toolkit-example" --dry-run
bash setup.sh developer ssh --identity-file "$HOME/.ssh/existing-key" --ssh-host code-host --hostname github.com --ssh-user git --dry-run
bash setup.sh developer ssh-add --identity-file "$HOME/.ssh/existing-key" --dry-run
```

SSH generation is a separate explicit action. Apply it from an interactive terminal with `--yes`; native ssh-keygen prompts for a passphrase and never overwrites an existing private/public key. Missing OpenSSH commands use the exact native prerequisite bootstrap after approval. `ssh-add` requires an existing agent; it never launches or persists one. Enroll the resulting public key with your provider manually, following the provider's documentation.

`developer ssh` writes only `~/.ssh/automation-toolkit.conf`, with a private backup. Use it explicitly with `ssh -F ~/.ssh/automation-toolkit.conf code-host`; it is not injected into existing SSH/Git settings. Host-key verification is strict, so verify/enroll the server's known-host key separately using the provider's official fingerprints. Replacing a differing toolkit connection config requires its reviewed `--current-sha256`. Existing config, known_hosts, transport rewrites and agents remain untouched; no network connection occurs while configuring.

`developer import-git-backup /absolute/old.gitconfig --current-sha256 CURRENT_SHA256 --yes` validates one selected legacy backup with Git's local parser, without following includes or printing credentials. Obtain CURRENT_SHA256 from the current `~/.gitconfig` bytes (the SHA-256 of empty bytes if absent). It creates a private restore receipt and leaves the active configuration unchanged. Restore with `developer restore RECEIPT.json --yes`; later edits cause refusal. No root-owned legacy state pointer is evaluated, no packages are uninstalled, and original backups are preserved.

References: [OpenSSH key generation](https://man.openbsd.org/ssh-keygen), [SSH configuration](https://man.openbsd.org/ssh_config), [openSUSE OpenSSH packaging](https://src.opensuse.org/pool/openssh), [Alpine OpenSSH client packaging](https://pkgs.alpinelinux.org/package/v3.22/main/x86_64/openssh-client-default).

### Explicit GitHub transport and private agent persistence

```bash
bash setup.sh developer git-transport --transport ssh --dry-run
bash setup.sh developer git-transport --transport ssh --yes
bash setup.sh developer git-transport --transport https --yes
bash setup.sh developer ssh-agent status
bash setup.sh developer ssh-agent configure --dry-run
bash setup.sh developer ssh-agent configure --yes
bash setup.sh developer ssh-agent start --yes
bash setup.sh developer ssh-agent status
bash setup.sh developer ssh-agent add --identity-file "$HOME/.ssh/your-selected-key" --yes
bash setup.sh developer ssh-agent enable --yes
```

Transport configuration edits only the exact `https://github.com/` → `git@github.com:` rule in the current user's `.gitconfig`, using Git's local parser and a private conflict-safe backup. `--transport https` removes that exact rule; it does not alter other providers, unrelated rewrite values, identities, credential helpers or repository remotes. A different exact-prefix rewrite already present in that file causes SSH setup to refuse. Includes are not read or modified by this operation; system, included and repository-local configuration can still affect effective transport. No Git network request occurs. The old implicit global rewrite is replaced by this explicit choice. See [Git configuration](https://git-scm.com/docs/git-config).

The controller owns only `automation-ssh-agent.service` in the user's systemd directory. It refuses an existing loaded/unrelated unit, edited unit file or pre-existing runtime directory at its reserved path. Configuration requires an available user manager, writes the unit exclusively after backup and reloads unit definitions; it never starts/enables an agent or loads keys. Failed reload rolls back its own unchanged new file and preserves concurrent edits. Start, stop, enable and disable are separate reviewed actions targeting that exact unit; no session/other agent is restarted. Enabling schedules the owned unit for future user sessions without loading keys. Keys must stay outside the volatile agent runtime directory; later unknown files there prevent toolkit startup/stop from proceeding so they can be preserved manually.

The unit runs the reviewed native `ssh-agent -D` with a private runtime directory/socket, mode 0700/0600 and no shell `eval`. Socket location is `$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock`; unsafe runtime directories, symlinks and non-socket objects are refused. Status reports readiness without logging fingerprints or identity comments. `add` requires the owned service to be active and its private socket ready, validates one explicit private key path and sends the request to that socket only. The caller's current `SSH_AUTH_SOCK` and other agents remain unchanged. No default key is generated or loaded implicitly; encrypted identities retain native OpenSSH passphrase handling. A successful start request does not replace the explicit socket-readiness check.

```bash
bash setup.sh developer shell --shell bash --use-toolkit-agent --dry-run
bash setup.sh developer ssh-agent disable --yes
bash setup.sh developer ssh-agent stop --yes
bash setup.sh developer ssh-agent uninstall --yes
```

The optional shell block selects an already-existing toolkit socket only when no `SSH_AUTH_SOCK` is selected, skips symlinked runtime/socket paths and never launches an agent or loads a key. Configure each desired Bash/Zsh/Fish startup file explicitly. Existing agents take precedence. Disabling does not stop the process; stopping is separate. Uninstall requires the unit already stopped and disabled, then backs up/removes its file without deleting keys, shell files or other agent state. `developer restore BACKUP.json --yes` refuses active/enabled agent state or later file edits; after review, use `developer ssh-agent reload --yes` to reload a restored/removed definition. Restore does not start it.

Unit creation/lifecycle/refusal/rollback have fixture coverage, static systemd verification passed, and native temporary agent protocol/key loading and teardown are tested separately. Disposable distribution workflows test native client packages, an isolated agent/socket and Git URL expansion without remote authentication. Actual host user-manager startup/autostart and real provider enrollment remain separate gates. Public-key enrollment, trusted-host fingerprint review and remote SSH authentication are manual; the removed installer no longer accepts new host keys automatically or removes packages from old install receipts. References: [ssh-agent](https://man.openbsd.org/ssh-agent), [ssh-add](https://man.openbsd.org/ssh-add), [systemd runtime directories](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

### Recovering old shell configuration

```bash
bash setup.sh developer shell --shell fish --fish-greeting off --dry-run
bash setup.sh developer shell --shell bash --migrate-legacy --current-sha256 REVIEWED_CURRENT_SHA256 --dry-run
bash setup.sh developer import-shell-backup /absolute/reviewed-old-shell.backup --shell zsh --current-sha256 REVIEWED_CURRENT_SHA256 --dry-run
```

`--migrate-legacy` replaces only exact paired legacy fetch/dev/PHPV/greeting marker blocks and the exact old auto-agent block. When removal would change bytes, supply the SHA-256 of the reviewed current file. Missing/nested/mismatched markers, unpaired old headers and edited auto-agent blocks are refused; timestamp-like user lines and unknown content are never deleted by a heuristic. Choose the new banner, greeting and socket options explicitly. Legacy functions inside the reviewed blocks are replaced by the maintained safe PATH/vendor-tool functions; destructive lock-file deletion aliases are not recreated.

The selected shell must already be installed. The complete candidate is syntax-checked in a temporary home with no startup configuration loaded; neither the current file nor a backup is executed. Fish greeting defaults to preservation; `--fish-greeting off` adds a managed preference for Fish only. Login-shell changes, third-party plugins and unmarked legacy debris are left for manual review. Apply a reviewed change with `--yes`; a private backup precedes replacement, and the current bytes are rechecked after approval.

`import-shell-backup` reads only one explicit bounded regular backup, validates its syntax, checks the current file digest and creates a private restore receipt. It never follows an old state pointer, modifies the original backup or activates it. Restore is separate, syntax-checked and refuses subsequent/concurrent edits, including edits during the approval prompt. No shell is sourced or restarted by configuration/import/restore.

## Setup checks and manual checklist

```bash
bash setup.sh checklist list
bash setup.sh checklist check
bash setup.sh checklist automate --select configuration,projects --dry-run
bash setup.sh checklist automate --select configuration,projects --yes
bash setup.sh checklist done theme --yes
bash setup.sh checklist skipped drivers --yes
bash setup.sh checklist pending theme --yes
bash setup.sh checklist review
```

`check` automatically observes dependency availability, active desktop, Git configuration-file presence, runtime configuration completeness/private permissions and the configured Project Sites layout. It creates no state, sends no API requests or inference prompts, and does not certify logins, service health, Git identity values or GPU acceleration.

`automate` requires an exact, explicit selection: `configuration` and/or `projects`. It reuses the existing configuration merge and project-layout helpers, validates the whole selection before approval, preserves original values/files, creates only missing directories and skips already-ready steps. `AUTOMATION_PROJECT_SITES_DIR` is respected; otherwise the root is `~/Documents/Project-Sites/`. No package manager, desktop setting or service is changed by these actions. Dry-run never asks approval or writes. If execution is interrupted after a completed step, rerun the same selection: observed files determine remaining work, without another progress database.

Git identity (`identity`) and package installation (`software`) were removed from the active manual list because `developer git` and `packages` already implement them. `list` provides maintained workflow guidance. Existing acknowledgements for those two IDs are preserved as `archived_progress` and survive future progress updates; old mutation commands for them now point to the maintained workflow. Package installation is not confused with personal update/tray preferences, which remain desktop choices.

The remaining 25 manual tasks retain stable IDs and private progress under the configured state directory. Listing and dry-run create nothing. Review requires a terminal and approval; cancellation/invalid input saves no partial answers. These are manual acknowledgements: marking a driver, account or desktop task done never applies settings, installs drivers or certifies a successful integration. No credentials or personal connection details are recorded. Desktop preferences and account logins are not implicitly automated.

## Existing AI state migration

Only llama.cpp inference is managed. Existing third-party services, their
settings and model stores are preserved. Use the verified GGUF workflow below
to copy compatible assets. For runtime installation and model switching, see
[the dedicated server guide](../INSTALL-LLAMACPP-FIRST.md).

### Complete GGUF bundles and old selection recovery

```bash
bash setup.sh ai llamacpp gguf-legacy-list --legacy-root /absolute/old-llamacpp
bash setup.sh ai llamacpp gguf-download --manifest /absolute/reviewed-gguf-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-download --manifest /absolute/reviewed-gguf-bundle.json --yes
bash setup.sh ai llamacpp gguf-list
bash setup.sh ai llamacpp gguf-resolve --manifest /absolute/reviewed-gguf-bundle.json
bash setup.sh ai llamacpp gguf-legacy-import --legacy-root /absolute/old-llamacpp --manifest /absolute/reviewed-gguf-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-remove --manifest /absolute/reviewed-gguf-bundle.json --dry-run
```

These actions use only Python's standard library. Supply an independently reviewed bundle manifest with one explicit public HTTPS URL, exact size and SHA-256 for each file, plus the repository, exact revision and a quantization label. URLs cannot contain credentials, query strings, whitespace or control characters. Server-generated HTTPS redirects remain supported with final size/hash verification. Labels identify the operator's reviewed choice; they do not prove the actual quantization, publisher provenance or model quality.

For example, this tiny test fixture is a complete single-file bundle, not a model recommendation:

```json
{
  "schema": 1,
  "repository": "ggml-org/tiny-llamas",
  "revision": "def3e2dd70df35ecbf6403ea347de4c5977220c1",
  "quantization": "fixture",
  "files": [
    {
      "path": "stories260K.gguf",
      "size": 1185376,
      "sha256": "047bf46455a544931cff6fef14d7910154c56afbc23ab1c5e56a72e69912c04b",
      "url": "https://huggingface.co/ggml-org/tiny-llamas/resolve/def3e2dd70df35ecbf6403ea347de4c5977220c1/stories260K.gguf"
    }
  ]
}
```

For split models list **every** adjacent `BASE-00001-of-000NN.gguf` through `BASE-000NN-of-000NN.gguf` file, each with its own independently verified size/hash/URL. The bundle must contain exactly one unsharded file or one complete consistent shard series. Mixed families, multiple single models, missing/duplicate shards, projectors and unsafe filenames are refused. Resolution always returns shard 1 regardless of manifest order. The native runtime loads the neighboring shards; the toolkit does not merge or reinterpret tensor data. See the [upstream server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) and [GGUF split utility](https://github.com/ggml-org/llama.cpp/blob/master/tools/gguf-split/README.md).

Before the first network/write, bundle download validates all existing artifact identities and receipts. After approval it checks RAM against the **whole** bundle plus a reserve, and disk against missing downloads plus a complete separate published copy. Unknown/insufficient RAM or space causes refusal. Verified completed downloads are cached for retries; an interrupted/corrupt shard never activates a partial bundle. Retry reuses verified completed shards without downloading them again. Existing changed data is never overwritten. All newly created private-store ancestors use private permissions. Standalone artifact ownership receipts are issued only after exclusive activation succeeds; a failed activation cannot authorize deletion of a concurrent user's file.

Default published bundles live under `~/.local/share/automation-toolkit/ai/gguf-bundles/QUANTIZATION/PUBLISHER/MODEL/REVISION`; `--root` selects a separate private base store. The private `.downloads/QUANTIZATION/...` cache is retained for reuse. `gguf-list` hashes and validates owned bundles and labels incomplete/changed/unmanaged entries unverified. `gguf-resolve` and selection refuse those entries. Removing a bundle requires the exact reviewed manifest, an unchanged observed-copy receipt and an explicit `--yes`; related active/unknown toolkit service state causes refusal without stopping it. Download caches and original models are preserved by bundle removal.

The separate legacy GGUF helper is removed. Its remaining compatibility caller shares read-only list/resolve logic for existing files. Unpinned old download requests fail before dependency or file changes; the existing-model compatibility path requires explicit `--download=no` and validates selection before prerequisites. Marker-only deletion fails before touching services or selection files. No new virtual environment, uv or Hub package is installed just to manage GGUF metadata. These compatibility paths are not normal setup entrypoints.

Native package transactions retry only recognized lock/busy errors, up to `AUTOMATION_RETRIES`; other errors and timeouts remain failures. AI build prerequisites run after AI flags are validated, and status/lifecycle operations never install compilers. Cancellation exits 130.

Current test scopes live in the normal validator output under `~/.local/state/automation-toolkit/validation/`. Offline tests, native container package tests, static systemd checks and actual CPU inference are distinct from real host service/desktop/GPU verification. No release deliverable generation is part of local refactoring.

## Compatibility boundaries

| Representative environment  | Native detection/search/core package workflow                              | Host services / desktop / GPU                                |
| --------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Arch base                   | Disposable rootless container verified                                     | Not certified by that test                                   |
| Debian 13 / Ubuntu 24.04    | Disposable rootless containers verified                                    | Not certified by those tests                                 |
| Fedora 42 / Rocky 9         | Disposable rootless containers verified; explicit Fedora wget2 replacement | Not certified by those tests                                 |
| openSUSE Tumbleweed         | Disposable rootless container verified; version-specific Python mapping    | Leap service/desktop behavior remains unverified             |
| Alpine 3.22                 | Disposable rootless container verified                                     | OpenRC does not imply systemd-user/Lerd support              |
| CachyOS KDE/Wayland session | Host detection and read-only desktop favorites plan verified               | Desktop mutation and service installation were not performed |

The current CPU source-build path was exercised in disposable Debian using the official llama.cpp checkout (0.8.0-dev, commit `4e910a8` for that run), including automatic Make/compiler bootstrap and `llama-server --version`. This verifies that tested CPU build environment, not every compiler/distro/GPU combination. Both CPU inference sandboxes also passed protected API checks; vLLM’s model-card context check confirmed 256 tokens and detected a 512-token mismatch. Exact subsequent run status remains in the normal validation JSON.

Container package and checklist fixtures cover exact installation, repeat
operations and safe configuration. They do not certify real desktop sessions,
GPU inference or production services.

### Dashboard review and apply

Open `bash setup.sh dashboard open`. The dashboard uses a fixed loopback port so selections, model paths and checkboxes are remembered by your browser. Use the **Advanced** tab for the current toolkit settings, explicit true or false overrides, a custom absolute Project Sites directory and JSON overrides. Empty values restore defaults. Saved changes print a private backup ID that can be restored in Advanced. Shell environment overrides remain authoritative and are marked in the preview.

Choose packages and any Project Sites, Zed or llama.cpp steps you intend to apply. For native packages, use the reinstall checkbox to review a reinstall instead of an installation. **Review all changes** validates the selection and reports package IDs, sources, project directories and the configured AI model directory and port. **Apply all changes** runs configuration and project setup first, then packages, Zed and Local AI. The floating **Setup checklist** opens a right-side panel with observed checks, manual tasks, and operation status. The panel shows pending, running, completed and failed actions. An unsuccessful action stops the sequence. Retry remaining actions from the same page or refresh the review if the package plan changed.

Package alternatives must be verified against the configured native repository before being saved. The shared CLI saves them in the private `package-mappings.json` beside the toolkit journal. The mapping includes distribution, architecture, package manager, actual package ID and source. Pacman metadata distinguishes configured repositories and foreign packages. Toolkit receipts can identify the helper that actually performed a recorded installation. [Shelly command reference](https://www.seafoam-labs.org/shelly-alpm/docs/rosetta/)

**System telemetry** supports the Debian Popularity Contest configuration on Debian and Ubuntu with the compatible cron package present. Disable adds a toolkit-owned opt-out drop-in and restore removes that drop-in. Zed telemetry and Zed settings backups are separate controls. [Debian Popularity Contest documentation](https://sources.debian.org/src/popularity-contest/1.79/README)

In **Local AI**, the toolkit can install llama.cpp and control its own service. External Ollama and vLLM entries report observed local status. The launcher stays on loopback. A custom llama.cpp port requires the direct loopback configuration. The optional LAN gateway uses port 8080 internally. **ChatGPT Lite** previews its build paths and loopback URL, builds the checked-in client, and can clear its generated build directory.

The **Zed settings** card in Configure provides settings and telemetry checks, apply, backup, and restore. Use **View current settings** for a read-only copy of the file. The editor previews changed keys and detected AI endpoints. If the proposed llama.cpp endpoint and model cannot be verified over loopback, the review shows the reason and offers **Apply anyway**. The CLI still validates each action and refuses conflicting restores.

The browser shows when package installation is waiting for sudo. Authenticate in the launching terminal. A valid sudo ticket is reused and refreshed during the operation under the local sudo policy. Shelly presents its own recipe and dependency review in that terminal. After an AUR failure, choose package search, enter an alternative package ID, try another installed helper, or check for a verified Flatpak match beside the operation result. The dashboard previews the selected alternative before you approve installation.

Check a manual task in the setup drawer to mark it as completed. Uncheck it to return it to pending. After an AUR failure, the alternative package field and search controls appear beside the operation result.

### Dashboard sections

**Home** links to the workflow pages and provides a read-only hardware check. In **Install**, select packages for review, then use **Preview selected packages** to resolve their exact sources. The confirmation offers **Reinstall selected packages** when the review includes installed packages. Reinstall resolves exact repository packages, verified native Shelly packages, an installed Flatpak's recorded remote, or an exact AUR recipe via an enabled helper. Helpers retain their normal recipe review. Alternative previews preserve other selections.

**Advanced** contains combined setup review, apply, Project Sites and the Zed defaults checkbox. The editor shows the toolkit defaults separately from effective values. **Configure → Zed settings** can merge missing values, override the keys in a JSONC input, or replace the settings object. Preview lists added, changed and removed key paths. The existing private backup and restore workflow preserves the original file bytes. The toolkit validates JSONC structure and common setting types. Zed owns the complete, version-specific settings schema.

**Maintenance → System Cleanup** inspects package caches, orphan candidates and journal usage. The preview counts native candidates and estimates their bytes. Arch systems with `paccache` can remove older cached package versions while retaining three. Debian-family systems can remove obsolete archives with APT autoclean. Unused packages, temporary files and logs are review information. [paccache manual](https://man.archlinux.org/man/paccache.8)

CPU is the default for new builds. GPU detection identifies a build candidate and real inference verifies the installed configuration. SSH requires an updated toolkit at the specified server path, an already trusted host key and an existing SSH key or agent. Install, download and change context from the SSH terminal to handle native prompts. Dashboard start, stop or restart of the remote toolkit-owned service requires suitable noninteractive sudo authorization there. [OpenSSH manual](https://man.openbsd.org/ssh)
