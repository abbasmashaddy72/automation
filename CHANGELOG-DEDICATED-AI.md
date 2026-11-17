# Dedicated AI Server v2 — change summary

Input: uploaded `automation(1).zip` (248 archive entries). This update modifies the existing toolkit instead of replacing it.

- Integrated `bash setup.sh ai server ...` routing through the existing `ai/manager.py` CLI.
- Added `ai/hardware_inventory.py`: read-only CPU, GPU, VRAM, RAM and disk inventory and conservative profile selection.
- Added `ai/dedicated_server.py`: read-only plan/status, repeatable Ollama setup requiring a mounted ext4 secondary SSD, optional LAN gateway and WebUI, key management, benchmarks and context tuning.
- Added `ai/lan_proxy.py`: narrow Ollama API allowlist, constant-time Bearer key verification, private-LAN source filtering, fixed localhost upstream, no prompt/secret access logs.
- Added `ai/ollama_benchmark.py`: real token-stream timing, load time and TTFT, CPU/RAM before/after, NVIDIA samples, and optional 2-request concurrency benchmark. No synthetic benchmark scores.
- Added `tests/test_dedicated_ai_server.py`: offline unit safety and regression checks.
- Added installation, troubleshooting, acceptance and rollback guide, target-reference report with explicit user-reported provenance, and an unmeasured benchmark placeholder.
- Existing Laravel, legacy migration, llama.cpp, vLLM, GGUF, checklist, packaging, update and system management modules preserved.
- Original `.env` and Python cache files deliberately excluded from release archive to avoid exporting possible secrets or stale bytecode.

**Verification limits**: No operations on the target physical SSD, GPU, local network, or firmware were performed from this environment. The original automation suite may contain unrelated code paths that are not covered by the focused new tests; inspect the test report included with this archive.
