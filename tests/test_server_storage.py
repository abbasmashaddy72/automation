"""Exercise storage selection and service start checks without touching disks."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
import dedicated_server
import llama_launcher
import server_storage

UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SIZE = 30 * 1024**3


def volume(path="/dev/sdb1", **changes):
    return dict(
        dict(
            path=path,
            type="part",
            fstype="ext4",
            uuid=UUID,
            mountpoints=[None],
            ro=False,
            rm=False,
            size=SIZE,
        ),
        **changes,
    )


def drive(path, *parts, **changes):
    return dict(
        volume(path, type="disk", fstype=None, uuid=None, children=list(parts)),
        **changes,
    )


class ServerStorage(unittest.TestCase):
    def test_unused_filesystem_selection_excludes_entire_active_disk_and_duplicate_ids(
        self,
    ):
        active = drive(
            "/dev/sda",
            volume("/dev/sda1", mountpoints=["/"]),
            volume("/dev/sda2", uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        )
        external = drive("/dev/sdc", volume("/dev/sdc1"), rm=True)
        spare = drive("/dev/sdb", volume())
        with patch.object(
            server_storage,
            "run",
            return_value=json.dumps({"blockdevices": [active, spare, external]}),
        ):
            self.assertEqual(server_storage.devices(), [])
        with patch.object(
            server_storage, "run", return_value=json.dumps({"blockdevices": [spare]})
        ):
            self.assertEqual(server_storage.selected(UUID)["device"], "/dev/sdb1")

    def test_local_storage_can_be_planned_before_directory_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "models-home"
            mounts = {
                "filesystems": [
                    dict(
                        target="/",
                        source="/dev/sda1",
                        fstype="ext4",
                        uuid=UUID,
                        options="rw",
                    )
                ]
            }
            with (
                patch.object(server_storage, "run", return_value=json.dumps(mounts)),
                patch.object(
                    server_storage.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=SIZE),
                ),
            ):
                result = dedicated_server.disk(target)
            self.assertEqual(result["mount"], "/")
            self.assertFalse(result["ready"])
            self.assertFalse(target.exists())

    def test_existing_dedicated_install_refuses_fallback_when_mount_disappears(self):
        config = {"data_root": "/srv/ai"}
        current = {"directory": "/srv/ai", "mount": "/", "uuid": UUID}
        with self.assertRaisesRegex(RuntimeError, "Restore the configured"):
            dedicated_server.check_installed_storage(config, current)

    def test_persistent_mount_refuses_a_user_writable_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            parent.chmod(0o777)
            with self.assertRaisesRegex(RuntimeError, "root-owned"):
                server_storage.check_mount_path(parent / "models")

    def test_launcher_uses_root_storage_and_refuses_wrong_selected_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "test.gguf"
            model.write_bytes(b"GGUFfixture")
            config = dict(
                data_root=directory,
                storage_mount="/",
                model=str(model),
                binary=sys.executable,
                context=2048,
                threads=2,
                batch=256,
                ubatch=64,
                parallel=1,
                port=8080,
            )
            with patch.object(
                llama_launcher.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="/"),
            ):
                self.assertIn(str(model), llama_launcher.command(config))
            with patch.object(
                llama_launcher.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=directory),
            ):
                with self.assertRaisesRegex(ValueError, "UUID"):
                    llama_launcher.command(config)
            config.update(storage_mount=directory, storage_uuid=UUID)
            with patch.object(
                llama_launcher.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=directory + " other"),
            ):
                with self.assertRaisesRegex(ValueError, "UUID"):
                    llama_launcher.command(config)

    def test_mount_reuse_checks_exact_persisted_unit_and_uuid(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "models"
            root.mkdir()
            unit = parent / "models.mount"
            marker = "# toolkit fixture"
            unit.write_text(
                f"{marker}\n[Mount]\nWhat=/dev/disk/by-uuid/{UUID}\n"
                f"Where={root}\nType=ext4\nOptions=rw,nodev,nosuid,noexec\nTimeoutSec=30\n"
            )
            from unittest.mock import Mock

            mutate = Mock()
            with (
                patch.object(server_storage, "SYSTEM_UNITS", parent),
                patch.object(
                    server_storage, "run", side_effect=["models.mount", str(unit)]
                ),
                patch.object(server_storage, "is_mount", return_value=True),
                patch.object(
                    server_storage,
                    "inspect",
                    return_value={"mount": str(root), "uuid": UUID},
                ),
            ):
                self.assertEqual(
                    server_storage.mount_selected(root, UUID, mutate, marker)["uuid"],
                    UUID,
                )
            mutate.assert_not_called()
            unit.write_text("foreign unit")
            with (
                patch.object(server_storage, "SYSTEM_UNITS", parent),
                patch.object(
                    server_storage, "run", side_effect=["models.mount", str(unit)]
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    server_storage.mount_selected(root, UUID, mutate, marker)
            mutate.assert_not_called()

    def test_selected_preformatted_volume_creates_a_persistent_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "models"
            unit = parent / "models.mount"
            choice = {
                "device": str(parent / "disk"),
                "uuid": UUID,
                "filesystem": "ext4",
                "bytes": SIZE,
            }
            (parent / UUID).symlink_to(parent / "disk")
            (parent / "disk").touch()
            commands = []

            def execute(argv, **kwargs):
                commands.append(argv)
                if argv[0] == "findmnt":
                    return SimpleNamespace(returncode=1, stdout="", stderr="")
                if argv[0] == "mkdir":
                    root.mkdir()
                elif argv[0] == "install":
                    Path(argv[-1]).write_bytes(Path(argv[-2]).read_bytes())
                elif argv[0] == "ln":
                    Path(argv[-1]).hardlink_to(argv[-2])
                elif argv[0] == "rm":
                    Path(argv[-1]).unlink()

            with (
                patch.object(server_storage, "SYSTEM_UNITS", parent),
                patch.object(server_storage, "UUID_DEVICES", parent),
                patch.object(server_storage, "check_mount_path"),
                patch.object(server_storage, "run", side_effect=["models.mount", ""]),
                patch.object(server_storage, "is_mount", return_value=False),
                patch.object(server_storage, "selected", return_value=choice),
                patch.object(server_storage.stat, "S_ISBLK", return_value=True),
                patch.object(
                    server_storage,
                    "inspect",
                    return_value={"mount": str(root), "uuid": UUID},
                ),
            ):
                server_storage.mount_selected(root, UUID, execute, "# fixture")
            self.assertIn(f"What=/dev/disk/by-uuid/{UUID}", unit.read_text())
            self.assertIn(f"Where={root}", unit.read_text())
            self.assertEqual(
                commands[-2:],
                [
                    ["systemctl", "daemon-reload"],
                    ["systemctl", "start", "models.mount"],
                ],
            )

    def test_dependency_install_delegates_to_existing_native_preflight(self):
        with patch.object(dedicated_server, "action") as action:
            dedicated_server.dependencies("cpu")
        self.assertIn("--with-ai-build", action.call_args.args[0])
        self.assertIn("--with-ai-server", action.call_args.args[0])
        self.assertNotIn("apt-get", action.call_args.args[0])
