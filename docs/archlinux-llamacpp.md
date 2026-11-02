# Unified llama.cpp CPU workflow

Arch uses the same portable implementation as other recognized Linux families. Existing legacy units and model directories are preserved without adoption.

```bash
bash setup.sh ai llamacpp check
bash setup.sh ai llamacpp install --dry-run --yes
bash setup.sh ai llamacpp install --yes
bash setup.sh ai llamacpp models --root /absolute/model-directory
bash setup.sh ai llamacpp serve --model /absolute/model.gguf --context 4096 --cpu-threads 2 --yes
```

The build targets only `llama-server`: CPU-only, headless, with embedded/prebuilt UI, outbound OpenSSL, external subprocess tools and extra apps/examples disabled. Model downloads use the toolkit’s separate verified Python HTTPS path; the generated backend serves loopback HTTP only. It uses a dedicated source/build directory under `~/.local/share/automation-toolkit/ai/llamacpp`. Existing source changes block updates. `serve` stays in the foreground and stops on Ctrl-C; it does not install systemd units or implement autostart. Foreground quota overrides are rejected; CPU quotas belong to explicitly configured user services. Unsupported bulk-download flags remain rejected.

## Keys and protected API verification

```bash
bash setup.sh ai llamacpp key-generate --yes
bash setup.sh ai llamacpp key-status
bash setup.sh ai llamacpp key-copy
bash setup.sh ai llamacpp key-use --yes
bash setup.sh ai llamacpp key-rotate --yes
bash setup.sh ai llamacpp serve --model /absolute/model.gguf --key-file /absolute/private/api-key --port 8094 --yes
bash setup.sh ai llamacpp test-auth --key-file /absolute/private/api-key --port 8094
bash setup.sh ai llamacpp smoke --model local --key-file /absolute/private/api-key --port 8094
bash setup.sh ai llamacpp context --context 4096 --key-file /absolute/private/api-key --port 8094
```

The default key location is `$XDG_CONFIG_HOME/automation-toolkit/ai/llamacpp/api-key`, falling back to `~/.config/...`. Native key files are mode 0600, their directory 0700. Keys never appear in argv or normal logs. Copy passes the key via clipboard stdin; if no clipboard exists it uses the controlling terminal only. Noninteractive copy without either refuses output. `key-use` reads privately with getpass. Rotation changes only the stored file: explicitly restart the server to load it. `key-revoke --yes` removes only the stored key and explains that running endpoints retain loaded keys until restarted. Authentication is backend-native, with no proxy. `test-auth` checks valid, invalid and absent keys on `/v1/models`; `/health` is public and cannot establish enforcement.

## Model artifacts

```bash
bash setup.sh ai llamacpp model-download --root /absolute/models --model tiny.gguf --url https://publisher.example/tiny.gguf --sha256 VERIFIED_SHA256 --size-bytes EXACT_BYTES --yes
bash setup.sh ai llamacpp model-remove --root /absolute/models --model tiny.gguf --dry-run
```

Supply an independently verified hash and exact size from the publisher. HTTPS, RAM, disk, size, hash and GGUF header are checked before exclusive activation. Verified existing files are reused. Removal requires a matching toolkit receipt and `--yes`; changed or unrelated models and shared caches are protected.

Complete models, including split GGUF sets, now use a reviewed bundle manifest:

```bash
bash setup.sh ai llamacpp gguf-download --manifest /absolute/reviewed-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-list
bash setup.sh ai llamacpp gguf-resolve --manifest /absolute/reviewed-bundle.json
bash setup.sh ai llamacpp gguf-legacy-list --legacy-root /absolute/old-llamacpp
bash setup.sh ai llamacpp gguf-legacy-import --legacy-root /absolute/old-llamacpp --manifest /absolute/reviewed-bundle.json --dry-run
bash setup.sh ai llamacpp gguf-select --legacy-root /absolute/old-llamacpp --manifest /absolute/reviewed-bundle.json --dry-run
```

Bundles require explicit URLs, exact sizes and independent checksums for every file, with one unambiguous complete shard series. Aggregate RAM/disk checks precede downloading; verified completed artifacts are reused on retry. Source legacy models, markers, selections and unrelated files remain intact. New owned selection recovers a matching repository/quantization alias and validated old context without starting or stopping services. Inventory distinguishes verified owned bundles from incomplete/changed entries. [Manifest, retry and selection instructions](unified-setup.md#complete-gguf-bundles-and-old-selection-recovery) describe paths and receipt-based removal. Quantization labels do not establish model quality or hardware fit.

```bash
python3 scripts/ai_sandbox.py --yes --allow-download --output /tmp/automation-ai
python3 scripts/ai_sandbox.py --yes --allow-download --with-gguf-shards --allow-pull --output /tmp/automation-ai-shards
```

This opt-in uses the 1,185,376-byte upstream `stories260K.gguf` fixture in a rootless CPU container. It tests real generation from a verified bundle, native authentication, effective context/mismatch detection, cached reuse, key rotation/revocation and teardown. The optional shard gate uses upstream's full CPU image to generate genuine tiny GGUF shards, imports them through the legacy-copy path and verifies native generation/authentication before removing its own fixture bundles/containers. It is not a coding-quality benchmark or GPU/host-service certification. Images require explicit `--allow-pull` when absent; no contributor-host packages, services, shared caches or existing models are modified.

References: [server flags/API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [official container](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md), [pinned fixture](https://huggingface.co/ggml-org/tiny-llamas/blob/def3e2dd70df35ecbf6403ea347de4c5977220c1/stories260K.gguf).

## Optional owned user services

```bash
bash setup.sh ai llamacpp configure --model /absolute/model.gguf --key-file /absolute/private/api-key --context 4096 --cpu-threads 2 --cpu-quota 200% --yes
bash setup.sh ai llamacpp start --yes
bash setup.sh ai llamacpp service-status
bash setup.sh ai llamacpp autostart --enabled yes --yes
bash setup.sh ai llamacpp stop --yes
bash setup.sh ai llamacpp uninstall --yes
```

These manage only `automation-ai-llamacpp.service`. Installation/configuration never starts or enables it automatically. Uninstall removes only the owned unit; keys, binaries, saved configuration and models remain. Edited or unrelated units are refused. To switch model/context/key file, stop the owned service, configure the explicit values and start it again. A changed stored key takes effect only after explicit restart; revoking a stored key does not revoke one already loaded in memory. Stop the owned service to revoke runtime access and verify the endpoint is unavailable.

`api-config` provides the interactive generate/use/copy/test/rotate/revoke/status menu. `model-search --query NAME` discovers publisher repositories without approving downloads. Lifecycle commands are fixture-tested with static systemd unit verification; the independent sandbox validates real llama.cpp API/model operation. Its expanded checks include malformed authenticated requests, occupied port detection, rotation/restart with old-key rejection and shutdown after stored-key revocation. GPU/real host systemd validation is separate.

The disposable source-build gate uses the same validated entrypoint and dependency bootstrap:

```bash
python3 scripts/container_workflows.py --allow-install --containers debian --with-ai-build --with-lint --output "$HOME/.local/state/automation-toolkit/validation/build"
```

Only the disposable Debian layer receives the compiler/tooling. Builds require the official source origin, respect requested bounded parallelism and never touch host models, binaries or services.

New toolkit API keys must be stored outside the source tree. The default private XDG configuration location satisfies this; local `.env.*` files and downloaded artifacts are excluded from test snapshots and source inventories. Existing external key files remain read-only until an explicit rotate/revoke action.
