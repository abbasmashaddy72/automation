"""Offline safety and behavior regression tests; no actual host installation."""

from __future__ import annotations
from argparse import Namespace
import contextlib
import importlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))
import hardware_inventory as hw
import dedicated_server as srv
import lan_proxy


class InventoryTests(unittest.TestCase):
    def test_desktop_details_use_live_kde_and_allowlisted_dmi(self):
        output = "\n".join(
            [
                "Operating System: Test Linux",
                "KDE Plasma Version: 6.8.3",
                "Graphics Processor 1: Intel: Xe",
                "Serial Number: Do not expose",
            ]
        )
        with (
            patch.dict(
                hw.os.environ,
                {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"},
            ),
            patch.object(hw, "run", return_value=output) as probe,
            patch.object(
                hw,
                "read",
                side_effect=lambda path: {
                    "sys_vendor": "Vendor",
                    "product_name": "Product",
                    "product_version": "Version",
                }[path.name],
            ),
        ):
            self.assertEqual(
                hw.desktop_details(),
                {
                    "Operating System": "Test Linux",
                    "KDE Plasma Version": "6.8.3",
                    "Graphics Processor 1": "Intel: Xe",
                    "Graphics Platform": "Wayland",
                    "Manufacturer": "Vendor",
                    "Product Name": "Product",
                    "System Version": "Version",
                },
            )
            probe.assert_called_once_with(["kinfo"], timeout=8)

    def test_memory_parser(self):
        with patch.object(
            hw,
            "read",
            return_value="MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\nSwapTotal: 100 kB",
        ):
            self.assertEqual(hw.meminfo()["MemTotal"], 16000000 * 1024)

    def test_cpu_lscpu_without_inferred_base(self):
        lines = {
            "lscpu": [
                {"field": "Architecture:", "data": "x86_64"},
                {"field": "Model name:", "data": "Ryzen 3 2200G"},
                {"field": "Core(s) per socket:", "data": "4"},
                {"field": "Socket(s):", "data": "1"},
                {"field": "CPU(s):", "data": "4"},
            ]
        }
        with (
            patch.object(
                hw,
                "run",
                side_effect=lambda args, timeout=5: (
                    json.dumps(lines) if args[0] == "lscpu" else ""
                ),
            ),
            patch.object(hw, "read", return_value="flags\t: avx2 sse4_2"),
        ):
            info = hw.cpu()
            self.assertEqual(info["physical_cores"], 4)
            self.assertIsNone(info["base_clock_mhz"])

    def test_nvidia_dedicated_vram_separate(self):
        def responses(args, timeout=5):
            if args[0] == "lspci":
                return ""
            if args[0] == "nvidia-smi" and args[1].startswith("--query-gpu=index,"):
                return "0, GeForce GTX 1650, GPU-UUID, 4096, 3800, 595.91.07, 34, 1"
            return ""

        with patch.object(hw, "run", side_effect=responses):
            g = hw.gpu()[0]
        self.assertEqual(g["dedicated_vram_mib"], 4096)
        self.assertIsNone(g["shared_system_ram_mib"])

    def test_profile_small_vram(self):
        info = {
            "ram": {"total_bytes": 16 * 1024**3},
            "cpu": {"physical_cores": 4, "logical_threads": 4},
            "gpus": [{"vendor": "NVIDIA", "dedicated_vram_mib": 4096}],
        }
        p = hw.profile(info)
        self.assertEqual(p["parallel_requests"], 1)
        self.assertEqual(p["context"], 2048)
        self.assertEqual(p["max_loaded_models"], 1)

    def test_no_gpu_profile(self):
        info = {
            "ram": {"total_bytes": 8 * 1024**3},
            "cpu": {"physical_cores": 2, "logical_threads": 4},
            "gpus": [],
        }
        self.assertEqual(hw.profile(info)["mode"], "cpu (GPU backend not verified)")


class SafetyTests(unittest.TestCase):
    def test_active_unchanged_llama_service_repairs_disabled_boot_without_restart(self):
        with (
            patch.object(srv, "launcher_command"),
            patch.object(srv, "ensure_account"),
            patch.object(srv, "prepare_model_store"),
            patch.object(srv, "allow_service_read"),
            patch.object(srv, "store_config", return_value=False),
            patch.object(srv, "install_owned", return_value=False),
            patch.object(srv, "run", side_effect=["active", "", "active", "enabled"]),
            patch.object(srv, "action") as execute,
        ):
            srv.ensure_service({"model": "/srv/ai/fixture.gguf"}, "/srv/ai")
            execute.assert_called_once_with(
                ["systemctl", "enable", srv.SERVICE.name], root=True
            )

    def test_status_separates_compiled_binary_from_background_service(self):
        output = io.StringIO()
        with (
            patch.object(srv, "load_config", side_effect=RuntimeError("No config")),
            patch.object(srv, "disk", return_value={}),
            patch.object(srv, "check_installed_storage"),
            patch.object(
                srv,
                "run",
                side_effect=[
                    "LoadState=not-found\nActiveState=inactive\nUnitFileState=",
                    "",
                    "",
                ],
            ),
            patch.object(srv, "lan", return_value=None),
            patch.object(srv, "BIN") as binary,
            contextlib.redirect_stdout(output),
        ):
            binary.is_file.return_value = True
            self.assertEqual(srv.print_status(Namespace(data_root="/srv/ai")), 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status["managed_binary"])
        self.assertFalse(status["configured"])
        self.assertEqual(status["service_unit"], "not-found")
        self.assertEqual(status["service"], "inactive")
        self.assertEqual(status["boot_state"], "")
        self.assertIsNone(status["api_ready"])

    def test_service_stop_reads_inactive_state_even_though_is_active_would_fail(self):
        with (
            patch.object(srv, "managed_service_config"),
            patch.object(srv, "action") as execute,
            patch.object(srv, "run", return_value="inactive") as observe,
        ):
            self.assertEqual(srv.service_control("stop", True), 0)
            execute.assert_called_once_with(
                ["systemctl", "stop", srv.SERVICE.name], root=True
            )
            observe.assert_called_once_with(
                [
                    "systemctl",
                    "show",
                    srv.SERVICE.name,
                    "--property=ActiveState",
                    "--value",
                ]
            )

    def test_loopback_port_check_distinguishes_free_healthy_and_unverified(self):
        with (
            patch("socket.socket") as socket_factory,
            patch("ai_health.check_api") as check,
        ):
            sock = socket_factory.return_value.__enter__.return_value
            self.assertEqual(srv.check_loopback_port(8080)["state"], "free")
            check.assert_not_called()
            sock.bind.assert_called_with(("127.0.0.1", 8080))
            sock.bind.side_effect = OSError("in use")
            for health_code, state in ((0, "healthy"), (3, "unavailable")):
                check.return_value = health_code
                self.assertEqual(srv.check_loopback_port(8080)["state"], state)
            check.assert_called_with("llamacpp", "127.0.0.1", 8080)

    def test_model_scan_includes_root_and_models_but_excludes_shards_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models").mkdir()
            for filename in (
                "existing.GGUF",
                "models/reused.gguf",
                "models/split-00001-of-00002.gguf",
            ):
                (root / filename).write_bytes(b"GGUF")
            (root / "models/invalid.gguf").touch()
            (root / "link.gguf").symlink_to(root / "existing.GGUF")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(srv.main(["models", "--data-root", directory]), 0)
            self.assertEqual(
                {Path(row["path"]).name for row in json.loads(output.getvalue())},
                {"existing.GGUF", "reused.gguf"},
            )

    def test_context_preview_is_read_only_and_refuses_beyond_training_limit(self):
        config = {"context": 2048, "parallel": 2, "model": "test.gguf"}
        output = io.StringIO()
        with (
            patch.object(srv, "managed_service_config", return_value=config),
            patch.object(srv, "run", return_value="active"),
            patch.object(srv, "launcher_command"),
            patch("gguf_context.trained_context_from_gguf", return_value=8192),
            patch.object(srv, "store_config") as save,
            patch("ai_health.smoke_inference") as inference,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(srv.change_context(16384, False, dry_run=True), 0)
            self.assertEqual(
                json.loads(output.getvalue())["target_tokens_per_slot"], 8192
            )
            with self.assertRaisesRegex(ValueError, "training limit"):
                srv.change_context(16386, True, dry_run=True)
            with self.assertRaisesRegex(ValueError, "use --yes"):
                srv.change_context(8192, False, dry_run=False)
            save.assert_not_called()
            inference.assert_not_called()

    def test_context_change_restores_configuration_if_generation_fails(self):
        previous = {
            "model": "test.gguf",
            "context": 4096,
            "parallel": 1,
            "port": 8083,
            "alias": "fixture",
            "_managed": srv.MARK,
        }
        candidate = {**previous, "context": 8192, "context_manual": True}
        with (
            patch.object(srv, "managed_service_config", return_value=previous),
            patch.object(srv, "load_config", side_effect=[previous, candidate]),
            patch.object(srv, "run", return_value="active"),
            patch.object(srv, "launcher_command"),
            patch.object(srv, "store_config", return_value=True) as save,
            patch.object(srv, "action") as action,
            patch.object(srv, "wait_health", return_value=True),
            patch("gguf_context.trained_context_from_gguf", return_value=8192),
            patch("ai_health.runtime_context", return_value=0) as context,
            patch("ai_health.smoke_inference", return_value=3) as inference,
        ):
            with self.assertRaisesRegex(RuntimeError, "generation checks"):
                srv.change_context(8192, True, dry_run=False)
            self.assertEqual(
                [call.args[0] for call in save.call_args_list], [candidate, previous]
            )
            self.assertEqual(action.call_count, 2)
            context.assert_called_once_with("llamacpp", port=8083, desired=8192)
            inference.assert_called_once_with(
                "llamacpp", "fixture", port=8083, timeout=60
            )

    def test_model_directory_cannot_be_filesystem_root(self):
        with self.assertRaises(ValueError):
            srv.disk("/")

    def test_gateway_restricted_to_selected_interface(self):
        s = srv.gateway_unit("192.168.0.107", "192.168.0.0/24")
        self.assertIn("--listen 192.168.0.107", s)
        self.assertIn("User=ai-llama", s)
        self.assertNotIn("0.0.0.0", s)

    def test_plan_without_install(self):
        with patch.object(srv, "make_plan", return_value={"dry_run": True}) as pl:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = srv.main(["install", "--dry-run"])
        self.assertEqual(code, 0)
        pl.assert_called_once()
        self.assertIn("dry_run", out.getvalue())

    def test_model_generation_test_requires_approval_and_running_owned_service(self):
        cfg = {
            "model": "/srv/ai/models/example.gguf",
            "alias": "shared-ai",
            "port": 8082,
        }
        with (
            patch.object(srv, "managed_service_config", return_value=cfg) as owned,
            patch.object(srv, "run", return_value="inactive") as run,
            patch("ai_health.smoke_inference", return_value=0) as smoke,
        ):
            with self.assertRaisesRegex(ValueError, "--yes"):
                srv.main(["test-model"])
            owned.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "Start"):
                srv.main(["test-model", "--yes"])
            smoke.assert_not_called()
            run.return_value = "active"
            self.assertEqual(srv.main(["test-model", "--yes"]), 0)
            smoke.assert_called_once_with(
                "llamacpp", "shared-ai", port=8082, timeout=60
            )

    def test_catalog_exposes_lfs_hash_and_exact_bytes(self):
        from argparse import Namespace

        hardware = {
            "ram": {"available_bytes": 8 * 1024**3, "total_bytes": 16 * 1024**3},
            "cpu": {"logical_threads": 8, "supported_instruction_flags": ["avx2"]},
            "gpus": [],
            "system": {"os_id": "fixture", "architecture": "x86_64"},
        }
        with (
            patch.object(srv, "inventory", return_value=hardware),
            patch.object(srv, "disk", return_value={"free_gib": 20}),
            patch.object(srv, "host_support", return_value=({"manager": "apt"}, [])),
            patch.object(srv.server_storage, "devices", return_value=[]),
            patch.object(srv, "lan", return_value=None),
            patch.object(srv, "run", return_value=""),
        ):
            matches = srv.make_plan(
                Namespace(data_root="/srv/ai", backend="cpu", profile="auto")
            )["model_recommendations"]
        self.assertEqual(matches["reasoning"]["size_bytes"], 1117320800)
        self.assertEqual(
            matches["reasoning"]["sha256"],
            "1741e5b2d062b07acf048bf0d2c514dadf2a48f94e2b4aa0cfe069af3838ee2f",
        )
        self.assertEqual(next(iter(matches)), "compact_2026")
        self.assertEqual(sum(row.get("year") == 2026 for row in matches.values()), 3)
        self.assertNotIn("balanced", matches)
        self.assertNotIn("deepseek_v3_distill", matches)

    def test_model_fit_changes_with_cpu_ram_vram_and_selected_disk(self):
        hardware = {
            "system": {"architecture": "x86_64"},
            "cpu": {"logical_threads": 2, "supported_instruction_flags": []},
            "ram": {"available_bytes": 8 * 1024**3},
            "gpus": [
                {"name": "Test GPU", "vendor": "NVIDIA", "available_vram_mib": 4096}
            ],
        }
        storage = {"free_gib": 20}
        catalog, cpu, summary = srv.assess_models(
            hardware, storage, "cpu", None, gpu_ready=False
        )
        self.assertNotIn("balanced", cpu)
        self.assertNotIn("balanced_2026", cpu)
        self.assertEqual(summary["available_vram_mib"], 4096)
        self.assertTrue(catalog["deepseek_v3_distill"]["manual_only"])
        self.assertEqual(catalog["deepseek_v3_distill"]["size_bytes"], 2497281120)
        _, gpu, _ = srv.assess_models(hardware, storage, "cuda", None, gpu_ready=True)
        self.assertEqual(next(iter(gpu)), "balanced_2026")
        self.assertNotIn("deepseek_v3_distill", gpu)
        hardware["gpus"][0]["available_vram_mib"] = 1024
        limited, _, _ = srv.assess_models(hardware, storage, "cuda", 25, gpu_ready=True)
        self.assertTrue(
            any("offload" in message for message in limited["balanced"]["fit_issues"])
        )
        hardware["ram"]["available_bytes"] = 1024**3
        limited, ranked, _ = srv.assess_models(
            hardware, {"free_gib": 2}, "cpu", None, gpu_ready=False
        )
        self.assertFalse(ranked)
        self.assertTrue(
            any("RAM" in message for message in limited["general"]["fit_issues"])
        )
        self.assertTrue(
            any("disk" in message for message in limited["general"]["fit_issues"])
        )

    def test_install_requires_yes(self):
        with patch.object(srv, "installation") as install:
            self.assertEqual(srv.main(["install"]), 4)
            install.assert_not_called()

    def test_unrelated_unit_is_not_overwritten(self):
        from types import SimpleNamespace

        with patch.object(
            srv, "action", return_value=SimpleNamespace(returncode=0, stdout="foreign")
        ) as action:
            with self.assertRaisesRegex(RuntimeError, "unmanaged"):
                srv.install_owned(Path("/fixture/unit"), "ours")
            self.assertEqual(action.call_count, 1)

    def test_identical_config_idempotent(self):
        from types import SimpleNamespace

        with patch.object(
            srv, "action", return_value=SimpleNamespace(returncode=0, stdout="same")
        ) as action:
            self.assertFalse(srv.install_owned(Path("/fixture/unit"), "same"))
            self.assertEqual(action.call_count, 1)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = lan_proxy.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lan_proxy.handler_factory(
                b"secret" * 8, lan_proxy.ip_network("127.0.0.0/8")
            ),
        )
        cls.thread = threading.Thread(target=cls.service.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.service.shutdown()
        cls.service.server_close()
        cls.thread.join(timeout=2)

    def get(self, path, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return request.urlopen(
            request.Request(
                "http://127.0.0.1:%s%s" % (self.service.server_port, path),
                headers=headers,
            ),
            timeout=2,
        )

    def test_unauthenticated_denied(self):
        with self.assertRaises(error.HTTPError) as e:
            self.get("/v1/models")
        self.assertEqual(e.exception.code, 401)

    def test_invalid_token_denied(self):
        with self.assertRaises(error.HTTPError) as e:
            self.get("/v1/models", "wrong")
        self.assertEqual(e.exception.code, 401)

    def test_unsupported_api_denied(self):
        with self.assertRaises(error.HTTPError) as e:
            self.get("/api/delete", "secret" * 8)
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
