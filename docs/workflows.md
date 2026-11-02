# Portable workflows (offline-tested, host installation unverified)

These features extend Validation. **Nothing in the workflows below installs packages, changes a repository, or removes existing Lerd databases/models.** Package installation still requires the existing explicit approval/`--yes` and exact repository checks.

## Setup profiles

```bash
# Export a portable, strictly limited configuration profile
bash setup.sh profiles export "$HOME/developer.json" --profile developer --select git,curl,podman
# Import as a private, user-scoped profile; name is derived from filename
bash setup.sh profiles import "$HOME/developer.json"
bash setup.sh profiles list
bash setup.sh profiles show developer
bash setup.sh packages plan --saved-profile developer
```

Profiles are JSON `{"schema":1,"type":"automation-profile","settings":{...}}`. Only allowlisted selection and AI settings are portable. **Credentials, private paths, keys, environment variables, downloaded models and installation history are never exported.** Imported profiles live under `${AUTOMATION_STATE_DIR:-~/.local/state/automation-toolkit}/profiles` with private permissions. `--saved-profile NAME` is a configuration baseline: local `.env`, supported environment variables and explicit CLI flags take precedence. Import does not automatically activate or install a profile. An existing profile cannot be overwritten implicitly.

## Machine-readable plans

```bash
bash setup.sh packages plan --select git,curl,php,lerd --output "$HOME/install-plan.json"
```

A plan is a point-in-time JSON description: hostname is not included, system changes are not authorized, and repository/package availability **must** be rechecked at the time of actual installation. When Lerd is compatible and selected, the original Lerd-aware overlap filtering applies to the export.

## Offline artifact preparation and verification

```bash
mkdir -p "$HOME/package-cache"
# Place distro-compatible, independently obtained native package artifacts in this directory.
bash setup.sh offline prepare "$HOME/install-plan.json" \
    --cache-dir "$HOME/package-cache" \
    --output "$HOME/offline-manifest.json" \
    --artifact git=git_2.47.0_amd64.deb
bash setup.sh offline verify "$HOME/offline-manifest.json" --cache-dir "$HOME/package-cache"
```

**Illustrative `.deb` filename** — it must actually exist in the cache. `--artifact` names are explicit and cannot contain paths. Format is restricted to `.deb`, `.rpm`, `.apk` or Arch `.pkg.tar.*`, matching the plan's distro family. Artifacts receive SHA-256 and size receipts. Uncached packages are reported as `not_cached`; verification exits **5** for incomplete manifests, missing or mismatched files. Exit **0** only means each listed local artifact is present and its hash matches, with no unfilled selections. **These manifests do not install or download packages, verify package signatures, resolve dependencies, or guarantee a bootstrappable offline system.** Use native managers and their signature verification when installing.

## Extension providers (declarative, opt-in)

```bash
bash setup.sh providers validate tests/fixtures/providers/native_tools.json
bash setup.sh providers plan tests/fixtures/providers/native_tools.json --select terminal-editor
# Only if the exact native repository package is available; explicit approval required
bash setup.sh providers install tests/fixtures/providers/native_tools.json --select terminal-editor --yes
```

Provider JSON contains only a schema version, ID and per-family native package-name mappings. No scripts, shell, hooks, repository URLs or arbitrary executable entries are permitted. All mapped package names pass the existing exact native availability checks. Plugins cannot install Lerd or AI backends via their native-only provider mappings. Provider files are read **only when explicitly supplied**; no automatic plugin directory execution.

## Project starter templates

```bash
bash setup.sh projects init python "$HOME/Documents/example-python" --dry-run
bash setup.sh projects init python "$HOME/Documents/example-python" --yes
bash setup.sh projects init node "$HOME/Documents/example-node" --yes
```

Creates dependency-free Python or Node starter files only under a **new** destination directory. Existing paths are never overwritten. It never executes `composer`, `pip`, `npm`, curl or any remote installation. Laravel and container project templates remain future possibilities; use the existing Lerd official workflow for Laravel.

