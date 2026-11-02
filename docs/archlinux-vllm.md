# vLLM and Jan API integration

Use a hardware-reviewed, already installed vLLM executable and an existing **local** model directory with `config.json`. No remote model code/downloads are enabled by the runtime. Native installation of CUDA/ROCm/PyTorch/vLLM is deliberately separate; host drivers and Python installations are never changed by status/configuration.

```bash
bash setup.sh ai vllm status
bash setup.sh ai vllm serve --executable /absolute/venv/bin/vllm --model /absolute/model-directory --key-file /absolute/private/api-key --yes
bash setup.sh ai vllm configure --executable /absolute/venv/bin/vllm --model /absolute/model-directory --key-file /absolute/private/api-key --yes
bash setup.sh ai vllm service-status
bash setup.sh ai vllm start --yes
bash setup.sh ai vllm models --key-file /absolute/private/api-key
bash setup.sh ai vllm test-auth --key-file /absolute/private/api-key
bash setup.sh ai vllm api-config
```

The shared owned-unit controller supplies configure/start/stop/restart/logs/autostart/unit uninstall. It never takes ownership of `vllm-local.service`, installs Playground or deletes external Hub caches. `legacy-plan`/`legacy-import` now copy supported stopped/disabled CPU service settings into a new owned unit, preserving dtype, CPU controls, served alias and supported native tool-parser choice. Literal environment entries are allowlisted data; private imported keys must match, and executable allocator preloads require explicit omission review. Supply an explicit local model path. See [migration and verified-copy commands](unified-setup.md#existing-vllm-cpu-settings).

Native keys reach vLLM through `VLLM_API_KEY` in its runtime environment, never argv. Runtime cache data uses a separate private toolkit directory; inherited vLLM/plugin/cache overrides are cleared and remote downloads/code remain disabled. Status/diagnostic requests stay loopback-only. Unit generation/control and settings import are fixture-tested; the rootless CPU sandbox verifies actual inference/auth/context using the shared runtime builder and a verified snapshot copy. Actual host systemd operation, GPU acceleration and all hardware dtype/parser combinations remain separate gates. See [upstream CPU installation](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/) and [native authentication scope](https://docs.vllm.ai/en/latest/usage/security/).

## Existing Jan Desktop API

```bash
bash setup.sh ai jan status
bash setup.sh ai jan models --key-file /absolute/private/api-key
bash setup.sh ai jan test-auth --key-file /absolute/private/api-key
bash setup.sh ai jan smoke --model EXISTING_MODEL --key-file /absolute/private/api-key
```

Jan's documented API is `127.0.0.1:1337`; toolkit keys must be applied explicitly in Jan Desktop API settings. No Jan GUI configuration, installation or lifecycle is performed. The OpenAI API contract is tested with a temporary authenticated endpoint, which does not certify actual Jan inference. [Jan API reference](https://docs.jan.ai/desktop/api-preference).

An independent CPU smoke test is available through the existing sandbox runner:

```bash
python3 scripts/ai_sandbox.py --backend vllm --yes --allow-download --output "$HOME/.local/state/automation-toolkit/validation/vllm"
```

It uses the official CPU image (explicit `--allow-pull` if absent) and a pinned 135M-parameter SmolLM2-Instruct safetensors fixture, checks RAM/disk and weights SHA-256, runs with dropped capabilities and a loopback-only host port, and removes only its temporary model/key/container. Check the normal JSON result for actual pass/fail/skip status; unit contracts alone do not establish vLLM execution. No test needs host Python/GPU/package installation.
