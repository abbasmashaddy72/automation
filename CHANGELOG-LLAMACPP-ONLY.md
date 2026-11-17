# Changelog — AI Server Automation v2 llama.cpp-only migration

## Architecture

- Updated existing AI Server Automation v2 ZIP in place; preserved general Linux
  Automation Toolkit and project structure.
- Replaced dedicated Ollama installer/service/benchmarks with a single llama.cpp
  model server, private OpenAI API and an authenticated LAN gateway.
- AI CLI refuses management of Ollama, vLLM and Jan. Old integration sources
  removed from the shipped toolkit; existing host installations remain untouched.
- Removed optional Ollama/vLLM entries from the default package catalogue and
  disabled `--with-ollama` prerequisites installer action.
- Updated rootless Open WebUI compatibility module to use llama.cpp OpenAI API.

## Capabilities

- CUDA/HIP/Vulkan/CPU build candidate detection, CMake build and upstream revision
  reporting; Metal recognized but automatic macOS installation out of scope.
- Physical CPU/RAM/GPU/VRAM inventory; no shared memory double-counting.
- Five bounded performance profiles, auto tuning with rollback, real generation
  timing, SSE TTFT and optional concurrent client measurements.
- Verified official Qwen GGUF downloads, local checksum receipts, reused model
  files, dedicated mounted SSD enforcement, one loaded shared model.
- Unprivileged systemd service; optional Open WebUI; LAN key authentication;
  private source port, network subnet guard and bounded concurrent requests.
- No automatic disk partitioning, driver replacement, service deletion, model
  deletion or forced clock/power settings.

## Limitations

- CUDA toolkit/compiler compatibility on Ubuntu 26.04 requires a real host test;
  driver version from `nvidia-smi` is not the CUDA build toolkit version.
- ROCm/HIP, Vulkan and Metal builds not exercised on hardware during packaging.
- Live GPU token-speed, TTFT, concurrent throughput, and tuning reports are
  produced on the target server, not fabricated during ZIP construction.
- Existing v2 legacy integration unit tests may no longer describe supported
  behavior; the new llama.cpp test suite covers the new live management path.

## Final hardening changes

- Removed the obsolete multi-engine sandbox.
- Fixed root-owned upstream source Git validation (`sudo git`) on existing builds and upgrades.
- Retained old multi-engine sources and tests only for historical review; no supported active CLI command installs Ollama or vLLM.
- Updated active README/AGENTS references to retired multi-engine scripts.
- Corrected repeat-install handling of an already active current-generation gateway; no re-migration or needless restart.
