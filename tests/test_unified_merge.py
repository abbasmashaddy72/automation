import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "lib"), str(ROOT / "ai")]
import automation
import cache
import gguf_context
import package_replay
import zed_settings


class MergeContracts(unittest.TestCase):
    def test_zed_endpoint_summary_limits_probes_to_safe_urls(self):
        settings = {
            "language_models": {
                "llama.cpp": {"api_url": "http://127.0.0.1:8080/v1"},
                "remote": {"api_url": "http://192.168.1.30:8080"},
                "authenticated": {"api_url": "https://user:private@example.org"},
                "query": {"api_url": "http://127.0.0.1:8080/?token=private"},
            },
            "agent": {"default_model": {"provider": "llama.cpp", "model": "sample"}},
        }
        rows = zed_settings.connection_summary(settings)
        self.assertNotIn("private", json.dumps(rows))
        self.assertEqual([row["can_test"] for row in rows], [True, False, False])
        self.assertEqual(rows[0]["model"], "sample")

    def test_zed_override_replace_preview_and_restore(self):
        from argparse import Namespace
        from unittest.mock import patch

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            base = Path(directory)
            target = base / "zed/settings.json"
            target.parent.mkdir()
            original = (
                b'{"theme":"Light","telemetry":{"diagnostics":true,"metrics":true}}'
            )
            target.write_bytes(original)
            profile = base / "profile.json"
            profile.write_text('{"telemetry":{"metrics":false}}')
            state = str(base / "state")
            args = Namespace(
                action="override", value=str(profile), dry_run=True, current_sha256=None
            )
            self.assertEqual(
                zed_settings.main(args, lambda *_: True, root=ROOT, state=state), 0
            )
            self.assertEqual(target.read_bytes(), original)
            args.dry_run = False
            self.assertEqual(
                zed_settings.main(args, lambda *_: True, root=ROOT, state=state), 0
            )
            self.assertEqual(
                json.loads(target.read_text())["telemetry"],
                {"diagnostics": True, "metrics": False},
            )
            args.action = "replace"
            self.assertEqual(
                zed_settings.main(args, lambda *_: True, root=ROOT, state=state), 0
            )
            self.assertEqual(
                json.loads(target.read_text()), {"telemetry": {"metrics": False}}
            )
            receipt = next(
                path
                for path in (base / "state").glob("zed-*.json")
                if json.loads(path.read_text())["expected_sha256"]
                == zed_settings.digest(target.read_bytes())
            )
            args.action, args.value = "restore", receipt.name
            self.assertEqual(
                zed_settings.main(args, lambda *_: True, root=ROOT, state=state), 0
            )
            self.assertEqual(json.loads(target.read_text())["theme"], "Light")

    def test_zed_jsonc_nested_merge_conflict_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "zed/settings.json"
            target.parent.mkdir()
            original = b'// user comment\n{"terminal":{"font_size":18,},"language_models":{"llama.cpp":{"api_url":"http://127.0.0.1:8080"}},}\n'
            target.write_bytes(original)
            profile = base / "profile.json"
            profile.write_text(
                '{"terminal":{"font_size":14,"dock":"bottom"},"base_keymap":"VSCode"}'
            )
            env = {
                **os.environ,
                "XDG_CONFIG_HOME": td,
                "AUTOMATION_STATE_DIR": str(base / "state"),
            }

            def cli(*args):
                return subprocess.run(
                    ["bash", str(ROOT / "setup.sh"), "zed", *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=25,
                )

            self.assertEqual(
                cli("apply", str(profile), "--dry-run", "--yes").returncode, 0
            )
            self.assertFalse((base / "state").exists())
            self.assertEqual(target.read_bytes(), original)
            result = cli("apply", str(profile), "--yes")
            self.assertEqual(result.returncode, 0, result.stderr)
            (backup,) = list((base / "state").glob("zed-*.json"))
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            value = json.loads(target.read_text())
            self.assertEqual(value["terminal"], {"font_size": 18, "dock": "bottom"})
            self.assertEqual(
                value["language_models"]["llama.cpp"]["api_url"],
                "http://127.0.0.1:8080",
            )
            changed = target.read_bytes()
            target.write_bytes(changed + b"\n")
            self.assertNotEqual(cli("restore", backup.name, "--yes").returncode, 0)
            target.write_bytes(changed)
            self.assertEqual(cli("restore", backup.name, "--yes").returncode, 0)
            self.assertEqual(target.read_bytes(), original)

    def test_replay_exact_names_and_refuse_foreign_or_non_native_plan(self):
        host = {
            "id": "ubuntu",
            "family": "debian",
            "arch": "x86_64",
            "manager": "apt-get",
        }
        row = {
            "name": "editor",
            "actual": "code",
            "status": "available",
            "source": "apt-get",
        }
        value = {
            "schema": 1,
            "type": "automation-plan",
            "host": host,
            "packages": [row],
        }
        self.assertEqual(package_replay.selection(value, host), {"editor": "code"})
        with self.assertRaises(ValueError):
            package_replay.selection(value, {**host, "id": "debian"})
        for actual, source in (("3;bad", "apt-get"), ("code", "flatpak")):
            with self.assertRaises(ValueError):
                package_replay.selection(
                    {
                        **value,
                        "packages": [{**row, "actual": actual, "source": source}],
                    },
                    host,
                )

    def test_cachyos_export_records_native_python_id(self):
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.json"
            info = dict(
                id="cachyos",
                family="arch",
                manager="pacman",
                arch="x86_64",
                desktop=False,
            )
            with (
                patch.object(automation, "platform_info", return_value=info),
                patch.object(automation, "installed", return_value=True),
                patch.object(automation, "_query", return_value=None),
            ):
                self.assertEqual(
                    automation.main(
                        [
                            "packages",
                            "export",
                            "--select",
                            "python3",
                            "--output",
                            str(plan),
                        ]
                    ),
                    0,
                )
            value = json.loads(plan.read_text())
            self.assertEqual(
                package_replay.selection(value, info), {"python3": "python"}
            )

    def test_expired_cache_cleanup_preserves_changed_and_unowned_entries(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self.assertTrue(cache.put(["test"], {}, folder=folder))
            (entry,) = list(folder.glob("*.json"))
            unrelated = folder / "personal.json"
            unrelated.write_text("{}")
            os.utime(entry, (1, 1))
            os.utime(unrelated, (1, 1))
            with patch.object(cache, "directory", return_value=folder):
                reviewed = cache.expired()
                entry.write_text("{}")
                self.assertEqual(cache.expire(reviewed), 0)
                self.assertEqual(cache.expire(cache.expired()), 0)
                self.assertTrue(cache.put(["test"], {}, folder=folder))
                os.utime(entry, (1, 1))
                self.assertEqual(cache.expire(cache.expired()), 1)
            self.assertTrue(unrelated.exists())

    def test_gguf_context_uses_model_architecture_and_rejects_truncation(self):
        def string(v):
            return struct.pack("<Q", len(v)) + v

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.gguf"
            metadata = (
                string(b"other.context_length")
                + struct.pack("<II", 4, 1234)
                + string(b"general.architecture")
                + struct.pack("<I", 8)
                + string(b"llama")
                + string(b"llama.context_length")
                + struct.pack("<II", 4, 8192)
            )
            raw = b"GGUF" + struct.pack("<IQQ", 3, 0, 3) + metadata
            path.write_bytes(raw)
            self.assertEqual(gguf_context.trained_context_from_gguf(path), 8192)
            path.write_bytes(raw[:-1])
            with self.assertRaises(gguf_context.InvalidGGUF):
                gguf_context.trained_context_from_gguf(path)
