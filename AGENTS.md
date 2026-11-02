# Automation Toolkit — Agent and Contributor Contract

## Maintained architecture

- Use `bash setup.sh` for normal operation. CLI orchestration is in `lib/automation.py`, shared package adapters in `lib/providers.py`/`catalog.py`, discovery in `lib/discovery.py`/`sources.py`, progress in `lib/progress.py`, and AI dispatch in `ai/manager.py` with `ai/portable.py`.
- Do not create distribution-specific setup entrypoints. openSUSE uses zypper; Fedora/RHEL use dnf. A working OS/package adapter does not establish AI, desktop or Lerd support.
- Keep Python 3.9+, Bash 4.4+ and standard-library-only portable libraries. Invoke Bash files with `bash` from Fish/Zsh; never source them.
- The `modules/legacy/` installer directory is removed. `docs/legacy-migration.md` records verified replacements and owner-approved retirements. Do not recreate or relocate the old installers. Bounded old-user-state importers remain supported. Laravel production workflows are self-contained in `laravel/` (including its own contract, private configuration, templates, helpers and tests). Optional root CLI integration must only delegate to its entrypoints; never introduce parent dependencies. Production mutations retain their separate approval controls.
- No Git branches, worktrees, staging, commits or tags. Preserve unrelated user work. Do not modify secrets, developer databases, existing models, package repositories or services as part of tests.

## Approval, prerequisites and configuration

- Mutations require explicit review/approval (`--yes` for automation). `--check`, help, doctor, status, package planning and `--dry-run` must never install packages, initialize `.env`, export files, clear disk caches, change services or send inference prompts.
- Bash-only `setup.sh prerequisites` must work before Python is installed. Direct installation commands automatically preflight operation-specific dependencies. Core prerequisite bootstrap must use enabled native repositories and exact package names only; no repository additions or fuzzy substitutions.
- Gum, ShellCheck, shfmt and crun are optional. `wizard` must not implicitly install Gum. Reject unknown platforms and treat immutable systems/WSL as planning targets by default.
- `config/defaults.env` contains safe public defaults. `.env` is ignored by Git and excluded from releases. `config init --yes` merges only missing settings, preserves existing bytes/values and writes mode 0600. Approved package/AI installation may initialize it; read-only commands must not.
- Parse `.env` as bounded allowlisted data. Never source it, use eval, accept executable hooks, or load arbitrary Python plugins. Validate profiles/providers/imported JSON and reject secrets or machine-specific paths in portable exports.

## Packages and source safety

- Query only configured repositories without adding sources or bypassing signatures. DNF queries use cache-only mode; zypper queries disable refresh. Missing metadata means unverified, never assumed available.
- Suggestions are string/name matches, not semantic equivalence or publisher provenance. Do not silently install a suggestion, including with `--yes`. `--replace requested=actual` must pass an uncached exact native check; validate tokens before argv construction.
- Revalidate exact native availability immediately before approved installation. Skip installed packages. Preserve exit code 5 for unavailable selections and report failed/post-install-unverified transactions accurately.
- AUR helpers/Shelly/pacman are Arch-only. Never run makepkg or an AUR helper as root; require explicit source consent and PKGBUILD review. Never install helpers automatically.
- Flatpak is an opt-in desktop source, not a universal substitute. Verify the exact app ID in a configured remote; never add a remote automatically.
- A Lerd selection suppresses standalone PHP/Composer, Node/npm, MariaDB/MySQL, PostgreSQL, Valkey/Redis and web servers. Preserve Git, Podman, database GUI clients and independent tools. `--allow-standalone-dev` requires explicit review. Never remove/stop existing services or initialize their data.
- Journals contain package identities/results only, directory 0700/files 0600. Ownership requires observed installation, not exit code zero. Inventory is a recovery receipt, never authorization for automatic uninstallation or OS rollback.

## Lerd, AI and desktop integrations

