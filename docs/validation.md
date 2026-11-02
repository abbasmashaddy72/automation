# Validation matrix and release gates

## Full system testing workflow

Use `scripts/container_workflows.py --allow-install --with-system-tests --with-lint --output=PRIVATE_DIRECTORY` to exercise native packages and run the full regression suite as an unprivileged fixture user. Fish/Zsh are installed only when their exact packages are available from enabled native repositories; unavailable shells are explicitly reported. Use `--system-tests-only` for focused regression reruns after fixture fixes, and `--jobs=1|2|3` to bound concurrent distro workloads (default two). The fixture switches numeric UID directly; it never changes deliberately expired image accounts or opens login sessions. Mocked systemd contracts explicitly simulate executable availability; an absent real manager remains unsupported. The shell regressions execute generated Bash/Fish/Zsh configuration twice, verify PATH deduplication and preserve argument boundaries for project-local tools. No interactive host shell is changed. A workflow passes only after observed container removal; an unknown engine response is a failure.

Actual AI CPU tests are separately authorized:

```bash
python3 scripts/ai_sandbox.py --backend=llamacpp --with-gguf-shards --yes --allow-download --allow-pull --output=PRIVATE_DIRECTORY
python3 scripts/ai_sandbox.py --backend=ollama --yes --allow-download --allow-pull --output=PRIVATE_DIRECTORY
python3 scripts/ai_sandbox.py --backend=vllm --yes --allow-download --allow-pull --output=PRIVATE_DIRECTORY
```

