# Validation matrix and release gates

## Full system testing workflow

Source checks skip generated dependency and build directories, caches, reports, backups, and symlinks. The Python syntax result reports the number of source files it actually checked.

Use `scripts/container_workflows.py --allow-install --with-system-tests --with-lint --output=PRIVATE_DIRECTORY` to exercise native packages and run the full regression suite as an unprivileged fixture user. Fish/Zsh are installed only when their exact packages are available from enabled native repositories; unavailable shells are explicitly reported. Use `--system-tests-only` for focused regression reruns after fixture fixes, and `--jobs=1|2|3` to bound concurrent distro workloads (default two). The disposable Arch layer upgrades with its repository refresh to avoid a partial upgrade. The disposable Tumbleweed test installs GNU awk before Git and Fish so Git retains its awk dependency. Full regressions install native rsync so Smart Backup copy tests run alongside ZIP tests. If a minimal fixture lacks `find`, the harness installs the exact native `findutils` package before running the source-validator regressions. [openSUSE findutils package](https://build.opensuse.org/package/show/Base:System/findutils) The fixture switches numeric UID directly; it never changes deliberately expired image accounts or opens login sessions. Mocked systemd contracts explicitly simulate executable availability; an absent real manager remains unsupported. The shell regressions execute generated Bash/Fish/Zsh configuration twice, verify PATH deduplication and preserve argument boundaries for project-local tools. No interactive host shell is changed. A workflow passes only after observed container removal; an unknown engine response is a failure.

Live inference verification is separate from distro probes. Use
`bash setup.sh ai server plan` for a read-only preview and
`bash setup.sh ai server benchmark` only on a configured target with consent.

When another workload locks the shared Podman engine, preserve that workload and use a private `CONTAINERS_STORAGE_CONF` file with a separate graphroot/runroot. [Podman's storage configuration](https://github.com/containers/storage/blob/main/docs/containers-storage.conf.5.md) supports per-process isolation. Example values below must be replaced with private directories owned by the test operator:

```toml
[storage]
driver = "overlay"
graphroot = "/absolute/private/test-store"
runroot = "/absolute/private/test-runroot"
```

Pass `CONTAINERS_STORAGE_CONF=/absolute/private/storage.conf` only to the test commands. Never replace the user's global configuration or reset/prune their existing engine. A shared read-only image store can still contend on metadata locks; a separate image store is needed when that happens. Run heavy image pulls and backend tests sequentially. Verify all fixture containers, networks and volumes are removed. This isolation does not certify or repair an independently locked host engine.

## 2026-11-17 distro and application verification

All twelve images passed the read-only probe and the write-enabled native package and checklist workflows in disposable rootless Podman. The 517-test unprivileged suite ran on each image, including native rsync copies and ZIP backups.

| Podman image        | Regression result     |
| ------------------- | --------------------- |
| Arch Linux          | 516 passed, 1 skipped |
| CachyOS             | 516 passed, 1 skipped |
| Manjaro             | 516 passed, 1 skipped |
| Debian 13           | 515 passed, 2 skipped |
| Ubuntu 24.04        | 515 passed, 2 skipped |
| Fedora 42           | 515 passed, 2 skipped |
| Rocky Linux 9       | 514 passed, 3 skipped |
| RHEL UBI 9          | 515 passed, 2 skipped |
| AlmaLinux 9         | 515 passed, 2 skipped |
| openSUSE Tumbleweed | 515 passed, 2 skipped |
| openSUSE Leap 16.0  | 515 passed, 2 skipped |
| Alpine 3.22         | 514 passed, 3 skipped |

Tool-dependent skips include native PHP, systemd-analyze and Fish on Rocky's enabled repositories. Debian also passed ShellCheck and shfmt. Leap 16 passed after its bootstrap switched to the unversioned Python package. Linux Mint and EndeavourOS passed distro-ID and package-adapter fixtures. Native Mint and EndeavourOS runs remain separate coverage. RHEL UBI tests exercise its public repositories.

The default matrix selects Arch, Debian, Ubuntu, Fedora, Rocky Linux, openSUSE Tumbleweed and Alpine. Run the additional images explicitly with the isolated Podman storage described above.

```bash
bash setup.sh validate --mode containers --engine podman --require-containers --allow-pull \
    --containers cachyos,manjaro,rhel-ubi,almalinux,leap --output /tmp/toolkit-derivatives/read-only
python3 scripts/container_workflows.py --allow-install --allow-pull --with-system-tests \
    --containers cachyos,manjaro,rhel-ubi,almalinux,leap --output /tmp/toolkit-derivatives/write
```

- **Advanced** passed Chromium checks for staging, cancellation, applying settings and Project Sites together, saving settings independently, restoring by backup ID, and mobile navigation.
- **Laravel** passed with live Nginx and PHP-FPM in Ubuntu. HTTP checks returned 200 throughout candidate rejection, deployment and rollback. The sandbox verified teardown. [Laravel verification scope](../laravel/docs/verification.md)
- **Smart Backup** passed Chromium checks at 390 px and 1366 px, including selection inheritance and creating a backup.
- **ChatGPT Lite** passed lint, TypeScript checking, a production build and browser tests with a simulated model API. **Open WebUI** passed sign-in enforcement, protected endpoint checks, interrupted recovery and session persistence in a separate disposable sandbox.

Receipts are in the validation state directory under `advanced-deploy-20261117` and `backup-docs-final-20261117`. GPU acceleration, physical external drives and live desktop settings need separate host tests.

## Dashboard verification

The Chromium smoke test opens System profile import and export in a temporary checkout. It checks unsupported-schema recovery, editing during review, the saved selection after reload, and the exported Zed preference. The offline suite exercises private backups, stale reviews, migration, and rollback after a write failure.

The 2026-11-18 reliability audit added checks for patch syntax before writing, patch recovery after interruption and conflicting edits, unsafe gateway-key paths, failed gateway restart recovery, incomplete ZIP inventories, and truncated Laravel health responses. Gateway failure tests use command fixtures. All 12 read-only Podman probes and the Debian writable package, unprivileged regression, and shell-tool checks passed. The standalone Ubuntu 24.04 Laravel fixture passed all 12 checks using native Nginx and PHP-FPM with a simulated systemd manager. Receipts are under `project-audit-20261118` in the validation state directory.

Run `python3 scripts/dashboard_browser_test.py` as a regular user with Chrome or Chromium and a matching ChromeDriver. CI runs it for pull requests and dashboard changes. The test copies the current checkout into a temporary directory and uses a fresh browser profile, user configuration paths, and OS-assigned loopback ports. It verifies the real Project Sites preview, package-status reuse and refresh, concurrent edits in two tabs, and recovery of queued edits after reload. Simulated AI responses cover review gating and model-folder refresh after successful installation. The fixture applies profile and configuration changes only in its disposable checkout and user directories.

The browser regression checks malformed and older profiles, formatting and editing, real toolkit and Zed restoration, checklist persistence after reopening the drawer, and the contents of an actual Smart Backup ZIP. Writable native package fixtures check that a repeated install has no installable packages and exercise an explicit Git reinstall.

On 2026-11-18, Chromium checked 24 dashboard routes at 320, 390, 768, and 1366 px for horizontal overflow. It verified backup ID and preview-button alignment, stacked mobile controls, shared tab spacing, and AI target and model tab navigation. It also ran both storage previews and verified that package IDs stayed on separate lines after preview, Back, and reload. Separate disposable browser runs exercised Advanced settings save and restore, combined settings and Project Sites, and Smart Backup copy and ZIP output. A fresh ChatGPT Lite build passed its browser preference and model selection checks against a test endpoint.

The same 12 Podman images passed read-only probes, native package and checklist workflows, and unprivileged regressions. ShellCheck and shfmt passed in the Debian fixture. The results and recovered teardown checks are under `dashboard-layout-20261118` in the validation state directory.

| Workflow                      | Verified scope                                                                                                                                                                                                                              | Remaining coverage                                                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| System and navigation         | Chromium showed host CachyOS hardware and AI eligibility, opened the checklist, and switched all six top-level pages at desktop and mobile widths.                                                                                          | Additional browsers and real desktop integrations.                                                         |
| Packages and terminal prompts | Chromium exercised selection, Back, preview, install, reinstall and a waiting-for-sudo event using a disposable command fixture.                                                                                                            | Live sudo, fingerprint prompts and real AUR recipe review.                                                 |
| Local AI                      | Chromium exercised the two-step installation, local GGUF scanning, port/API/context reads against a loopback fixture, and SSH failure recovery and remote scanning with an SSH fixture. Context rollback has automated regression coverage. | Managed service installation, live inference, live SSH provisioning and GPU verification on a target host. |
| Zed                           | Chromium used the real CLI against a temporary JSONC file. It tested a loopback model API fixture, cancelled a remote-endpoint warning, validated replacement, rejected an invalid backup ID and restored the original bytes.               | Real Zed GUI and authenticated or remote provider connectivity.                                            |
| Cleanup                       | Chromium exercised both previews. Native CachyOS package-cache inspection reported zero candidates; a separate temporary cache demonstrated selection of two obsolete archives.                                                             | Host cache deletion, dependency removal and log changes.                                                   |
| Smart Backup                  | Chromium verified the layout at 390 px and 1366 px and created a disposable backup through the folder tree. Native regressions verify copy/ZIP contents, exclusions, and failure recovery.                                                  | Physical external-drive detection and backup to external filesystems.                                      |

The isolated Debian 13 Podman workflow passed native package smoke, ShellCheck, shfmt, checklist automation and unprivileged regressions, and verified container teardown. Its receipt is in the validation state directory under `dashboard-redesign-debian/workflows.json`.

A subsequent CachyOS Chromium run tested the readable AI eligibility summary and raw JSON, recommended model selection, verified-download preview, and the exact Project Sites folder and optional PHP file list. The real ChatGPT Lite standalone build served its chat page on loopback. The preview was stopped and the port was released. Model download and GPU inference were separate from this browser run.

Chromium verified the CachyOS KDE and firmware fields, the green theme, browser-saved AI preferences across reload, tab-scoped operation output and the terminal authentication modal. Managed llama.cpp registration and sudo events used fixtures. A read-only host check observed the compiled binary, an absent unit and no service configuration. Real service startup and reboot persistence were outside this run.

The package grid filled its card at desktop width and kept bounded scrolling at mobile width in Chromium. The Configure → Lerd flow exercised preview, cancellation, confirmed installation, installed status, repair preview and compatibility refusal with a disposable command fixture. The host executable and compatibility were checked read-only. A live Lerd install or repair was outside this run.

Chromium exercised Terminal's per-shell options and the install, login-shell and configuration review controls using fixtures. Bash, Fish and Zsh were exercised in disposable terminal sessions, where the shortcut populated the editable buffer and execution required Enter. The AI client used a loopback HTTP fixture to test selected input, streamed output and rejected multiline suggestions. Live inference and account login-shell changes were outside this run.

Native shell fixtures verified the compact startup block, option discovery, preserved surrounding bytes and the sourced helpers. Disposable interactive sessions verified the shortcut in Bash, Fish and Zsh from a checkout path containing spaces, quotes and a backslash. Existing Fish and Zsh startup files were syntax-checked in preview only.

Native Fish and Zsh fixtures ran the cleanup aliases with stubbed removal and installation commands and verified that personal aliases take precedence. Chromium exercised the option preview and dashboard URLs across reload, direct links, Back and Forward.

Chromium verified individual Terminal command choices, exact review, mobile layout, restored managed settings and an unselected fresh configuration with Lerd present. Native Bash, Fish and Zsh fixtures verified the empty selection, a standalone project wrapper and a disabled AI operation. Live shell files and services were outside this run.

## Unified merge verification

The Downloads automation tree supplied the ChatGPT Lite UI, its locked
dependencies, Zed preferences and the bounded GGUF context reader. The active
checkout supplied the distro adapters, package/checklist workflows, the
dedicated llama.cpp server, Open WebUI lifecycle and Laravel. The separate
Downloads `automations/` directory was not present. No second installer
or duplicate package/provider implementation was imported.

Read-only probes passed all seven cached targets (Arch, Debian, Ubuntu,
Fedora, Rocky, Tumbleweed and Alpine), using the private Podman engine.
The focused Debian workflow ran unprivileged regressions, checklist CLI smoke
and lint. The pinned Open WebUI fixture verified authentication, interrupted
recovery, account/session persistence and teardown; provider networking was
disabled in that fixture. Reports are under the private validation directory
in `unified-merge-containers/`, `unified-merge-debian/` and
`unified-merge-webui/`.

ChatGPT Lite passed its production build, debug startup, streamed chat and
browser rendering at desktop and mobile widths using a disposable loopback
model API fixture. The production-only npm audit reported zero advisories;
the separate developer lint toolchain has eight moderate advisory entries.
A real
Ubuntu install, live model inference, GPU acceleration and WebUI-to-llama.cpp
networking are distinct checks and were not run for this merge.

## Historical verification — 2026-11-03

The statuses below describe the toolkit on that date. The current toolkit manages llama.cpp only. See the [migration guide](legacy-migration.md) for retired installers and preserved user data.

The self-contained Laravel toolkit has its own [test procedures and results](../laravel/docs/verification.md). Its tests, helpers, templates, manifests and private `.env` do not depend on this repository. Optional root unittest/CLI bridges only delegate.

Receipts are under the existing private validation state directory, in `system-finalization-20261103/isolated/`. `stage-results.json` links native package stages on Arch, Debian 13, Ubuntu 24.04, Fedora 42, Rocky 9, openSUSE Tumbleweed and Alpine 3.22 to their corrected unprivileged regression reruns. Exact installation, repeat installation, unavailable exit 5, prerequisite bootstrap and catalogue planning passed on all seven. These are scoped package stages plus regression reruns, not one fresh combined run: the original failing `systems/workflows.json` and logs remain preserved. Read-only probes independently passed all seven distributions in `readonly/validation.json`.

`final-lint-markers/workflows.json` records native ShellCheck/shfmt success in disposable Debian. Host tools remain absent. `source-build-budget-fix/workflows.json` records the completed llama.cpp CPU source build and binary version check; the earlier outer-harness timeout is preserved in `source-build/`. `ollama-installer-fix/workflows.json` records the actual official native installer, automatically supplied prerequisites and a repeat-install skip. Unselected checks in older receipts are not failed tests.

Actual model execution passed independently in `llamacpp/ai-sandbox.json` (including real GGUF shards, authentication, key rotation/revocation and ownership-safe removal), `ollama-context-fix/ai-sandbox.json` (import, implicit-`:latest` reuse, generation, context and removal), and `vllm-warmup-fix/ai-sandbox.json` (checksummed safetensors, shared invocation builder, protected API and CPU generation). The vLLM fixture allowed up to 120 seconds for first-generation CPU warmup. `webui/webui-sandbox.json` records protected login, interrupted recovery and account/session persistence on the approved pinned image. Each successful fixture verified its own teardown and preservation of source models.

`laravel/laravel-sandbox.json` records the clean standalone Ubuntu run, exporting only `laravel/` with no parent files or source overlays. Real Nginx, PHP-FPM, PostgreSQL, Composer, npm and Laravel exercised provisioning/repeat, deployment, reviewed migrations, health checks, rollback and persistent uploads. The systemd manager is simulated; public TLS, SSH/firewall and real systemd remain separate gates.

| System                       | Actual status                                            | Verified scope and remaining boundary                                                                                                                                            |
| ---------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OS/prerequisites/packages    | Implemented; native tests pass                           | Seven distribution families above; immutable/WSL stay planning targets; derivatives classified, not individually certified                                                       |
| Git/SSH                      | Implemented; disposable tests pass                       | Native Git/SSH probes, explicit identities and private backups; real remote credentials/host agent session unverified                                                            |
| Bash/Fish/Zsh                | Implemented; native tests pass where available           | Generated blocks executed twice, PATH deduplication and argument preservation; Rocky Fish unavailable in enabled repositories                                                    |
| Lerd/Project Sites           | Implemented; contract tests pass                         | Runtime suppression, directory/link assistance and public CLI adapters; real Lerd DNS, services and desktop lifecycle unverified                                                 |
| udev                         | Reviewed exports implemented; contract tests pass        | Automatic host rule activation retired by owner; device access/reload unverified                                                                                                 |
| Ollama                       | Implemented; native installer and CPU runtime tests pass | Installer/repeat, compatible model import/reuse/generation/context/removal; no API-key enforcement claim                                                                         |
| llama.cpp                    | Implemented; CPU source build and runtime tests pass     | Actual inference, sharded GGUF, API keys, context and safe owned removal; GPU unverified                                                                                         |
| vLLM                         | Maintained runtime integration; CPU test passes          | Actual safetensors inference and valid/invalid/absent authentication; native installer retired, host/GPU unverified                                                              |
| AI models/resources/API keys | Implemented; native and contract tests pass              | Compatible format-specific stores, preservation, automatic planning/ports and protected llama.cpp/vLLM endpoints; no format interchangeability claim                             |
| Open WebUI                   | Dashboard lifecycle and pinned Podman app tested         | Chromium used simulated install/start/stop responses. Real private Podman verified readiness, sign-in, recovery and persistence. Live llama.cpp connectivity remains unverified. |
| ChatGPT Lite background      | Dashboard lifecycle tested with a simulated user manager | Chromium reached the real Node build in preview and background fixtures. Live systemd user-service lifecycle remains unverified.                                                 |
| Desktop/taskbar              | Implemented; contract tests pass                         | GNOME/KDE/Cinnamon/XFCE adapters; actual graphical sessions unverified                                                                                                           |
| Configuration/checklist      | Implemented; regression tests pass                       | One root runtime config; independently portable Laravel config is deliberate; read-only commands preserve state                                                                  |
| Update/backup/recovery       | Implemented; disposable regression tests pass            | Checksum archives, conflicts, atomic replacement, interruption and rollback; no deliverable archive generated                                                                    |
| Laravel provisioning         | Portable; Ubuntu native and contract tests pass          | Local provisioning native; external HTTPS/checksum/redirect/approval failures use fixtures, not an arbitrary public provisioner                                                  |
| Laravel deployment/rollback  | Portable; Ubuntu native and contract tests pass          | Real application, atomic releases, shared data and rollback; real systemd/SSH/firewall/public ACME unverified                                                                    |

All subsequent integration runs used a separately configured rootless Podman engine with private storage. The owner's Insure360 client and engine were preserved. An earlier shared-engine attempt could not verify cleanup while that engine was locked; its interrupted receipts remain in `system-finalization-20261103/`. Do not interpret the private-engine cleanup as verification of the unrelated shared engine, and do not reset/prune it to finish a test.

Final host verification discovered 466 tests: 465 passed and the native-PHP probe skipped the host Lerd wrapper; that probe passed with native PHP in the standalone Ubuntu fixture. Bash/Python syntax, setup check, minimal dry-run and llama.cpp check/dry-run passed. Offline validation reports three passing checks, zero failures and two absent host-tool skips (ShellCheck/shfmt); native disposable Debian ran both tools, with existing shfmt style differences remaining advisory. The standalone Laravel suite discovered 31 tests (30 pass, the same host-PHP skip). `final-offline.json` preserves the final root result. `teardown.json` confirms no containers, volumes or fixture networks remain in the private engine; downloaded images stay cached.

## Portable checklist follow-up

The checklist now observes configuration completeness/private permissions and Project Sites using the maintained parsers/layout planner. Approved `checklist automate --select configuration,projects` invokes the existing helpers only for pending steps. These actions use Python/Bash and filesystem operations across supported distributions; no desktop adapter, package transaction, service manager or AI runtime is required. Git identity/package-install entries are removed from active manual prompts while bounded old progress is preserved. See [usage and safety](unified-setup.md#setup-checks-and-manual-checklist).

The final host suite discovers 479 tests: 478 pass and the existing native-PHP probe skips the host Lerd wrapper. Twelve new checklist cases cover refusal, dry-run, complete-selection preflight, exact selection, preservation, private modes, repeat runs, interrupted resumption, retired progress, manual prompts, unsafe paths/data and CLI routing. The container harness also rejects a success exit without an observed checklist smoke marker. Host ShellCheck/shfmt remain absent; disposable Debian runs both, with pre-existing shfmt style differences advisory. This verifies portable setup actions, not automatic personal desktop preferences, account logins or GPU/service readiness.

Native checklist CLI smoke passed on all seven x86_64 targets: dry-run created nothing, both selected actions reached observed-ready status, a repeat run succeeded, and an existing project file survived. Every fixture was removed. Receipts/logs are in the existing validation state directories `checklist-automation-20261103/` (Arch/Debian full package and regression workflows), `checklist-cross-distro-20261103/` (five focused native regression workflows) and `checklist-lint-20261103/` (latest native lint). Tests used the private Podman storage configuration; the unrelated Insure360 engine was preserved.

| Target              | Checklist CLI | Regression snapshot: discovered / skipped | Environment skips                                              |
| ------------------- | ------------- | ----------------------------------------- | -------------------------------------------------------------- |
| Arch                | Pass          | 477 / 1                                   | Native PHP                                                     |
| Debian 13           | Pass          | 477 / 2                                   | Native PHP, systemd-analyze                                    |
| Ubuntu 24.04        | Pass          | 478 / 2                                   | Native PHP, systemd-analyze                                    |
| Fedora 42           | Pass          | 478 / 3                                   | OpenSSL, native PHP, systemd-analyze                           |
| Rocky 9             | Pass          | 478 / 3                                   | Native PHP, Fish unavailable in enabled repos, systemd-analyze |
| openSUSE Tumbleweed | Pass          | 478 / 2                                   | Native PHP, systemd-analyze                                    |
| Alpine 3.22         | Pass          | 478 / 3                                   | OpenSSL, native PHP, systemd-analyze                           |

These snapshots precede the final interruption/harness assertions as their counts indicate; the final host suite includes all 479. All seven exercised the implemented checklist actions; skipped unrelated capabilities are not passes. Distribution derivatives, other architectures and real graphical sessions are not individually certified by these runs.

## Recorded installer-removal verification (earlier scoped run)

The local removal run verified the following scopes. Results live under the
normal toolkit validation state directory; skips are not passes.

| Gate                                                                                    | Result                    | Coverage / limit                                                                                                                                       |
| --------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Unit regressions                                                                        | Passed: 399 tests         | Includes removed-source guards, maintained CPU configuration, Lerd suppression, PHP export retirement and WebUI recovery                               |
| Required CLI and syntax checks                                                          | Passed                    | Doctor, minimal dry-run, llama.cpp check/dry-run and 23 Bash scripts                                                                                   |
| Actual Open WebUI slim image                                                            | Passed; teardown verified | Protected endpoint credentials, interrupted recovery and account/session/private-key persistence; `webui-migration/webui-sandbox.json`                 |
| Ubuntu 24.04 package workflow                                                           | Passed; container removed | Actual disposable package install/repeat/unavailable exit, catalogue plan, Git/SSH/private agent and checklist; `legacy-removal-ubuntu/workflows.json` |
| Arch, Debian 13, Fedora 42, Rocky 9, openSUSE Tumbleweed, Alpine 3.22 package workflows | Skipped                   | Images absent in the current cache; additional image pulls not authorized in the recorded attempt; `legacy-removal-packages/workflows.json`            |
| Host ShellCheck / shfmt                                                                 | Skipped                   | Tools not installed; no contributor-host installation performed                                                                                        |
| Real desktop, user-manager/autostart, device access and GPU gates                       | Unverified                | No host mutation or certification inferred from containers                                                                                             |

WebUI browser UX, provider connectivity/inference and upgrades to other image
versions remain independent gates. The approved pinned WebUI image stays cached;
its fixture container, volume, network and account data were removed.

Validation provides read-only checks and explicitly authorized disposable integrations. Maintained package, Lerd, AI, update and bounded old-state import commands are tested; removed installers are not retained.

## Quick start: no changes to your operating system

```bash
bash setup.sh validate --mode offline
python3 scripts/validate.py --mode offline --strict-tools
# Results: ~/.local/state/automation-toolkit/validation/validation.{json,md}
```

The offline suite runs unit tests, Bash syntax, Python syntax, ShellCheck
(errors-only when installed) and shfmt listing when installed. Missing ShellCheck
and shfmt are **skips**, not passes, unless `--strict-tools` is set. Existing
shfmt differences are warnings unless `--strict-format` is selected. The
historical Bash scripts were not blindly reformatted.

## Distribution matrix — isolated, non-destructive

```bash
# Cached container images only; NO pulling or installation:
python3 scripts/validate.py --mode containers

# With explicit consent to pull images (stores layers in Docker/Podman cache):
python3 scripts/validate.py --mode containers --allow-pull --require-containers

# One distribution with a specific container engine:
python3 scripts/validate.py --mode containers --engine podman \
    --containers opensuse --allow-pull --require-containers
```

Supported probe targets: Arch, Ubuntu, Debian, Fedora, Rocky, openSUSE
Tumbleweed, and Alpine. The probed images are listed in `scripts/validate.py`.
Use pinned immutable image digests in your regulated CI environment; these
reference image **tags** can drift between runs.

Container probes run as UID 65534 with `--network=none`, `--read-only`,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`, and a read-only mount of
the toolkit source. They check distribution identity and existence of the native
package-manager executable. **They do not install packages, configure Lerd,
start systemd, open GUI windows, or test GPU drivers**. Containers are not a
substitute for a desktop VM. No container engine is installed automatically.

Use real disposable VMs for additional installation coverage. On each VM:

1. Snapshot VM and securely back up any test data.
2. Run `bash setup.sh doctor`, `bash setup.sh packages plan --select git,curl,lerd`.
3. Confirm Lerd compatibility: `python3 scripts/host_diagnostics.py --lerd-doctor`.
4. Verify rootless Podman, DNS, `systemctl --user`, desktop app, CLI services,
   PHP versions, and a disposable `.test` project. Record commands and outcomes.
5. With explicit consent and test-only environment, install selected packages;
   test idempotent reruns, network failures, service conflicts and repair paths.
6. Verify backups, journal, model retention and reinstall behavior. Never use
   these destructive/mutating experiments on the developer workstation.
7. Capture verified distribution version, architecture, host or VM type, Lerd
   binary version, and observed results. Do not publish secrets or certificates.

## Host diagnostics (read-only unless you choose inference)

```bash
# Read-only host details (no Lerd CLI invocation by default)
python3 scripts/host_diagnostics.py

# Explicitly run Lerd's official diagnostic
python3 scripts/host_diagnostics.py --lerd-doctor

# Run via the saved report interface
python3 scripts/validate.py --mode host --lerd-doctor
```

The host probe checks the systemd user session, rootless Podman, crun presence,
Lerd existence, and optionally `lerd doctor`. It reports basic status without
copying potentially sensitive command output into the report.

Lerd officially requires a systemd user session and rootless Podman 4.5+.
Some distros/installations may be incompatible even if package-family
classification succeeds. For actual requirements see
<https://lerd.sh/getting-started/requirements>.

## AI runtime inference (explicit opt-in, localhost only)

Run `bash setup.sh ai server benchmark` on an existing managed llama.cpp
installation. It sends real requests. Host validation only probes llama.cpp
when explicitly opted in. Synthetic responses do not prove GPU acceleration.

Managed llama.cpp storage regression coverage exercises local paths, spare
filesystem selection, duplicate UUIDs, administrator-controlled mount paths,
mount unit creation and reuse, and startup refusal when the filesystem changes.
A generated mount-unit fixture passed `systemd-analyze verify`. Read-only Podman
probes passed on Arch, Debian 13, Ubuntu 24.04, Fedora 42, Rocky 9, openSUSE
Tumbleweed and Alpine 3.22. Debian 13 also passed a disposable native AI
prerequisite install and no-op rerun. Those checks leave physical disk attachment,
reboot persistence and GPU inference as host or VM verification tasks.

## Fault-injection and regression coverage

The offline suite includes simulated native package failures, missing managers,
container/WSL/immutable host restrictions, missing or fake zero-success
post-install verification, report privacy, non-rootless Podman rejection,
remote inference rejection, redirects, malformed API responses, and compatibility
matrix tests. Patch apply and rollback must be tested in a disposable copy of
the previous release for each release candidate.

## Explicit release acceptance criteria

- No tests or syntax checks fail.
- ShellCheck and shfmt are installed and validated; `--strict-format` is a
  separate style gate pending normalization of preserved legacy scripts.
- Every claimed distribution/version is tested in a disposable VM, with package
  installation, idempotence, recovery and real service/desktop workflows.
- Lerd Desktop must be checked in a real supported systemd session with rootless
  Podman and proper DNS/HTTPS behavior.
- AI acceleration claims need real inference logs and GPU utilization checks.
- Local checksum-verified full/patch archives require neither signing keys nor
  `--allow-unsigned`, per the owner's workflow. Optional historical signed
  archives still require their trusted publisher verification.
- A skipped test is not a passing test; report skipped environments as such.

The present release implements the **validation infrastructure and offline
regressions**, but it does not claim these VM, desktop or GPU gates have passed.

The minimal Tumbleweed fixture requires an explicitly reviewed BusyBox-awk to gawk variant replacement before installing Fish. This fixture preparation uses only configured official repositories; the production adapter continues to refuse package conflicts rather than force a solver removal. See the [upstream Zypper manual](https://raw.githubusercontent.com/openSUSE/zypper/master/doc/zypper.8.txt). Rocky's native Fish package may be unavailable in enabled repositories; tests record that capability skip without adding EPEL.