## Offline local report

```bash
bash setup.sh dashboard export "$HOME/automation-report.html"
```

Creates a local, noninteractive, static HTML report from the existing private installation journal/observed inventory. No server, remote scripts, external CSS or live package changes. HTML is escaped and includes a restrictive CSP. **Treat the exported file as sensitive local inventory**; it is created mode `0600`. An existing report is not overwritten.

## Constraints / compatibility

- Python 3.9+ and Bash are runtime requirements. The consolidated release can bootstrap Python 3.9+ using its Bash-only `setup.sh prerequisites` workflow with explicit approval.
- All Portable workflows JSON is size-bounded, schema-validated and never evaluated as shell code.
- Profiles do not confer privileges; installation still follows `setup.sh packages install` approvals.
- Offline plans are metadata inventories, not a distribution-independent installer.
- Removed legacy installers are replaced by maintained adapters or owner-approved retirements; existing data, Lerd and AI installations are preserved.
- Functional cross-distro and Lerd/GPU tests on real hosts remain pending.

## Reviewed audit additions

`bash setup.sh ai install --backends=llamacpp,ollama --dry-run` plans only the explicitly selected installers. Execute with `--yes` after review; vLLM native installation and Jan GUI remain separate manual gates. `bash setup.sh ai llamacpp resources` reports bounded CPU/cgroup/RAM-aware resources and an available loopback port. `AUTOMATION_AI_THREADS`, `AUTOMATION_AI_QUOTA` and `AUTOMATION_AI_PORT` accept `auto`; explicit CLI/configuration values and existing service selections are preserved. Hardware discovery does not prove GPU acceleration. Foreground commands do not imply a service CPU quota is enforced.

Developer actions include `ssh-status`, `ssh-copy`, `ssh-test --ssh-provider=github|gitlab --identity-file=PATH`, and `clone REPOSITORY --destination=NEW_PATH`. Copy requires approval and uses clipboard stdin or a controlling terminal; it never prints a private key. Host trust remains strict and tests never accept a new fingerprint. Repository cloning validates a new owned destination and authenticates through Git's existing credential/SSH workflow. `checklist check` observes dependencies, desktop, private configuration completeness and Project Sites without mutation. `checklist automate --select configuration,projects --dry-run` plans the maintained config/layout helpers; `--yes` applies missing steps and skips ready ones. Manual acknowledgements remain separate; duplicate identity/software tasks are removed from prompts while old progress is preserved. See [setup checks](unified-setup.md#setup-checks-and-manual-checklist).

Project Sites defaults to `~/Documents/Project-Sites/` and respects `AUTOMATION_PROJECT_SITES_DIR` or an explicit target. Existing content is preserved. Desktop favorites append without deleting earlier favorites; Cinnamon and XFCE support intentionally narrow single-panel/single-launcher targets and refuse ambiguous configurations. Their fixtures do not establish real desktop-session behavior.

Laravel production documentation and tests now live in the [independent Laravel folder](../laravel/README.md). Root setup is only an optional launcher.


Ollama installation, repair and update now preflight `--with-ollama` dependencies (including zstd) only when the upstream installer will actually run. An existing installation skips unused installer tools. Installer downloads validate every hop through the official Ollama/GitHub release identity, bound the response and syntax-check the saved script; signed asset query values are never logged. External installer execution still requires explicit approval and may change system services; the native integration tests run only in disposable containers.

Ollama cache reuse treats an omitted tag as `:latest` while preserving explicit tags and `--refresh-model --yes`. Runtime context reads the exact loopback `/api/ps` route, including IPv6 support. These operations do not change existing models or services merely to inspect them. WSL/immutable prerequisite installation is rejected before repository queries when required tools are missing, avoiding DNF query state creation on a blocked operation.
