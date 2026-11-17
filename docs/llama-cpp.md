# Managed llama.cpp installation

```bash
bash setup.sh ai server hardware
bash setup.sh ai server storage
bash setup.sh ai server plan
```

Managed installation uses the shared native prerequisite installer on mutable
systemd hosts in the Arch, Debian/Ubuntu, Fedora/RHEL and openSUSE families.
Installations require working configured repositories. OpenRC, WSL, immutable
hosts and containers can use the planning tools. GPU builds require a compatible
existing vendor toolchain. Use `--backend cpu` for a CPU build.

## Choose model storage

| Available storage                      | Setup                                                                                                 |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Local filesystem                       | Use the default `/srv/ai` or set `--data-root /absolute/path`. Setup creates the directory as needed. |
| Already mounted drive                  | Set `--data-root` to a directory on that mount.                                                       |
| Unmounted spare disk with a filesystem | List candidates with `ai server storage`, then supply `--mount-uuid` with the reviewed UUID.          |
| Blank disk                             | Prepare a filesystem separately before selecting it.                                                  |

Automatic attachment handles an existing ext4, XFS or Btrfs filesystem on
an unused non-removable disk. The selector excludes active disks, swap, and
ambiguous UUIDs. Choose an empty mount point under administrator-controlled
directories such as `/srv`. The toolkit creates a
systemd mount unit tied to the selected UUID and uses it when the service starts.
If the volume is unavailable, service start fails. A partially completed
installation may leave the reviewed mount active and its unit available for a
retry with the same UUID. Existing configured directories are reused on reruns.
Automatic attachment requires a healthy standalone filesystem. Prepare blank
disks and complex storage such as encrypted or multi-device volumes separately.
See the [systemd mount unit reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.mount.html).

```bash
# Preview attaching a spare volume
bash setup.sh ai server plan --data-root /srv/ai --mount-uuid REVIEWED_UUID

# Reuse a GGUF already in local storage or on an existing mount
bash setup.sh ai server install --data-root /srv/ai \
  --model /srv/ai/models/my-model.gguf --no-pull --backend cpu --yes

# Attach a reviewed volume that already contains the GGUF
bash setup.sh ai server install --data-root /srv/ai --mount-uuid REVIEWED_UUID \
  --model /srv/ai/models/my-model.gguf --no-pull --backend cpu --yes
```

Add `--dry-run` to preview installation. New model downloads require an
independently reviewed SHA-256 and exact size. Review storage free space and
GPU compatibility separately. The service serves one model at
`127.0.0.1:8080`. Add `--with-lan-api` if you want the authenticated LAN gateway.

### Existing Ollama or old gateway detected?

The installer refuses to stop third-party engines. Review and resolve any
conflict separately. `--migrate-legacy` only replaces an owned old gateway;
installed packages, old model weights and user data are preserved.

### Use your own GGUF instead

```bash
# Existing verified GGUF within /srv/ai, no download
bash setup.sh ai server install \
  --model /srv/ai/models/my-model.gguf --no-pull --yes

# Create the storage directory and install using a reviewed GGUF download:
bash setup.sh ai server install \
  --model-url 'https://example.org/verified-model.gguf' \
  --sha256 'REPLACE_WITH_64_HEX_DIGEST' --size-bytes EXACT_BYTES --yes

# Switch without downloading a second copy
bash setup.sh ai server switch --model /srv/ai/models/my-model.gguf --yes
```

The default is a small, quantized model suitable for a 4 GB card. Choosing a
19 GB GGUF on this system is **not** recommended; disk size and runtime memory
are separate. `--allow-oversized` explicitly accepts the download risk.

## Access from other LAN devices

```bash
bash setup.sh ai server urls
bash setup.sh ai server status
bash setup.sh ai server key-show
```

Example, assuming DHCP still assigns `LAN_IP`:

- **Raw private llama.cpp:** `http://127.0.0.1:8080/v1`
- **Authenticated shared LAN API:** `http://LAN_IP:11435/v1`
- **Optional authenticated Open WebUI:** `http://LAN_IP:3000`

From a **different trusted LAN device**:

