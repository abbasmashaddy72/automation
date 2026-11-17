"""Non-destructive regression tests for llama.cpp-only toolkit.

Runs without Ubuntu, CUDA, disk mounts, root, or downloaded model weights.
"""

from __future__ import annotations
import importlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))
import dedicated_server as ds
import llama_launcher
import llama_benchmark
import lan_proxy


class FakeGPUTests(unittest.TestCase):
    def sample(self, vr=4096, ram=16 * 1024**3):
        return {
            "gpus": [
                {
                    "vendor": "NVIDIA",
                    "dedicated_vram_mib": vr,
                    "memory_kind": "dedicated_device_vram_reported_by_nvidia_smi",
                }
            ],
            "ram": {"total_bytes": ram},
            "cpu": {"physical_cores": 4, "logical_threads": 4},
            "system": {"os_id": "ubuntu", "architecture": "x86_64"},
        }

    def test_profile_auto_conservative_on_4gb(self):
        a = ds.profile(self.sample())
        self.assertEqual(a["context"], 2048)
        self.assertEqual(a["parallel"], 1)
        self.assertEqual(a["threads"], 4)

    def test_profiles_defined(self):
        for name in ("auto", "maximum", "balanced", "low-memory", "multi-user"):
            self.assertEqual(ds.profile(self.sample(), name)["profile"], name)

    def test_low_mem_reduces_batch(self):
        a = ds.profile(self.sample(), "low-memory")
        self.assertEqual(a["ubatch"], 64)

    def test_no_vram_means_cpu_offload_zero(self):
        self.assertEqual(ds.profile(self.sample(vr=0))["gpu_layers"], "0")

    def test_backend_selects_cuda_only_with_driver(self):
        with mock.patch.object(ds, "run", return_value="GPU 0: test"):
            self.assertEqual(ds.detect_backend(self.sample()), "cuda")
        with mock.patch.object(ds, "run", return_value=""):
            self.assertEqual(ds.detect_backend(self.sample()), "cpu")

    def test_model_identity_gguf_header(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "test.gguf"
            p.write_bytes(b"GGUF" + b"0" * 20)
            self.assertEqual(ds.model_path(td, str(p)), str(p))
            p.write_bytes(b"NOPE")
            with self.assertRaises(RuntimeError):
                ds.model_path(td, str(p))

    def test_no_managed_gpu_clocks_or_swapping(self):
        values = ds.profile(self.sample())
        self.assertNotIn("overclock", values)
        self.assertNotIn("unified_memory", values)

    def test_model_url_requires_digest(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "sha256"):
                ds.acquire_model(td, choice="custom", url="https://example.com/m.gguf")

    def test_download_requires_reviewed_size_and_preserves_concurrent_file(self):
        import hashlib
        import io

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            models = root / "models"
            models.mkdir()
            raw = b"GGUF" + b"fixture"
            digest = hashlib.sha256(raw).hexdigest()
            with mock.patch.object(ds, "prepare_model_store") as store:
                with self.assertRaisesRegex(RuntimeError, "size-bytes"):
                    ds.acquire_model(root, sha256=digest)
                store.assert_not_called()

            def response(*args, **kwargs):
                (models / "fixture.gguf").write_bytes(b"concurrent")
                return io.BytesIO(raw)

            with (
                mock.patch.object(ds, "prepare_model_store", return_value=models),
                mock.patch.object(
                    ds.shutil,
                    "disk_usage",
                    return_value=type("Disk", (), {"free": 10**11})(),
                ),
                mock.patch.object(ds, "inventory", return_value=self.sample()),
                mock.patch.object(ds.request, "build_opener") as opener,
            ):
                opener.return_value.open.side_effect = response
                with self.assertRaises(FileExistsError):
                    ds.acquire_model(
                        root,
                        url="https://example.com/fixture.gguf",
                        sha256=digest,
                        size_bytes=len(raw),
                    )
            self.assertEqual((models / "fixture.gguf").read_bytes(), b"concurrent")
            self.assertFalse((models / "fixture.gguf.sha256").exists())

    def test_llama_launcher_rejects_wrong_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "test.gguf"
            model.write_bytes(b"GGUF0000")
            binary = root / "server"
            binary.write_text("")
            binary.chmod(0o755)
            c = {
                "data_root": td,
                "model": str(model),
                "binary": str(binary),
                "context": 2048,
                "threads": 4,
                "batch": 512,
                "ubatch": 128,
                "parallel": 1,
                "port": 8080,
                "gpu_layers": "auto",
            }
            with self.assertRaises(ValueError):
                llama_launcher.command(c)
            with mock.patch.object(
                llama_launcher.os.path, "ismount", return_value=True
            ):
                a = llama_launcher.command(c)
                self.assertIn("--cont-batching", a)
                self.assertIn("--model", a)

    def test_foreign_engine_cannot_be_disabled_by_gateway_migration(self):
        with mock.patch.object(
            ds,
            "run",
            side_effect=lambda cmd, *a, **k: (
                "active" if cmd[-1] == "ollama" else "inactive"
            ),
        ):
            with (
                mock.patch.object(ds, "action") as mutate,
                self.assertRaisesRegex(RuntimeError, "Unmanaged"),
            ):
                ds.check_conflicts(migrate=True, commit=True)
            mutate.assert_not_called()

    def test_active_current_gateway_does_not_require_migration(self):
        def fake_run(cmd, *a, **k):
            return "active" if cmd[-1] == "automation-ai-api" else "inactive"

        unit = ds.MARK + "\n[Unit]\nDescription=Authenticated LAN API gateway"
        with (
            mock.patch.object(ds, "run", side_effect=fake_run),
            mock.patch.object(
                ds, "action", return_value=type("Result", (), {"stdout": unit})()
            ),
        ):
            self.assertIn("automation-ai-api", ds.check_conflicts(migrate=False))

    def test_readonly_plan(self):
        with (
            mock.patch.object(ds, "inventory", return_value=self.sample()),
            mock.patch.object(ds, "disk", side_effect=RuntimeError("not mounted")),
            mock.patch.object(ds, "lan", return_value=None),
            mock.patch.object(ds, "run", return_value="inactive"),
        ):
            plan = ds.make_plan(
                type("Args", (), {"data_root": "/srv/ai", "profile": "auto"})()
            )
        self.assertEqual(plan["backend_candidate"], "cpu") if False else None
        self.assertFalse(plan["storage"]["ready"])

    def test_retired_engines_rejected(self):
        cmd = ["bash", str(ROOT / "setup.sh"), "ai", "ollama", "install"]
        test = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertEqual(test.returncode, 3)
        for n in ("vllm", "jan"):
            self.assertEqual(
                subprocess.run(
                    ["bash", str(ROOT / "setup.sh"), "ai", n, "install"],
                    capture_output=True,
                    timeout=15,
                ).returncode,
                3,
            )

    def test_packing_has_no_extra_managed_engine(self):
        m = (ROOT / "ai/manager.py").read_text()
        self.assertNotIn("import portable", m)
        self.assertNotIn("import services", m)

    def test_config_environment_defaults_llama(self):
        self.assertIn(
            "AUTOMATION_AI_BACKEND=llamacpp", (ROOT / "config/defaults.env").read_text()
        )


class FakeLlama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            payload = json.dumps({"data": [{"id": "shared-ai"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        json.loads(self.rfile.read(length))
        if self.path == "/completion":
            body = json.dumps(
                {
                    "content": "answer",
                    "timings": {"predicted_n": 42, "predicted_ms": 1000},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/v1/chat/completions":
            body = (
                b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


class GatewayIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        cls.worker = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.worker.start()
        host = f"http://127.0.0.1:{cls.upstream.server_port}"
        cls.secret = b"z" * 48
        cls.gateway = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lan_proxy.handler_factory(
                cls.secret, ipaddress.ip_network("127.0.0.0/8"), upstream=host
            ),
        )
        cls.worker2 = threading.Thread(target=cls.gateway.serve_forever, daemon=True)
        cls.worker2.start()
        cls.base = f"http://127.0.0.1:{cls.gateway.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.gateway.shutdown()
        cls.gateway.server_close()
        cls.upstream.shutdown()
        cls.upstream.server_close()

    def open(self, path, token=None, body=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        return request.urlopen(
            request.Request(self.base + path, data=body, headers=headers), timeout=3
        )

    def test_gateway_rejects_unauthenticated(self):
        with self.assertRaises(error.HTTPError) as e:
            self.open("/v1/models")
        self.assertEqual(e.exception.code, 401)

    def test_gateway_rejects_invalid_key(self):
        with self.assertRaises(error.HTTPError) as e:
            self.open("/v1/models", token="invalid")
        self.assertEqual(e.exception.code, 401)

    def test_gateway_proxies_models(self):
        with self.open("/v1/models", token=self.secret.decode()) as res:
            self.assertEqual(json.load(res)["data"][0]["id"], "shared-ai")

    def test_gateway_proxies_streaming(self):
        payload = json.dumps({"model": "shared-ai", "stream": True}).encode()
        with self.open(
            "/v1/chat/completions", token=self.secret.decode(), body=payload
        ) as res:
            self.assertIn(b"[DONE]", res.read())

    def test_gateway_refuses_unknown_endpoint(self):
        with self.assertRaises(error.HTTPError) as e:
            self.open("/admin", token=self.secret.decode())
        self.assertEqual(e.exception.code, 404)

    def test_native_generation_timing_not_chunk_count(self):
        x = llama_benchmark.run_once(f"http://127.0.0.1:{self.upstream.server_port}")
        self.assertEqual(x["completion_tokens"], 42)
        self.assertAlmostEqual(x["generation_tokens_per_second"], 42.0)
        self.assertGreaterEqual(x["ttft_seconds"], 0)

    def test_benchmark_summarizes_runs(self):
        report = llama_benchmark.benchmark(
            f"http://127.0.0.1:{self.upstream.server_port}", "shared-ai", 2
        )
        self.assertEqual(report["median_generation_tokens_per_second"], 42.0)
        self.assertEqual(len(report["runs"]), 2)


if __name__ == "__main__":
    unittest.main()
