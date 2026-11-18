"""Profile migration, export boundaries and reviewed restoration."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import automation
import package_mappings
import system_profile
import workflows


class SystemProfileTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        base = Path(workspace.name)
        self.root = base / "checkout"
        self.state = str(base / "state")
        (self.root / "config").mkdir(parents=True)
        self.zed = base / "editor/zed/settings.json"
        environment = patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(self.zed.parent.parent)}
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.info = {
            "id": "debian",
            "family": "debian",
            "arch": "x86_64",
            "manager": "apt-get",
        }

    def profile(self, **sections):
        return {
            "schema": 2,
            "type": "automation-profile",
            "application_version": workflows.APPLICATION_VERSION,
            "sections": sections,
        }

    def restore(self, profile, **kwargs):
        return system_profile.restore(
            self.root,
            self.state,
            self.info,
            profile,
            automation.config_file,
            automation.validate_settings,
            **kwargs,
        )

    def zed_fixture(self):
        self.zed.parent.mkdir(parents=True)
        original = b'{ // comment\n "tab_size": 2, "custom_setting": 7, "language_models": {"example": {"api_key":"private-token"}},\n}\n'
        self.zed.write_bytes(original)
        return original

    def test_export_excludes_credentials_and_can_select_sections(self):
        self.zed_fixture()
        result = system_profile.export_profile(
            self.root,
            self.state,
            ["zed", "setup"],
            {
                "selected": ["curl"],
                "aiSavedAt": 123,
                "ai": {"port": 8080},
                "remote": {"host": "192.168.1.5"},
            },
            automation.config_file,
            automation.validate_settings,
        )
        self.assertEqual(set(result["profile"]["sections"]), {"zed", "setup"})
        self.assertEqual(result["profile"]["sections"]["zed"], {"tab_size": 2})
        self.assertEqual(
            result["profile"]["application_version"], workflows.APPLICATION_VERSION
        )
        self.assertNotIn("private-token", json.dumps(result))
        self.assertNotIn("aiSavedAt", json.dumps(result))
        self.assertTrue(result["notices"])
        self.assertFalse(Path(self.state).exists())

    def test_export_can_roundtrip_existing_browser_draft_with_retired_fields(self):
        saved = {
            "selected": ["curl"],
            "ai": {
                "shell": "fish",
                "port": 8081,
                "stage": False,
                "api_key": "secret-fixture",
            },
            "remote": {
                "host": "ai.lan",
                "port": "invalid",
                "password": "secret-fixture",
            },
        }
        exported = system_profile.export_profile(
            self.root,
            self.state,
            ["setup"],
            saved,
            automation.config_file,
            automation.validate_settings,
        )
        expected = {
            "selected": ["curl"],
            "ai": {"port": 8081, "stage": False},
            "remote": {"host": "ai.lan"},
        }
        document = exported["profile"]
        review = self.restore(system_profile.parse_document(json.dumps(document)))
        self.assertEqual(review["setup"], expected)
        self.assertIn("skipped outdated or unsupported", exported["notices"][0])
        self.assertNotIn("secret-fixture", json.dumps(exported))
        self.assertEqual(saved["ai"]["shell"], "fish")
        document["sections"]["setup"]["ai"]["shell"] = "fish"
        review = self.restore(document)
        self.assertIn("retired Local AI shell preference", review["notices"][0])
        result = self.restore(document, revision=review["revision"])
        self.assertEqual(result["setup"], expected)
        self.assertIn("shell", document["sections"]["setup"]["ai"])
        document["sections"]["setup"]["ai"]["unknown"] = True
        with self.assertRaisesRegex(ValueError, "Unsupported fields in setup.ai"):
            self.restore(document)

    def test_retired_shell_only_import_leaves_existing_ai_settings_outside_review(self):
        result = self.restore(self.profile(setup={"ai": {"shell": False}}))
        self.assertNotIn("ai", result["setup"])
        self.assertIn("retired Local AI shell preference", result["notices"][0])

    def test_review_and_apply_selected_settings_preserves_unrelated_values(self):
        before = self.zed_fixture()
        env = self.root / ".env"
        env.write_text("# preserve\nAUTOMATION_LERD=true\n")
        incoming = self.profile(
            toolkit={"AUTOMATION_PROJECT_SITES_DIR": "/tmp/new-projects"},
            setup={"selected": ["curl", "curl"], "ai": {"port": 8080}},
            mappings={
                package_mappings.platform_key(self.info): {
                    "browser": {
                        "distribution": "debian",
                        "architecture": "x86_64",
                        "manager": "apt-get",
                        "source": "apt-get",
                        "actual": "firefox-esr",
                    },
                }
            },
            zed={"tab_size": 4, "telemetry": {"metrics": False}},
        )
        review = self.restore(incoming)
        self.assertEqual(review["setup"]["selected"], ["curl"])
        self.assertEqual(self.zed.read_bytes(), before)
        self.assertFalse(Path(self.state).exists())
        result = self.restore(incoming, revision=review["revision"])
        self.assertEqual(set(result["backups"]), {"toolkit", "zed", "mappings"})
        for backup in result["backups"].values():
            self.assertEqual((Path(self.state) / backup).stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            package_mappings.choices(self.info, self.state), {"browser": "firefox-esr"}
        )
        self.assertIn("# preserve\nAUTOMATION_LERD=true\n", env.read_text())
        self.assertIn("AUTOMATION_PROJECT_SITES_DIR=/tmp/new-projects", env.read_text())
        self.assertFalse((self.root / "new-projects").exists())
        edited = json.loads(self.zed.read_bytes())
        self.assertEqual(edited["tab_size"], 4)
        self.assertEqual(
            edited["language_models"]["example"]["api_key"], "private-token"
        )
        self.assertFalse(any(row["changed"] for row in self.restore(incoming)["files"]))

    def test_strict_profile_json(self):
        for text, message in (
            ('{\n  "sections": }', "line 2, column 15"),
            ('{"schema": 2, "schema": 1}', "Duplicate JSON field"),
            ('{"value": NaN}', "must be finite"),
            ('{"value": 1e999}', "must be finite"),
            (r'{"value": "\ud800"}', "invalid Unicode"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                system_profile.parse_document(text)
        self.assertEqual(
            system_profile.parse_document('{"number":2.5}'), {"number": 2.5}
        )
        with self.assertRaisesRegex(ValueError, "zed.tab_size"):
            self.restore(self.profile(zed={"tab_size": 2.5}))

    def test_stale_review_and_unsupported_fields_leave_current_files_untouched(self):
        before = self.zed_fixture()
        profile = self.profile(zed={"vim_mode": True})
        review = self.restore(profile)
        self.zed.write_bytes(before + b" ")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.restore(profile, revision=review["revision"])
        with self.assertRaisesRegex(ValueError, "Unsupported profile schema"):
            self.restore({**profile, "schema": 9})
        with self.assertRaisesRegex(ValueError, "Unsupported fields in zed"):
            self.restore(self.profile(zed={"unrecognized_setting": True}))
        with self.assertRaisesRegex(ValueError, "api_url"):
            self.restore(
                self.profile(
                    zed={
                        "language_models": {
                            "llama.cpp": {
                                "api_url": "https://example.test/v1?secret=token",
                            }
                        }
                    }
                )
            )
        self.assertEqual(self.zed.read_bytes(), before + b" ")
        self.assertFalse(Path(self.state).exists())

    def test_unversioned_cli_profile_migrates(self):
        old = {
            "schema": 1,
            "type": "automation-profile",
            "settings": {
                "AUTOMATION_PROFILE": "minimal",
                "AUTOMATION_SELECTED_PACKAGES": "curl,lerd",
            },
        }
        review = self.restore(old)
        self.assertIn("migrated", review["notices"][0])
        self.assertEqual(review["setup"]["selected"], ["curl"])
        result = self.restore(old, revision=review["revision"])
        self.assertIn(
            "AUTOMATION_SELECTED_PACKAGES=curl,lerd", (self.root / ".env").read_text()
        )

        with (
            patch.object(automation, "ROOT", self.root),
            patch.dict(os.environ, {"AUTOMATION_STATE_DIR": self.state}),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                automation.main(
                    ["config", "restore", result["backups"]["toolkit"], "--yes"]
                ),
                0,
            )
        self.assertNotIn(
            "AUTOMATION_SELECTED_PACKAGES", (self.root / ".env").read_text()
        )

    def test_later_write_failure_rolls_back_prior_configuration(self):
        before = self.zed_fixture()
        env = self.root / ".env"
        env.write_text("AUTOMATION_LERD=true\n")
        incoming = self.profile(
            toolkit={"AUTOMATION_LERD": "false"}, zed={"tab_size": 4}
        )
        review = self.restore(incoming)
        original_atomic = system_profile.filesystem.atomic

        def write(target, content):
            if target == self.zed:
                raise OSError("simulated failure")
            original_atomic(target, content)

        with patch.object(system_profile.filesystem, "atomic", side_effect=write):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                self.restore(incoming, revision=review["revision"])
        self.assertEqual(env.read_text(), "AUTOMATION_LERD=true\n")
        self.assertEqual(self.zed.read_bytes(), before)