```bash
read -rsp 'AI API key: ' AI_KEY; echo
curl -fsS http://LAN_IP:11435/v1/models \
  -H "Authorization: Bearer $AI_KEY"

curl -fsS http://LAN_IP:11435/v1/chat/completions \
  -H "Authorization: Bearer $AI_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"shared-ai","messages":[{"role":"user","content":"Hello"}],"max_tokens":64}'
unset AI_KEY
```

OpenAI-compatible SDKs: `base_url=http://LAN_IP:11435/v1`, and use
the secret as `api_key`. The same loaded model is reused across chat, coding,
mobile backends and automation clients; each client does **not** download a model.

**Security:** LAN HTTP is plaintext. Never forward ports 8080/11435/3000 from
your router. Browser-only clients should call your own authenticated backend;
CORS preflight is deliberately disabled at the gateway to prevent leaking
Bearer keys into browser code. Use HTTPS reverse proxy/VPN for untrusted links.

## Performance profiles and measurements

```bash
bash setup.sh ai server benchmark --repeats 3 --concurrency 2 \
  --output ~/ai-benchmark.json
bash setup.sh ai server tune --repeats 3 --yes \
  --output ~/ai-tuning.json
```

Available installation profiles: `auto` (default, bounded live tuning),
`maximum`, `balanced`, `low-memory`, `multi-user`. The GPU offload is `auto` and
actual limits are confirmed by llama.cpp at runtime. On your 4 GB card, the
conservative base is 2048 context, 1 parallel slot, 512 batch/128 microbatch.

Benchmarks measure native `/completion` predicted token counts and model
prediction milliseconds **plus** time-to-first-content from OpenAI SSE. They
never mistake streaming chunks for tokens. Optional concurrent-client tests
measure request completion, not guaranteed per-request throughput. Status
reports include NVIDIA VRAM use and temperature if the driver exposes them.

## Optional chat interfaces

Use [ChatGPT Lite](../chatgpt-lite/README.md) for a browser-local chat workspace,
or the [rootless Open WebUI workflow](configuration-and-webui.md#rootless-open-webui)
for authenticated accounts. Each is configured separately from the server.

## Troubleshooting, preservation and rollback

```bash
sudo journalctl -u automation-llamacpp -n 150 --no-pager
sudo journalctl -u automation-ai-api -n 150 --no-pager
systemctl status automation-llamacpp automation-ai-api
findmnt /srv/ai
nvidia-smi
sudo cat /etc/automation-ai/llamacpp.json
bash setup.sh ai server plan
```

- Model path and service config: `/etc/automation-ai/llamacpp.json`.
- Model files: the selected data directory, with downloads in its `models/` subdirectory.
- Last-owned config backups: `*.backup-YYYYMMDDHHMMSS` in `/etc/automation-ai`.
- Source/build: `/opt/automation-ai/llama.cpp`, with recorded commit in
  `automation-build.json`.
- To restore old settings after an unsuccessful change, copy a reviewed backup
  back to `llamacpp.json`, run `sudo systemctl restart automation-llamacpp`,
  and verify `/health` from the server before allowing LAN traffic.

AI installation is opt-in. Existing third-party services and model stores
are preserved. Optional clients: [ChatGPT Lite](../chatgpt-lite/README.md) and
[Open WebUI](configuration-and-webui.md).

## Testing and limitations

```bash
PYTHONPATH=ai:lib python3 -m unittest -q tests.test_llamacpp_server_v21
bash setup.sh validate --mode offline
```

Offline tests cover route authentication, SSE, genuine upstream timing parsing,
profile bounds, path checks, and old-engine CLI rejection. Because tests are
performed in a container without your NVIDIA GPU, the following are **not**
certified by offline fixtures: real CUDA compilation on your target host,
actual token/s and TTFT, real 4 GB VRAM fit, long-running thermal stability,
WebUI provider networking, GPU backend comparison, LAN firewall/router rules, and
real multi-client throughput. Run the live benchmark on your AI host to obtain
real performance numbers. Do not interpret any CPU/VRAM numbers printed in the
packaging environment as your server measurements.
