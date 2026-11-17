import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import setup_dashboard
import smart_backup


class SmartBackupTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enter_temp())
        self.source = self.work / "home"
        self.destination = self.work / "destination"
        self.destination.mkdir()
        self.project = self.source / "Documents" / "Project Sites"
        self.project.mkdir(parents=True)
        (self.source / "Documents" / "keep.txt").write_text("keep")
        (self.project / "app.py").write_text("application")
        (self.project / ".env").write_text("private fixture")
        (self.project / ".git").mkdir()
        (self.project / ".git" / "config").write_text("fixture")
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules" / "dep.js").write_text("unused")
        (self.project / "link").symlink_to(self.work / "outside")
        (self.work / "outside").write_text("outside the source")
        self.spec = {
            "source": str(self.source),
            "destination": str(self.destination),
            "jobs": [{"path": "Documents/Project Sites", "mode": "zip"}],
        }

    def enter_temp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary.name

    def execute(self, spec=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return smart_backup.execute(*smart_backup.prepare(spec or self.spec))

    @unittest.skipUnless(shutil.which("rsync"), "native rsync required")
    def test_split_copy_zip_verifies_and_preserves_selection(self):
        self.spec["jobs"].insert(0, {"path": "Documents", "mode": "copy"})
        copied = self.source / "Documents"
        (copied / ".secrets").write_text("sensitive")
        (copied / "vendor").mkdir()
        (copied / "vendor" / "ignored").touch()
        (copied / "empty").mkdir()
        (copied / "dir [*]").mkdir()
        (copied / "dir [*]" / "-file").write_text("literal")
        (copied / "dir [*]" / ".ignored").touch()
        (copied / "dir [*]" / "node_modules").mkdir()
        os.link(copied / "keep.txt", copied / "link")
        plan, _, _ = smart_backup.prepare(self.spec)
        self.assertEqual([], list(self.destination.iterdir()))
        self.assertEqual(["Project Sites"], plan["jobs"][0]["separate"])
        final = self.execute()
        paths = {entry.name for entry in (final / plan["jobs"][0]["output"]).iterdir()}
        self.assertEqual({"keep.txt", "empty", "link", "dir [*]"}, paths)
        snapshot = final / plan["jobs"][0]["output"]
        self.assertEqual(
            (snapshot / "keep.txt").stat().st_ino, (snapshot / "link").stat().st_ino
        )
        self.assertEqual("literal", (snapshot / "dir [*]" / "-file").read_text())
        self.assertEqual(
            ["-file"], [path.name for path in (snapshot / "dir [*]").iterdir()]
        )
        with zipfile.ZipFile(final / plan["jobs"][1]["output"]) as archive:
            self.assertEqual(
                {"Project Sites/", "Project Sites/app.py", "Project Sites/link"},
                set(archive.namelist()),
            )
            link = archive.getinfo("Project Sites/link")
            self.assertTrue(stat.S_ISLNK(link.external_attr >> 16))
            self.assertEqual(str(self.work / "outside"), archive.read(link).decode())
            self.assertIsNone(archive.testzip())
        self.assertTrue((final / "manifest.json").is_file())

    def test_standard_home_preset_only_selects_existing_folders(self):
        self.project.rename(self.source / "Documents" / "Project-Sites")
        (self.source / "Code").mkdir()
        (self.source / "Downloads").symlink_to(self.project.parent)
        self.assertEqual(
            [
                {"path": "Documents", "mode": "copy"},
                {"path": "Code", "mode": "copy"},
                {"path": "Documents/Project-Sites", "mode": "zip"},
            ],
            smart_backup.browse(str(self.source))["home_jobs"],
        )

    @unittest.skipUnless(shutil.which("rsync"), "native rsync required")
    def test_root_files_only_and_skipped_subtree(self):
        (self.source / "note.txt").write_text("keep")
        (self.source / ".private").touch()
        (self.source / "shortcut").symlink_to("note.txt")
        self.spec.update(
            root_files=True,
            jobs=[
                {"path": "Documents", "mode": "copy"},
                {"path": "Documents/Project Sites", "mode": "skip"},
            ],
        )
        final = self.execute()
        first, second = json.loads((final / "manifest.json").read_text())["jobs"]
        self.assertEqual("root-files", first["scope"])
        self.assertEqual(
            {"note.txt", "shortcut"},
            {item.name for item in (final / first["output"]).iterdir()},
        )
        self.assertEqual(["Project Sites"], second["excluded_folders"])
        self.assertEqual(
            ["keep.txt"], [item.name for item in (final / second["output"]).iterdir()]
        )

    def test_root_files_and_entire_source_do_not_duplicate_visible_files(self):
        (self.source / "note.txt").touch()
        (self.source / ".private").touch()
        self.spec.update(
            root_files=True, jobs=[{"path": ".", "mode": "zip", "hidden": True}]
        )
        _, inventory, _ = smart_backup.prepare(self.spec)
        root_files, entire_source = [
            {str(path) for path, _ in entries} for _, entries in inventory
        ]
        self.assertIn("note.txt", root_files)
        self.assertNotIn("note.txt", entire_source)
        self.assertIn(".private", entire_source)

    def test_hidden_and_exclusion_override(self):
        self.spec.update(hidden=False, excludes=["node_modules"], verification="quick")
        self.spec["jobs"][0]["hidden"] = True
        final = self.execute()
        [archive_path] = (final / "zip").iterdir()
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("Project Sites/.env", archive.namelist())
            self.assertIn("Project Sites/.git/config", archive.namelist())
            self.assertNotIn("Project Sites/node_modules/dep.js", archive.namelist())

    def test_refuses_destination_inside_selected_folder(self):
        self.spec["destination"] = str(self.project)
        with self.assertRaisesRegex(ValueError, "destination is inside"):
            smart_backup.prepare(self.spec)

    def test_target_change_and_review_are_checked_before_writes(self):
        plan = smart_backup.prepare(self.spec)[0]
        self.destination.rename(self.work / "disconnected")
        self.destination.mkdir()
        with contextlib.redirect_stderr(io.StringIO()) as error:
            status = smart_backup.main(
                [
                    "run",
                    "--spec",
                    json.dumps(self.spec),
                    "--expected-plan",
                    plan["revision"],
                    "--yes",
                ]
            )
        self.assertEqual(1, status)
        self.assertIn("changed after preview", error.getvalue())
        self.assertEqual([], list(self.destination.iterdir()))

    def test_backup_failure_is_not_published(self):
        with patch.object(
            smart_backup, "zip_tree", side_effect=OSError("drive disconnected")
        ):
            with (
                self.assertRaisesRegex(OSError, "disconnected"),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.execute()
        self.assertEqual([], list(self.destination.glob("smart-backup-*")))
        self.assertEqual(
            1, len(list(self.destination.glob(".smart-backup-incomplete-*")))
        )

    def test_symlink_source_and_malformed_filters_are_refused(self):
        link = self.source / "shortcut"
        link.symlink_to(self.project, target_is_directory=True)
        self.spec["jobs"][0]["path"] = "shortcut"
        with self.assertRaisesRegex(ValueError, "without symbolic links"):
            smart_backup.prepare(self.spec)
        self.spec["jobs"][0]["path"] = "."
        self.spec["excludes"] = ["Documents/.git"]
        with self.assertRaisesRegex(ValueError, "individual directory names"):
            smart_backup.prepare(self.spec)

    def test_external_inherits_usb_parent_and_excludes_fixed_devices(self):
        payload = {
            "blockdevices": [
                {
                    "type": "disk",
                    "tran": "usb",
                    "children": [
                        {
                            "type": "part",
                            "mountpoints": [
                                str(self.destination),
                                str(self.work / "unmounted"),
                            ],
                        }
                    ],
                },
                {"type": "disk", "tran": "nvme", "mountpoints": [str(self.source)]},
            ],
        }
        (self.work / "unmounted").mkdir()
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload))
        with (
            patch.object(smart_backup.shutil, "which", return_value="/usr/bin/lsblk"),
            patch.object(smart_backup.subprocess, "run", return_value=result),
            patch.object(
                smart_backup,
                "mounted_paths",
                return_value={self.source, self.destination},
            ),
        ):
            self.assertEqual(
                [str(self.destination)], smart_backup.external_destinations()
            )

    def test_missing_lsblk_leaves_manual_destination_available(self):
        with patch.object(smart_backup.shutil, "which", return_value=None):
            self.assertEqual([], smart_backup.external_destinations())
            plan, _, _ = smart_backup.prepare(self.spec)
            self.assertEqual(str(self.destination), plan["destination"])

    def test_dashboard_requires_approval_and_a_review_revision(self):
        payload = {"action": "backup-run", "spec": self.spec}
        builder = setup_dashboard.preview_arguments
        self.assertEqual(
            ["smart-backup", "plan"], builder(payload, aur_ready=False)[:2]
        )
        with self.assertRaisesRegex(ValueError, "Confirm"):
            builder(payload, aur_ready=False, execute=True)
        with self.assertRaisesRegex(ValueError, "Preview"):
            builder({**payload, "confirmed": True}, aur_ready=False, execute=True)
        args = builder(
            {**payload, "confirmed": True, "revision": "a" * 64},
            aur_ready=False,
            execute=True,
        )
        self.assertEqual(["smart-backup", "run"], args[:2])
        self.assertEqual("--yes", args[-1])
