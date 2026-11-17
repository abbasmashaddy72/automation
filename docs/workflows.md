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
bash setup.sh packages export --select git,curl,php,lerd --output "$HOME/install-plan.json"
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

Developer actions include `ssh-status`, `ssh-copy`, `ssh-test --ssh-provider=github|gitlab --identity-file=PATH`, and `clone REPOSITORY --destination=NEW_PATH`. Copy requires approval and uses clipboard stdin or a controlling terminal; it never prints a private key. Host trust remains strict and tests never accept a new fingerprint. Repository cloning validates a new owned destination and authenticates through Git's existing credential/SSH workflow. `checklist check` observes dependencies, desktop, private configuration completeness and Project Sites without mutation. `checklist automate --select configuration,projects --dry-run` plans the maintained config/layout helpers; `--yes` applies missing steps and skips ready ones. Manual acknowledgements remain separate; duplicate identity/software tasks are removed from prompts while old progress is preserved. See [setup checks](unified-setup.md#setup-checks-and-manual-checklist).

Project Sites defaults to `~/Documents/Project-Sites/` and respects `AUTOMATION_PROJECT_SITES_DIR` or an explicit target. Existing content is preserved. Desktop favorites append without deleting earlier favorites; Cinnamon and XFCE support intentionally narrow single-panel/single-launcher targets and refuse ambiguous configurations. Their fixtures do not establish real desktop-session behavior.

Laravel production documentation and tests now live in the [independent Laravel folder](../laravel/README.md). Root setup is only an optional launcher.

## Zed settings

The bundled VS Code style profile combines the supplied Zed preferences with
the available source project's safe editor defaults. It leaves endpoint/model
choices and tool permissions to the local settings. Existing JSONC values
always win; lists are preserved as a whole. Changes normalize formatting to
JSON. A private receipt preserves the exact original bytes, including comments.
Use `zed plan` to review keys, `zed apply --yes` to add them, or pass an explicit
profile path. `zed backup --yes` creates a separate backup. Restore takes the
printed receipt ID and refuses later changes unless the current SHA-256 is
explicitly reviewed and passed with `--current-sha256`.

## Package restore and cleanup

Export a reviewed native plan with `packages export --output FILE` (include any
explicit `--replace REQUESTED=ACTUAL` selections). The plan records package IDs,
sources and platform; an interactive choice is recorded with its actual name
in the installed inventory. `packages restore FILE --dry-run` previews native
replay. Add `--yes` to run it after review. Replay rejects unavailable/managed,
Flatpak and AUR entries and mismatched distribution/architecture/manager.
It rechecks native availability and skips already installed exact packages.

`cleanup plan` lists the number of expired toolkit repository cache entries.
`cleanup cache --yes` deletes those entries only. Package removal, service
removal, external caches, model data and application histories are outside
generic cleanup. Use `ai llamacpp gguf-remove --dry-run --manifest FILE` to
review removal of a verified toolkit-owned model copy.