- Look up current official documentation before changing Lerd, Shelly, AUR, Flatpak or openSUSE packaging. Record references and verified limitations.
- Use Lerd's public CLI exclusively for its runtimes/services. Never edit its Quadlets, DNS, certificates, databases or PHP images. Optional Lerd Desktop requires a GUI, explicit approval and upstream `.flatpakref`; update that app only.
- AI hardware inspection is read-only. Device/driver-tool presence is not proof of acceleration. Keep CPU fallback explicit; never install drivers or change existing system services as a diagnostic side effect.
- AI HTTP diagnostics must be literal loopback-only, bypass proxies, reject redirects and use bounded responses/timeouts. Dry-run never sends prompts. Validate actual response structure and generated text.
- Native keys are private files (0600, directory 0700) outside the source tree, never argv or ordinary logs. Reject unsafe/symlink key paths; preserve keys on repair. Copy uses clipboard stdin or a controlling terminal, never redirected stdout. Test valid, invalid and absent credentials against the exposed protected endpoint; health endpoints are not enforcement evidence.
- GGUF downloads require explicit HTTPS URL, independently verified SHA-256 and exact size. Check RAM/disk, reuse verified cached files, and never overwrite changed models. Deletion requires explicit approval and matching toolkit receipt; never delete shared model caches.
- Expose only implemented backend operations. `ai/services.py` manages only exact toolkit-owned user units, never existing backend or Lerd units. Configuration, process state and API readiness are distinct. Native vLLM installation, Jan GUI integration, actual host systemd operation and GPU acceleration need independent verification; do not claim them from llama.cpp tests.
- Desktop adapters must match the active environment, skip headless sessions, validate exact application IDs, back up before changes and refuse restoration over later user edits. No automatic session/service restart. GNOME/KDE adapter fixtures do not establish real-session verification.

## Update/release safety

- Per the owner's local-workflow instruction, checksum-verified full/patch ZIPs do **not** require signing keys, publisher configuration or `--allow-unsigned`. Optional historical signed archives remain supported; never package private keys.
- Full and patch archives must include manifest SHA-256 values and explicit deletions. Reject traversal, noncanonical/duplicate paths, symlinks, unexpected payloads and checksum conflicts before application. Preserve `.env` and user data; never overwrite conflicts by default.
- Back up originals before changes, atomically replace files, preserve executable modes and syntax-check before activation. Test normal rollback, caught interruption, receipt-based interrupted recovery and preservation of subsequent edits, in disposable copies only.
- Work directly in the current checkout. Do not create ZIPs, patch deliverables, tags or standalone completion reports unless explicitly requested. Keep useful update/rollback code and test it in temporary fixtures. Use the existing validation output locations; the repository is the result.

## Mandatory validation

Before edits, run `python3 scripts/validate.py --mode offline` and inspect JSON results and every skipped check. Before delivery run:

```bash
bash scripts/check-scripts.sh --check
python3 -m unittest discover -s tests -v
bash setup.sh --check
bash setup.sh --dry-run --profile=minimal
bash setup.sh ai llamacpp --check --dry-run
python3 scripts/validate.py --mode offline
```

- ShellCheck/shfmt absence must be reported. Never install them or change repositories on the contributor host merely to test. Disposable container installation is separately opt-in.
- `scripts/container_probe.sh` stays POSIX, non-root, read-only, without network or package installs. `validate --mode containers` never pulls by default; use explicit `--allow-pull`, and `--require-containers` when skips must fail.
- Mutating package integration is separate: `scripts/container_workflows.py --allow-install` uses disposable rootless Podman layers and never host mounts writable. No live host installation, upgrades, sudo, `/etc` edits, model deletion, legacy provisioning, database/service changes or destructive testing.
- `container_workflows --with-system-tests` runs the full suite as an unprivileged numeric UID; do not rely on login/PAM access to expired system accounts. `--system-tests-only` reruns regressions with native prerequisites, separately from package/catalogue smoke. Service contract fixtures must explicitly mock executable availability as well as control responses; keep unsupported-system refusal tests.
- Preserve unrelated Podman clients/services when their engine is busy. Use a private per-process `CONTAINERS_STORAGE_CONF` graphroot/runroot for testing; never reset/prune or rewrite the user's shared engine. Unknown teardown or runtime-query failures are failures, not successful cleanup.
- `scripts/ai_sandbox.py` requires explicit model-download/inference opt-in and uses only its tiny fixture model, key and container; verify teardown. Synthetic HTTP responses establish contracts only. Actual inference needs a real runtime.
- Host diagnostics must not retain private Lerd output. Real-host integrations require explicit opt-in and a backup plan. VM, desktop, systemd and GPU tests are separate gates; container success cannot certify them.
- Add regression tests and synchronized docs for fixes. Keep meaningful existing tests, review unused-file removals against references, and record tested versus skipped/unverified status in the compatibility matrix.

## Local refactoring and cleanup

