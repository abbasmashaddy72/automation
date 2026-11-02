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

```bash
bash setup.sh ai vllm model-search --query coder --rank downloads --scope hub --offset 0 --limit 20
bash setup.sh ai vllm model-files --model HuggingFaceTB/SmolLM2-135M-Instruct --revision 12fd25f77366fa6b3b4b768ec3050bf629380bac
bash setup.sh ai llamacpp model-files --model PUBLISHER/MODEL --revision EXACT_40_HEX_COMMIT --quant Q4_K_M
bash setup.sh ai vllm key-import --legacy-key-file /absolute/private/old-vllm-api.env --dry-run
bash setup.sh ai llamacpp legacy-plan --legacy-unit "$HOME/.config/systemd/user/llamacpp-local.service"
```

Model search supports downloads/likes/trending activity and pagination, not quality rankings. Warm means hosted inference availability. `model-files` reads bounded public metadata at an exact commit, reports publisher sizes/checksums and pinned HTTPS URLs, and rejects incomplete GGUF shard sets. Independently verify size/SHA-256 before explicit downloads; missing publisher SHA-256 remains missing. No dependency, model, export file or receipt is installed by discovery. See the [Hub API](https://huggingface.co/docs/hub/en/api) and [official metadata client](https://github.com/huggingface/huggingface_hub/blob/main/src/huggingface_hub/hf_api.py).

`key-import --yes` reads only an explicit private owned raw key or single `VLLM_API_KEY=value` file as data. It copies to the private toolkit destination without printing the key, sourcing data, replacing a different key or changing the original. Existing endpoints keep their loaded keys until separately restarted.

CPU llama.cpp `legacy-import --legacy-unit PATH --yes` imports supported native command settings into a **new** owned service, preserving model alias, model path, port, context, threads, quota and private raw-key path. Review `legacy-plan` first, then stop and disable the exact old unit yourself. Import verifies that state and refuses an existing destination, foreign unit, GPU/non-loopback command, unsupported environment override, ambiguous/unknown flags or changed input. The old unit, model/cache data and keys are never modified or deleted; imported assets gain no download/deletion receipt. New service start/autostart are separate actions. This imports supported settings, not arbitrary old service directives or legacy uninstall behavior.

### Existing vLLM CPU settings

```bash
bash setup.sh ai vllm legacy-plan --legacy-unit "$HOME/.config/systemd/user/vllm-local.service" --model /absolute/reviewed/local-snapshot --key-file /absolute/private/imported-key
# After reviewing the plan and separately stopping/disabling the exact old unit:
bash setup.sh ai vllm legacy-import --legacy-unit "$HOME/.config/systemd/user/vllm-local.service" --model /absolute/reviewed/local-snapshot --key-file /absolute/private/imported-key --yes
bash setup.sh ai vllm configure --executable /absolute/reviewed/vllm --model /absolute/local-snapshot --model-alias publisher/model --dtype float32 --kv-cache-gib 1 --cpu-threads 2 --dry-run
```

The importer now supports the old vLLM `serve` command, dtype, context, quota, OMP threads, CPU KV-cache size, `nobind` affinity and paired native Hermes/Qwen3-Coder tool-parser flags. Supply an explicit local model directory: remote repository IDs are never resolved or downloaded implicitly. The old repository ID becomes the served alias so clients keep their model identifier. New configuration accepts `--dtype auto|bfloat16|float32|float16`, `--kv-cache-gib 1..64` and an explicit supported `--tool-parser`; hardware suitability is still a separate review.

Literal allowlisted environment entries are parsed as data. An old `EnvironmentFile` must contain a private single native key; import it separately using `key-import` and supply the matching private `--key-file`. A different key is refused. Unknown variables, shell/systemd expansions, unpaired tool flags and arbitrary service directives are refused. An executable allocator preload is never imported: review it and use `--ignore-legacy-preload` only if intentionally omitting that optimization. Old units, selected-model files, caches, keys and service states remain unchanged.

vLLM invocations use a fresh private runtime cache under `${XDG_CACHE_HOME:-~/.cache}/automation-toolkit/ai/vllm`, not the legacy Hub/runtime directories. Creation occurs only when actually launching the approved runtime; planning, configuration and dry-run create none. Native key values stay out of argv. The runtime clears inherited vLLM overrides, external Hub-cache paths, allocator/Python hooks and external plugin selection, then applies reviewed CPU settings with Hub/Transformers offline. This does not install a CPU wheel, certify a host systemd session or migrate Playground. References: [vLLM CPU guide](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/), [native environment settings](https://docs.vllm.ai/en/stable/configuration/env_vars/).

### Revision-aware cache inventory and verified copies

```bash
bash setup.sh ai vllm cache-list --cache-root /absolute/existing/hub
bash setup.sh ai vllm snapshot-import --cache-root /absolute/existing/hub --manifest /absolute/reviewed-model.json --root /absolute/private/toolkit-snapshots --dry-run
bash setup.sh ai llamacpp snapshot-import --source-dir /absolute/legacy-model-directory --manifest /absolute/reviewed-gguf.json --root /absolute/private/toolkit-snapshots --dry-run
bash setup.sh ai vllm snapshot-remove --root /absolute/private/toolkit-snapshots --model publisher/model --revision EXACT_40_HEX_COMMIT --dry-run
```

Cache inventory is read-only, bounded and revision-aware. Expected Hub snapshot file links are accepted only when they resolve directly into the same repository's regular blob files; escaping, cyclic and directory links are refused. It reports logical bytes per revision, which may share storage; the sum is not a promise of reclaimable disk space. Inventory grants no ownership or deletion permission. See the [official cache layout](https://huggingface.co/docs/huggingface_hub/guides/manage-cache).

Prepare a manifest containing independently reviewed SHA-256 values and exact sizes for **every selected asset**:

```json
{
  "schema": 1,
  "repository": "publisher/model",
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "files": [
    {"path": "config.json", "size": 2, "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"}
  ]
}
```

This illustrative config-only manifest does not constitute a runnable model. Include the weights, tokenizer and configuration assets needed by the chosen runtime, and verify all identities/checksums independently; publisher metadata is discovery evidence. Duplicate fields/paths, unsafe paths, executable/pickle assets, incomplete shard series and oversized inputs are refused. No checksum is invented for an unverified source. Directory copying supports regular legacy GGUF assets; Hub copying supports the validated revision/blob layout. No Hub package, pip dependency or model download is needed.

Apply `snapshot-import` with `--yes` after review. It checks source bytes and free disk, copies into private staging, rechecks copied bytes and publishes files exclusively at `ROOT/PUBLISHER/MODEL/REVISION`. No original model/cache is renamed, hardlinked into the result, deleted or granted a new ownership receipt. A receipt commits the observed copy only after publication; repeated import verifies and reuses an unchanged owned copy. Existing unmanaged/conflicting destinations are refused, including empty directories. A caught interruption can leave an incomplete destination without a receipt, preserved for manual review; it is never silently adopted, reused or recursively removed.

`snapshot-remove --yes` removes only an exact receipt-owned copy after checking all bytes, permissions, links and entries. Later edits, unknown files/directories, changed file permissions/links or a related active/unknown toolkit service cause refusal; no service is stopped. External caches are never deleted. Removal is irreversible for the selected copy; the preserved source can be copied again into a new empty destination. Manually started/untracked applications are outside toolkit service-state detection. No model code or inference runs during inventory/copy/removal, and a successful copy does not prove RAM fit or runtime compatibility.

The old vLLM cache-removal helper is removed. Its retained compatibility caller reuses shared inventory, and deletion requests fail **before** changing services or selection files. Unreceipted cache deletion is retired rather than presented as safe ownership.

### Complete GGUF bundles and old selection recovery

```bash
bash setup.sh ai llamacpp gguf-legacy-list --legacy-root /absolute/old-llamacpp
bash setup.sh ai llamacpp gguf-download --manifest /absolute/reviewed-gguf-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-download --manifest /absolute/reviewed-gguf-bundle.json --yes
bash setup.sh ai llamacpp gguf-list
bash setup.sh ai llamacpp gguf-resolve --manifest /absolute/reviewed-gguf-bundle.json
bash setup.sh ai llamacpp gguf-legacy-import --legacy-root /absolute/old-llamacpp --manifest /absolute/reviewed-gguf-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-select --legacy-root /absolute/old-llamacpp --manifest /absolute/reviewed-gguf-bundle.json --dry-run
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

Legacy inventory reads bounded `.llama-automation.json`, `config/selected-model` and `config/runtime-settings` as data, validating exact repository/folder/quantization identities, complete file sets and GGUF headers. Corrupt old selection/context is refused by default. For explicit recovery, `--ignore-legacy-state` with `--legacy-root` on `gguf-legacy-list`, `gguf-legacy-import` or `gguf-select` omits those two scalar files without reading or editing them; model markers/assets still require full validation and the reviewed manifest. New selection then uses an explicit `--context` or normal owned-controller settings, never an invented old value. A legacy marker is **not** a checksum receipt or deletion authorization. `gguf-legacy-import --yes` copies only the manifest-matching independently checked assets into a separate store outside the old tree, preserving old models, markers, selection files and unrelated contents. It does not infer a missing revision or hash from the old marker. Use the old repository and explicit reviewed quantization; a repository-only old selection does not prove which quantization was active.

`gguf-select --yes` configures the new owned llama.cpp service from the verified primary file with alias `REPOSITORY:QUANTIZATION` (or an explicit reviewed `--model-alias`). With `--legacy-root`, the old selected repository must match, and its validated context is recovered unless overridden by `--context`. Existing executable/key/port/CPU settings follow the normal controller rules. No service is started, enabled or stopped; active new services refuse reconfiguration. Old units and files remain intact. Selecting a bundle does not certify host systemd operation, GPU acceleration or the fit of an arbitrary model/context combination.

The separate legacy GGUF helper is removed. Its remaining compatibility caller shares read-only list/resolve logic for existing files. Unpinned old download requests fail before dependency or file changes; the existing-model compatibility path requires explicit `--download=no` and validates selection before prerequisites. Marker-only deletion fails before touching services or selection files. No new virtual environment, uv or Hub package is installed just to manage GGUF metadata. These compatibility paths are not normal setup entrypoints.

AI `configure` creates only a toolkit-owned user unit and a private allowlisted manifest. `start`, `stop`, `restart`, `service-status`, `logs`, `autostart --enabled yes|no` and `uninstall` apply only to that unit. Model/key assets must validate before starts; stopping/removing the owned unit remains possible if its model or key was removed. Existing legacy units are never adopted. A successful service command is not proof of API readiness: run `test-api` and `test-auth`. `model-select` reuses explicit configuration and refuses changes while active. Native vLLM execution uses a reviewed existing executable and local model directory, with remote downloads/code disabled.

Native package transactions retry only recognized lock/busy errors, up to `AUTOMATION_RETRIES`; other errors and timeouts remain failures. AI build prerequisites run after AI flags are validated, and status/lifecycle operations never install compilers. Cancellation exits 130.

Current test scopes live in the normal validator output under `~/.local/state/automation-toolkit/validation/`. Offline tests, native container package tests, static systemd checks and actual CPU inference are distinct from real host service/desktop/GPU verification. No release deliverable generation is part of local refactoring.

Ollama CLI status/model operations explicitly bind their client target to the selected literal loopback address and remove proxy overrides; an inherited remote `OLLAMA_HOST` cannot redirect diagnostics or model requests. Publisher/native package metadata parsers run with `LC_ALL=C` in child processes only, so translated labels do not produce false missing-package results. Existing llama.cpp source checkouts must have the official upstream origin before build/update.

## Compatibility boundaries

| Representative environment | Native detection/search/core package workflow | Host services / desktop / GPU |
|---|---|---|
| Arch base | Disposable rootless container verified | Not certified by that test |
| Debian 13 / Ubuntu 24.04 | Disposable rootless containers verified | Not certified by those tests |
| Fedora 42 / Rocky 9 | Disposable rootless containers verified; explicit Fedora wget2 replacement | Not certified by those tests |
| openSUSE Tumbleweed | Disposable rootless container verified; version-specific Python mapping | Leap service/desktop behavior remains unverified |
| Alpine 3.22 | Disposable rootless container verified | OpenRC does not imply systemd-user/Lerd support |
| CachyOS KDE/Wayland session | Host detection and read-only desktop favorites plan verified | Desktop mutation and service installation were not performed |

The package fixtures install/check Git, curl, wget (explicit wget2-wget choice on Fedora) and unzip, repeat the transaction, verify unavailable-package exit 5 and plan the catalogue. They also bootstrap the native SSH client/key commands, generate a disposable key, validate an isolated SSH configuration with `ssh -G` (no connection), and persist/list the manual checklist. They do not install or launch every GUI/server package. ShellCheck runs in disposable Debian; local absence is recorded, while shfmt style differences remain informational. The separate llama.cpp and vLLM CPU sandboxes verify real generated responses and protected endpoint authentication. The vLLM sandbox verifies every fixture artifact checksum, copies a pinned model through the snapshot importer, runs the shared invocation builder with dtype/CPU settings and alias, then removes its own copied snapshot and checks original-fixture preservation. The llama.cpp sandbox now serves a verified GGUF bundle; its optional `--with-gguf-shards` gate generates genuine tiny shards with upstream's full CPU image, imports them through the legacy-copy path and tests native inference/authentication. The extra image requires its own cache hit or `--allow-pull`; no host compiler, driver or writable host source mount is used. Only sandbox networking adapts the container-internal bind for rootless publication; host ports remain loopback-only. This establishes CPU-container behavior, not native host systemd or hardware-wide dtype/parser support. Jan uses an authenticated contract fixture only. Systemd unit syntax, supported legacy settings import and owned control paths are tested independently from actual host service operation. SSH passphrase prompts have fixture coverage; isolated native agent protocol/key loading and teardown are tested separately from actual host user-session/autostart behavior. No real provider enrollment is claimed.

The current CPU source-build path was exercised in disposable Debian using the official llama.cpp checkout (0.8.0-dev, commit `4e910a8` for that run), including automatic Make/compiler bootstrap and `llama-server --version`. This verifies that tested CPU build environment, not every compiler/distro/GPU combination. Both CPU inference sandboxes also passed protected API checks; vLLM’s model-card context check confirmed 256 tokens and detected a 512-token mismatch. Exact subsequent run status remains in the normal validation JSON.
