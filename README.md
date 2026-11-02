# Linux Automation Toolkit

Use `bash setup.sh` for platform-aware package planning and approved installation.
Python 3.9+ and Bash 4.4+ are required; Bash-only prerequisite bootstrap works before Python is available.

Python handles structured work: package metadata, JSON validation, HTTP checks,
checksums, private receipts and conflict-safe file updates. Its standard library
keeps these consistent across distributions without adding Python dependencies.
Bash remains the entrypoint and pre-Python bootstrap, and invokes native tools.
Using more Python reduces shell quoting and text-parsing risks; it does not
require replacing straightforward shell wrappers.

```bash
bash setup.sh --help
bash setup.sh --check
bash setup.sh packages plan --profile=minimal --dry-run
bash setup.sh packages search git
bash setup.sh packages install --select git,curl,wget,unzip --yes
bash setup.sh wizard
```

Installation commands automatically preflight their runtime requirements. `--yes` approves the displayed installation; a noninteractive command without approval refuses changes. Read-only commands and `--dry-run` do not bootstrap packages or write configuration/cache/export files. Gum is optional, with a text fallback.

Configured native repositories are checked for exact package names. Similar names are suggestions only. Unavailable installation selections return exit code 5; they do not become implicitly approved alternatives. No repositories or Flatpak remotes are added. AUR/Shelly require an Arch system and explicit source approval. Immutable hosts and WSL are planning targets by default.

## Configuration

Safe defaults ship in `config/defaults.env`; the old example file is removed.

```bash
bash setup.sh config show
bash setup.sh config init --yes
```

`config init` creates `.env` with mode 0600 or adds missing settings without changing existing values. Approved package/AI installation can initialize it automatically. Read-only commands use defaults without creating `.env`. Local environment files stay ignored and are never executed or logged. Values are parsed as allowlisted data, never executed.

## Lerd and AI

```bash
bash setup.sh lerd status
bash setup.sh lerd install --dry-run
bash setup.sh ai list
bash setup.sh ai hardware --json
bash setup.sh ai llamacpp check
bash setup.sh ai llamacpp install --yes
bash setup.sh ai llamacpp key-generate --yes
bash setup.sh ai llamacpp key-status
```

Lerd uses its public CLI only. Selecting compatible Lerd suppresses redundant standalone PHP/Composer, Node/npm, database and web-server packages; existing installations/data are preserved. Arch AI now uses the same portable Python dispatcher as other families. Existing legacy units/model stores are not adopted or deleted.

llama.cpp supports a CPU source build, existing GGUF serving, bounded API/inference/context diagnostics, receipt-based checksum downloads/removal and native key files. Keys are never put in argv or ordinary logs. See [AI guide](docs/archlinux-llamacpp.md). Ollama provides explicit installer/pull/foreground serving operations. Toolkit-owned user-service configuration/lifecycle/autostart is implemented with fixture and static-unit verification; real host systemd operation still needs a supported-session test. Native vLLM installation, Jan GUI setup and GPU acceleration remain separately unverified. Service uninstall removes only its owned unit and preserves models/binaries/keys.

## Desktop and updates

```bash
bash setup.sh desktop status
bash setup.sh desktop plan --select firefox.desktop
bash setup.sh desktop apply --select firefox.desktop --yes
bash setup.sh desktop restore BACKUP.json --yes
bash scripts/update.sh --check /path/to/automation-patch.zip
bash scripts/update.sh --apply /path/to/automation-patch.zip
bash scripts/update.sh --rollback
bash scripts/update.sh --recover
bash scripts/update.sh --full-check /path/to/automation-full.zip
```

GNOME/KDE favorites use explicit application IDs and backups, with conflict checks on restore. Other environments are detected and reported unsupported for favorites. Real desktop changes require separate session verification.

Local update ZIPs require checksums and safe manifests, with no signing-key setup or `--allow-unsigned` requirement. Full ZIP upgrades use the same backup/rollback engine. Use the **new release updater** to apply the first migration to an older tree: see [migration](docs/legacy-migration.md). Never overwrite a modified prior release blindly.

## Validation and compatibility

```bash
python3 scripts/validate.py --mode offline
python3 scripts/validate.py --mode containers --engine podman --require-containers
python3 scripts/container_workflows.py --allow-install --with-lint --output /tmp/toolkit-packages
python3 scripts/ai_sandbox.py --yes --allow-download --output /tmp/toolkit-ai
```

Container images are not pulled without `--allow-pull`. Package integration installs only into disposable rootless Podman layers. The AI sandbox uses a checksum-pinned 1.2 MB CPU test model and removes only its own temporary model/key/container. No developer packages, services, databases or model caches are changed. Unit mocks, distro probes, container installs and real-host/GUI/GPU tests are distinct evidence.

See [setup guide](docs/unified-setup.md), [architecture](docs/unified-architecture.md), [setup](docs/unified-setup.md), [documentation index](docs/index.md) and [contributor rules](AGENTS.md).

Project directory creation, Lerd PHP guidance, reviewed USB exports and
rootless Open WebUI lifecycle are described in the [configuration guide](docs/configuration-and-webui.md).
Their verification boundaries are explicit. The opt-in actual app sandbox tests WebUI authentication, recovery and persistence separately from model inference or browser UX.

The legacy installer module is removed. Its maintained replacements and owner-approved retirements are recorded in the [migration ledger](docs/legacy-migration.md). Development runtimes and services use Lerd; existing host data and installations are preserved. The [portable Laravel server toolkit](laravel/README.md) provides independently runnable production provisioning and release deployment. Its own `.env`, helpers, templates, documentation and tests all live in `laravel/`; optional `setup.sh laravel provision|deploy` only delegates to its two entrypoints.