- The current checkout is authoritative. Reference archives are optional recovery/comparison sources; never replace newer local changes with old contents.
- Every modified feature needs unified implementation, operation-specific prerequisites, input validation, error/recovery handling, regression tests and synchronized usage docs. Do not introduce new distribution-specific installers or duplicate legacy implementations.
- Migrate useful legacy functions before removal; retain a script only for a named, still-unique compatibility requirement recorded in `docs/legacy-migration.md`. Delete replaced scripts and update callers/tests. Never relocate old implementations as a migration shortcut.
- The old openSUSE provisioning hierarchy is removed. Do not reintroduce hardcoded repository injection, eval, plaintext Git credential storage, security-policy downgrades, remote shell plugin bootstraps or automatic login-shell changes.
- `lib/developer.py` owns user Git identity and shell integration. Require explicit identity/shell choices, use private backups and reject restoration over subsequent edits. Never read/print private Git configuration in status or alter SSH credentials as a side effect.
- AI service manifests are allowlisted data, not executable hooks. Require reviewed existing executables, local model paths, loopback binding and private native keys. vLLM keys travel through the runtime environment, not argv. Preserve keys/configuration/models on service uninstall. Refuse unrelated or edited units; stop/uninstall must still work after model/key removal.
- `lib/checklist.py` separates read-only observed setup checks from manual acknowledgements. Approved `automate --select configuration,projects` reuses the maintained configuration/project helpers, validates all selections before mutation, skips observed-ready steps and never installs packages or changes desktop/services. Removed duplicate task IDs have bounded read-only compatibility for saved progress, never active prompts. Read/list never creates state, and cancellation saves no partial manual answers. `lib/ssh_ops.py` uses explicit identities, native passphrase prompts and existing agents; never implicitly start an agent, overwrite keys or accept host fingerprints. Separate SSH configuration and legacy Git-backup restore receipts preserve existing state.
- `lib/ssh_agent.py` controls only the exact owned user agent unit and private runtime socket. Refuse loaded/foreign/edited units, pre-existing runtime directories, unsafe sockets and later runtime user files before stopping. Configure never starts/enables or loads keys; lifecycle/key loading needs separate approval. Preserve existing agents/environment and keep keys outside volatile runtime directories. Native process fixtures/static units do not certify a real host user session or autostart.
- Git transport changes are exact, explicit GitHub rules edited with Git's parser and private backups; refuse conflicting exact-prefix rules and preserve other providers. `lib/shell_migration.py` replaces only reviewed exact paired legacy blocks; no fuzzy line deletion, startup execution or automatic login-shell/plugin changes. Import only selected bounded backups, syntax-check without startup files, and recheck current bytes after restore approval.
- `ai/legacy.py` parses supported CPU llama.cpp and reviewed vLLM settings as bounded data. Import requires a stopped/disabled original unit and absent destination, preserves model aliases/assets/originals and grants no deletion ownership. vLLM environment handling is a strict data allowlist, never sourcing; compare a separately imported private key, reject unknown settings and require explicit review before omitting a legacy allocator preload. Native vLLM installation and Playground/host support remain separate gates.
- `ai/snapshots.py` treats external Hub caches as read-only. Inventory grants no ownership. Copy only independently checksummed, size-verified assets into a separate private store, publish an observed-copy receipt last, preserve incomplete/conflicting destinations, and remove only unchanged receipt-owned copies. Refuse escaping links, executable/pickle assets, partial shards, later files/edits and related active/unknown toolkit services. Never stop a service or delete original/shared caches as a removal side effect.
- `ai/gguf.py` owns complete GGUF bundles and bounded old selection/marker readers. Require every explicit HTTPS artifact URL, independent SHA-256 and exact size, one complete shard family, aggregate RAM/disk preflight and no network/writes in dry-run. Keep verified retry caches separate from published copies. Old markers grant no ownership; preserve originals and configure new selections only after explicit approval without starting/stopping services. Artifact ownership receipts must follow successful exclusive activation, never precede it.
- Hub discovery uses pinned revisions for file metadata and reports publisher checksums as metadata requiring independent verification. Reject incomplete GGUF shard series; do not turn activity ranks or hosted inference availability into quality/local support claims.
- Validate AI arguments before command-specific dependency installation. Ollama installer preflight includes curl, tar, zstd, CA certificates and its required native utilities; it must not bootstrap a compiler or install unused tools for an already installed binary. Starting/status-checking a service must never bootstrap a compiler. Retry only a bounded, recognized native package-manager lock failure; do not repeat arbitrary failing installers or hide partial errors.
- CPU source builds explicitly require Make as well as Git/CMake/C++, disable unreviewed UI downloads/external subprocess tools, and use only a bounded requested job count. Verify source builds in disposable containers.
- Interactive cancellation returns 130. No mutation may occur merely because a menu or wizard was opened. Read-only Jan API integration does not certify its GUI or model runtime.