The native installer can also be exercised with `container_workflows.py --allow-install --containers=debian --with-ollama-install --output=PRIVATE_DIRECTORY`. Its operation-specific `--with-ollama` prerequisite profile supplies curl, tar, **zstd**, CA certificates and installer utilities from enabled native repositories. The official [Linux installer](https://ollama.com/install.sh) was inspected locally to confirm its zstd requirement; the [openSUSE zstd documentation](https://doc.opensuse.org/documentation/tumbleweed/zstd/) was consulted without adding package sources. Existing installations skip unused installer prerequisites; status and dry runs remain read-only.

Ollama's sandbox uses the [official CPU image](https://docs.ollama.com/docker), imports only an independently checksummed tiny [GGUF fixture](https://docs.ollama.com/import), then verifies discovery, [real generation](https://docs.ollama.com/api/generate), context and removal of its own imported model. The source GGUF remains unchanged. No host installer, service, model cache or API-key enforcement is claimed. Image pulls have a bounded 30-minute budget for large CPU runtime images; package-only workflows retain their separate shorter deadline, and source-build/native-installer workflows allow their bounded compiler/download budgets. Every image/model pull needs explicit opt-in. Timeouts/interruption produce failed receipts; unknown teardown never counts as removal.

When another workload locks the shared Podman engine, preserve that workload and use a private `CONTAINERS_STORAGE_CONF` file with a separate graphroot/runroot. [Podman's storage configuration](https://github.com/containers/storage/blob/main/docs/containers-storage.conf.5.md) supports per-process isolation. Example values below must be replaced with private directories owned by the test operator:

```toml
[storage]
driver = "overlay"
graphroot = "/absolute/private/test-store"
runroot = "/absolute/private/test-runroot"
```

Pass `CONTAINERS_STORAGE_CONF=/absolute/private/storage.conf` only to the test commands. Never replace the user's global configuration or reset/prune their existing engine. A shared read-only image store can still contend on metadata locks; a separate image store is needed when that happens. Run heavy image pulls and backend tests sequentially. Verify all fixture containers, networks and volumes are removed. This isolation does not certify or repair an independently locked host engine.

## Current verification — 2026-11-03

The self-contained Laravel toolkit has its own [test procedures and results](../laravel/docs/verification.md). Its tests, helpers, templates, manifests and private `.env` do not depend on this repository. Optional root unittest/CLI bridges only delegate.

Receipts are under the existing private validation state directory, in `system-finalization-20261103/isolated/`. `stage-results.json` links native package stages on Arch, Debian 13, Ubuntu 24.04, Fedora 42, Rocky 9, openSUSE Tumbleweed and Alpine 3.22 to their corrected unprivileged regression reruns. Exact installation, repeat installation, unavailable exit 5, prerequisite bootstrap and catalogue planning passed on all seven. These are scoped package stages plus regression reruns, not one fresh combined run: the original failing `systems/workflows.json` and logs remain preserved. Read-only probes independently passed all seven distributions in `readonly/validation.json`.

`final-lint-markers/workflows.json` records native ShellCheck/shfmt success in disposable Debian. Host tools remain absent. `source-build-budget-fix/workflows.json` records the completed llama.cpp CPU source build and binary version check; the earlier outer-harness timeout is preserved in `source-build/`. `ollama-installer-fix/workflows.json` records the actual official native installer, automatically supplied prerequisites and a repeat-install skip. Unselected checks in older receipts are not failed tests.

Actual model execution passed independently in `llamacpp/ai-sandbox.json` (including real GGUF shards, authentication, key rotation/revocation and ownership-safe removal), `ollama-context-fix/ai-sandbox.json` (import, implicit-`:latest` reuse, generation, context and removal), and `vllm-warmup-fix/ai-sandbox.json` (checksummed safetensors, shared invocation builder, protected API and CPU generation). The vLLM fixture allows a bounded 120 seconds for first-generation CPU warmup; the original 35-second timeout remains in `vllm/`. Ollama's API is not certified as key-protected. `webui/webui-sandbox.json` records protected login, interrupted recovery and account/session persistence on the approved pinned image. Each successful fixture verified its own teardown and preservation of source models.

`laravel/laravel-sandbox.json` records the clean standalone Ubuntu run, exporting only `laravel/` with no parent files or source overlays. Real Nginx, PHP-FPM, PostgreSQL, Composer, npm and Laravel exercised provisioning/repeat, deployment, reviewed migrations, health checks, rollback and persistent uploads. The systemd manager is simulated; public TLS, SSH/firewall and real systemd remain separate gates.

| System | Actual status | Verified scope and remaining boundary |
| --- | --- | --- |
| OS/prerequisites/packages | Implemented; native tests pass | Seven distribution families above; immutable/WSL stay planning targets; derivatives classified, not individually certified |
| Git/SSH | Implemented; disposable tests pass | Native Git/SSH probes, explicit identities and private backups; real remote credentials/host agent session unverified |
| Bash/Fish/Zsh | Implemented; native tests pass where available | Generated blocks executed twice, PATH deduplication and argument preservation; Rocky Fish unavailable in enabled repositories |
| Lerd/Project Sites | Implemented; contract tests pass | Runtime suppression, directory/link assistance and public CLI adapters; real Lerd DNS, services and desktop lifecycle unverified |
| udev | Reviewed exports implemented; contract tests pass | Automatic host rule activation retired by owner; device access/reload unverified |
| Ollama | Implemented; native installer and CPU runtime tests pass | Installer/repeat, compatible model import/reuse/generation/context/removal; no API-key enforcement claim |
| llama.cpp | Implemented; CPU source build and runtime tests pass | Actual inference, sharded GGUF, API keys, context and safe owned removal; GPU unverified |
| vLLM | Maintained runtime integration; CPU test passes | Actual safetensors inference and valid/invalid/absent authentication; native installer retired, host/GPU unverified |
| AI models/resources/API keys | Implemented; native and contract tests pass | Compatible format-specific stores, preservation, automatic planning/ports and protected llama.cpp/vLLM endpoints; no format interchangeability claim |
| Open WebUI | Implemented; pinned app test passes | Authentication, recovery and persistence; browser UX/provider connectivity remain separate |
| Desktop/taskbar | Implemented; contract tests pass | GNOME/KDE/Cinnamon/XFCE adapters; actual graphical sessions unverified |
| Configuration/checklist | Implemented; regression tests pass | One root runtime config; independently portable Laravel config is deliberate; read-only commands preserve state |
| Update/backup/recovery | Implemented; disposable regression tests pass | Checksum archives, conflicts, atomic replacement, interruption and rollback; no deliverable archive generated |
| Laravel provisioning | Portable; Ubuntu native and contract tests pass | Local provisioning native; external HTTPS/checksum/redirect/approval failures use fixtures, not an arbitrary public provisioner |
| Laravel deployment/rollback | Portable; Ubuntu native and contract tests pass | Real application, atomic releases, shared data and rollback; real systemd/SSH/firewall/public ACME unverified |

All subsequent integration runs used a separately configured rootless Podman engine with private storage. The owner's Insure360 client and engine were preserved. An earlier shared-engine attempt could not verify cleanup while that engine was locked; its interrupted receipts remain in `system-finalization-20261103/`. Do not interpret the private-engine cleanup as verification of the unrelated shared engine, and do not reset/prune it to finish a test.

Final host verification discovered 466 tests: 465 passed and the native-PHP probe skipped the host Lerd wrapper; that probe passed with native PHP in the standalone Ubuntu fixture. Bash/Python syntax, setup check, minimal dry-run and llama.cpp check/dry-run passed. Offline validation reports three passing checks, zero failures and two absent host-tool skips (ShellCheck/shfmt); native disposable Debian ran both tools, with existing shfmt style differences remaining advisory. The standalone Laravel suite discovered 31 tests (30 pass, the same host-PHP skip). `final-offline.json` preserves the final root result. `teardown.json` confirms no containers, volumes or fixture networks remain in the private engine; downloaded images stay cached.

## Portable checklist follow-up

The checklist now observes configuration completeness/private permissions and Project Sites using the maintained parsers/layout planner. Approved `checklist automate --select configuration,projects` invokes the existing helpers only for pending steps. These actions use Python/Bash and filesystem operations across supported distributions; no desktop adapter, package transaction, service manager or AI runtime is required. Git identity/package-install entries are removed from active manual prompts while bounded old progress is preserved. See [usage and safety](unified-setup.md#setup-checks-and-manual-checklist).

The final host suite discovers 479 tests: 478 pass and the existing native-PHP probe skips the host Lerd wrapper. Twelve new checklist cases cover refusal, dry-run, complete-selection preflight, exact selection, preservation, private modes, repeat runs, interrupted resumption, retired progress, manual prompts, unsafe paths/data and CLI routing. The container harness also rejects a success exit without an observed checklist smoke marker. Host ShellCheck/shfmt remain absent; disposable Debian runs both, with pre-existing shfmt style differences advisory. This verifies portable setup actions, not automatic personal desktop preferences, account logins or GPU/service readiness.

Native checklist CLI smoke passed on all seven x86_64 targets: dry-run created nothing, both selected actions reached observed-ready status, a repeat run succeeded, and an existing project file survived. Every fixture was removed. Receipts/logs are in the existing validation state directories `checklist-automation-20261103/` (Arch/Debian full package and regression workflows), `checklist-cross-distro-20261103/` (five focused native regression workflows) and `checklist-lint-20261103/` (latest native lint). Tests used the private Podman storage configuration; the unrelated Insure360 engine was preserved.

| Target | Checklist CLI | Regression snapshot: discovered / skipped | Environment skips |
| --- | --- | --- | --- |
| Arch | Pass | 477 / 1 | Native PHP |
| Debian 13 | Pass | 477 / 2 | Native PHP, systemd-analyze |
| Ubuntu 24.04 | Pass | 478 / 2 | Native PHP, systemd-analyze |
| Fedora 42 | Pass | 478 / 3 | OpenSSL, native PHP, systemd-analyze |
| Rocky 9 | Pass | 478 / 3 | Native PHP, Fish unavailable in enabled repos, systemd-analyze |
| openSUSE Tumbleweed | Pass | 478 / 2 | Native PHP, systemd-analyze |
| Alpine 3.22 | Pass | 478 / 3 | OpenSSL, native PHP, systemd-analyze |

These snapshots precede the final interruption/harness assertions as their counts indicate; the final host suite includes all 479. All seven exercised the implemented checklist actions; skipped unrelated capabilities are not passes. Distribution derivatives, other architectures and real graphical sessions are not individually certified by these runs.

## Recorded installer-removal verification (earlier scoped run)

The local removal run verified the following scopes. Results live under the
normal toolkit validation state directory; skips are not passes.

| Gate | Result | Coverage / limit |
|---|---|---|
| Unit regressions | Passed: 399 tests | Includes removed-source guards, maintained CPU configuration, Lerd suppression, PHP export retirement and WebUI recovery |
| Required CLI and syntax checks | Passed | Doctor, minimal dry-run, llama.cpp check/dry-run and 23 Bash scripts |
| Actual Open WebUI slim image | Passed; teardown verified | Protected endpoint credentials, interrupted recovery and account/session/private-key persistence; `webui-migration/webui-sandbox.json` |
| Ubuntu 24.04 package workflow | Passed; container removed | Actual disposable package install/repeat/unavailable exit, catalogue plan, Git/SSH/private agent and checklist; `legacy-removal-ubuntu/workflows.json` |
| Arch, Debian 13, Fedora 42, Rocky 9, openSUSE Tumbleweed, Alpine 3.22 package workflows | Skipped | Images absent in the current cache; additional image pulls not authorized in the recorded attempt; `legacy-removal-packages/workflows.json` |
| Host ShellCheck / shfmt | Skipped | Tools not installed; no contributor-host installation performed |
| Real desktop, user-manager/autostart, device access and GPU gates | Unverified | No host mutation or certification inferred from containers |

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

```bash
# Only if an Ollama server and the model are already running:
bash setup.sh ai ollama smoke --model=qwen2.5-coder:3b --port=11434

# Run full host report with explicit permission for a small inference request:
python3 scripts/validate.py --mode host --allow-inference \
    --inference-backend ollama --inference-model qwen2.5-coder:3b
```

The probe makes a bounded localhost API call (`POST /api/generate` for Ollama,
`POST /completion` for llama.cpp or `POST /v1/chat/completions` for vLLM).
It disables proxies and redirects; checks that the response includes nonempty
generated text; **does not** download models, install drivers, or change
server settings. Synthetic loopback API tests in the offline suite are not
proof of real model inference or CUDA/ROCm/Vulkan acceleration.

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