## Owned AI services and developer configuration

```bash
bash setup.sh ai llamacpp api-config
bash setup.sh ai llamacpp model-search --query tiny --limit 5
bash setup.sh ai llamacpp configure --model /absolute/model.gguf --key-file /absolute/private/api-key --context 4096 --yes
bash setup.sh ai llamacpp service-status
bash setup.sh ai llamacpp start --yes
bash setup.sh ai llamacpp stop --yes
bash setup.sh ai llamacpp restart --yes
bash setup.sh ai llamacpp autostart --enabled yes --yes
bash setup.sh ai llamacpp logs
bash setup.sh developer status
bash setup.sh developer git --name "Your Name" --email you@example.com --dry-run
bash setup.sh developer shell --shell fish --dry-run
```

Model discovery never approves downloads. `model-select` is an alias for explicitly configuring a reviewed local model; active services must first be stopped. `configure` never starts/enables a unit. Services use `automation-ai-BACKEND.service`; existing units and shared model caches are never adopted or deleted. After changing a stored key, explicitly restart a configured service and run `test-auth` to verify enforcement. Jan supports probing an existing local API, model listing and auth/inference checks; its GUI is managed separately.

Developer changes require `--yes` (or confirmation), create a private backup and preserve unrelated settings. `developer restore BACKUP.json --yes` refuses to overwrite later edits. No SSH keys, credential stores, login shells, service policies or third-party shell plugins are changed implicitly. This task works locally and produces no new release archives or standalone delivery reports.

Setup checks use `checklist check`; `checklist automate --select configuration,projects --dry-run` previews the existing configuration merge and Project Sites layout, and `--yes` applies only missing steps. The 25 remaining manual tasks use `checklist list`, `checklist review` or `checklist done TASK_ID --yes`; these records are acknowledgements only. Duplicate Git identity/package tasks are replaced by maintained workflow guidance, with old progress preserved. Explicit SSH enrollment uses `developer ssh-generate`, `developer ssh` and `developer ssh-add` with a selected `--identity-file`; existing keys, agents and SSH config are preserved. Old Git backups can be imported into conflict-safe restore receipts. Shell integration includes working vendor-tool functions and an optional installed fetch banner. See the [migration commands and safety boundaries](docs/unified-setup.md#ssh-and-old-git-backups).

AI discovery supports Hub activity ordering/pagination and `model-files` metadata at an exact commit, without downloading models. `key-import` handles an explicit private old raw/env key. CPU llama.cpp and reviewed vLLM `legacy-plan`/`legacy-import` can migrate supported old settings into a new owned unit after the operator stops/disables the old one. vLLM preserves dtype, CPU controls, supported native tool-parser choice and the served alias; it uses a separate private runtime cache and never executes old environment files. Native vLLM/Playground installation is retired from the toolkit; actual host service operation remains separately unverified.

```bash
bash setup.sh ai vllm cache-list --cache-root /absolute/existing/hub
bash setup.sh ai vllm snapshot-import --cache-root /absolute/existing/hub --manifest /absolute/reviewed-model.json --root /absolute/private/toolkit-snapshots --dry-run
bash setup.sh ai vllm snapshot-remove --root /absolute/private/toolkit-snapshots --model publisher/model --revision EXACT_40_HEX_COMMIT --dry-run
```

Revision inventory is read-only. Copying requires a reviewed manifest with independent SHA-256 values, sizes and an exact revision; the original cache stays intact. Removal applies only to the observed toolkit copy and refuses later edits, extra files or a related active toolkit service. The old unreceipted cache-deletion helper is removed; its retained caller fails before changing services or selections. [Existing AI state migration](docs/unified-setup.md#existing-ai-state-migration) documents manifests, interrupted-copy handling, supported settings and verification boundaries.

Complete GGUF models use `ai llamacpp gguf-download/list/resolve/select/remove`. A reviewed manifest names one file or a complete adjacent shard set with explicit URLs, independent checksums and exact sizes. Downloads check the whole model's RAM/disk budget and reuse completed verified shards after failure. `gguf-legacy-list/import` reads old markers/selection/context as data and copies checked assets into a separate store. `gguf-select --yes` recovers the new owned selection without activating a service or altering original files. The replaced standalone GGUF helper is removed; [GGUF bundle usage](docs/unified-setup.md#complete-gguf-bundles-and-old-selection-recovery) explains manifests and recovery.

GitHub transport rewriting is explicit through `developer git-transport --transport ssh|https`. `developer ssh-agent configure/start/stop/enable/disable/status/add/uninstall` manages only a private toolkit-owned user unit, with separate approval for lifecycle changes and selected-key loading. It never adopts an existing agent, accepts host fingerprints or loads a default key. The replaced Git installer is removed. [Transport and agent usage](docs/unified-setup.md#explicit-github-transport-and-private-agent-persistence) distinguishes native fixture verification from actual host user-session/autostart testing.

Shell migration supports `--migrate-legacy --current-sha256 REVIEWED_SHA256`, explicit Fish greeting preferences, opt-in use of an existing toolkit agent socket, and private `import-shell-backup` receipts. Exact legacy blocks are replaced only after review/backup; ambiguous content is refused and syntax checks never execute the shell file. Restore refuses later and concurrent edits. Login-shell/plugin preferences remain manual; [shell recovery](docs/unified-setup.md#recovering-old-shell-configuration) documents the supported scope.
