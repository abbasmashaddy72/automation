"""Legacy replacement regressions, using disposable homes and native local parsers."""

from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "lib"), str(ROOT / "ai")]
import checklist
import developer
import models


class MigrationFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / "state"
        env = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_STATE_HOME": str(self.home / "xdg-state"),
                "XDG_CONFIG_HOME": str(self.home / "config"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.out = io.StringIO()
        redirect = contextlib.redirect_stdout(self.out)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.args = Namespace(
            action="ssh",
            identity_file=str(self.home / ".ssh/selected"),
            ssh_host="code-host",
            hostname="github.com",
            ssh_user="git",
            dry_run=False,
            yes=True,
            developer_state=str(self.state),
            current_sha256=None,
            value=None,
            banner="none",
        )

    def identity(self):
        key = Path(self.args.identity_file)
        key.parent.mkdir(mode=0o700, exist_ok=True)
        key.write_text("private-fixture")
        key.chmod(0o600)
        return key

    def test_separate_ssh_configuration_real_parser_and_restore(self):
        if not shutil.which("ssh"):
            self.skipTest("OpenSSH is not installed")
        self.identity()
        original = self.home / ".ssh/config"
        original.write_text("Host *\n User unchanged\n")
        original.chmod(0o600)
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        target = developer.target("ssh")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        cp = subprocess.run(
            ["ssh", "-G", "-F", str(target), "code-host"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("hostname github.com", cp.stdout)
        self.assertIn("user git", cp.stdout)
        self.assertIn("identitiesonly yes", cp.stdout)
        self.assertIn("stricthostkeychecking true", cp.stdout)
        self.assertEqual(original.read_text(), "Host *\n User unchanged\n")
        receipt = next((self.state / "developer").glob("*.json"))
        self.args.action = "restore"
        self.args.value = receipt.name
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        self.assertFalse(target.exists())
        self.assertTrue(original.exists())

    def test_ssh_idempotency_and_replacement_review(self):
        self.identity()
        developer.main(self.args, lambda *_: True)
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        target = developer.target("ssh")
        target.write_text(target.read_text() + "# later edit\n")
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        self.args.current_sha256 = developer.sha(target.read_bytes())
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)

    def test_ssh_dry_run_and_refusal(self):
        self.identity()
        self.args.dry_run = True
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        self.assertFalse(self.state.exists())
        self.assertFalse(developer.target("ssh").exists())
        self.args.dry_run = False
        self.assertEqual(developer.main(self.args, lambda *_: False), 4)
        self.assertFalse(self.state.exists())

    def test_ssh_injection_and_permissions_rejected(self):
        key = self.identity()
        for field, value in [
            ("ssh_host", "*"),
            ("hostname", "example\nProxyCommand evil"),
            ("ssh_user", "-oProxyCommand=evil"),
        ]:
            old = getattr(self.args, field)
            setattr(self.args, field, value)
            with self.assertRaises(ValueError):
                developer.main(self.args, lambda *_: True)
            setattr(self.args, field, old)
        key.chmod(0o644)
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        key.chmod(0o600)
        link = key.with_name("linked")
        link.symlink_to(key)
        self.args.identity_file = str(link)
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        self.assertFalse(self.state.exists())

    def test_ssh_generation_never_overwrites_or_runs_unattended(self):
        key = self.identity()
        self.args.action = "ssh-generate"
        with patch("ssh_ops.subprocess.run") as run, self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        run.assert_not_called()
        self.assertEqual(key.read_text(), "private-fixture")
        key.unlink()
        with (
            patch("ssh_ops.shutil.which", return_value="/usr/bin/ssh-keygen"),
            patch("ssh_ops.sys.stdin.isatty", return_value=False),
            self.assertRaises(ValueError),
        ):
            developer.main(self.args, lambda *_: True)
        self.assertFalse(key.exists())

    def test_ssh_generation_native_prompt_and_atomic_publication(self):
        self.args.action = "ssh-generate"

        def generate(cmd, **kwargs):
            self.assertNotIn("-N", cmd)
            self.assertNotIn("-P", cmd)
            path = Path(cmd[-1])
            path.write_text("generated-private")
            path.chmod(0o600)
            path.with_name(path.name + ".pub").write_text("ssh-ed25519 public-fixture")
            return Namespace(returncode=0)

        with (
            patch("ssh_ops.shutil.which", return_value="/usr/bin/ssh-keygen"),
            patch("ssh_ops.sys.stdin.isatty", return_value=True),
            patch("ssh_ops.subprocess.run", side_effect=generate),
        ):
            self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        key = Path(self.args.identity_file)
        self.assertEqual(key.read_text(), "generated-private")
        self.assertEqual(key.stat().st_nlink, 1)
        self.assertFalse(list(key.parent.glob(".automation-ssh-*")))
        self.assertNotIn("generated-private", self.out.getvalue())

    def test_ssh_generation_publication_conflict_preserves_concurrent_key(self):
        self.args.action = "ssh-generate"
        key = Path(self.args.identity_file)

        def generate(cmd, **kwargs):
            path = Path(cmd[-1])
            path.write_text("generated")
            path.chmod(0o600)
            path.with_name(path.name + ".pub").write_text("public")
            key.with_name(key.name + ".pub").write_text("concurrent-public")
            return Namespace(returncode=0)

        with (
            patch("ssh_ops.shutil.which", return_value="/usr/bin/ssh-keygen"),
            patch("ssh_ops.sys.stdin.isatty", return_value=True),
            patch("ssh_ops.subprocess.run", side_effect=generate),
            self.assertRaises(FileExistsError),
        ):
            developer.main(self.args, lambda *_: True)
        self.assertFalse(key.exists())
        self.assertEqual(
            key.with_name(key.name + ".pub").read_text(), "concurrent-public"
        )

    def test_agent_is_explicit_existing_and_scoped(self):
        key = self.identity()
        self.args.action = "ssh-add"
        with (
            patch.dict(os.environ, {"SSH_AUTH_SOCK": ""}),
            self.assertRaises(ValueError),
        ):
            developer.main(self.args, lambda *_: True)
        with (
            patch.dict(os.environ, {"SSH_AUTH_SOCK": "fixture-agent"}),
            patch("ssh_ops.shutil.which", return_value="/usr/bin/ssh-add"),
            patch(
                "ssh_ops.subprocess.run", return_value=Namespace(returncode=0)
            ) as run,
        ):
            self.assertEqual(developer.main(self.args, lambda *_: False), 4)
            run.assert_not_called()
            self.assertEqual(developer.main(self.args, lambda *_: True), 0)
            run.assert_called_once_with(["ssh-add", str(key)], check=False)

    def test_legacy_git_backup_import_does_not_overwrite_and_conflicts_on_restore(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        current = self.home / ".gitconfig"
        current.write_text("[user]\n name = Current\n")
        original = self.home / "legacy.gitconfig"
        original.write_text("[user]\n name = Previous\n")
        original.chmod(0o600)
        self.args.action = "import-git-backup"
        self.args.value = str(original)
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        self.args.current_sha256 = developer.sha(current.read_bytes())
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        self.assertIn("Current", current.read_text())
        receipt = next((self.state / "developer").glob("*.json"))
        self.args.action = "restore"
        self.args.value = receipt.name
        current.write_text("[user]\n name = Later\n")
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        current.write_text("[user]\n name = Current\n")
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        self.assertEqual(current.read_bytes(), original.read_bytes())
        self.assertTrue(original.exists())

    def test_backup_import_rejects_executable_data_and_readonly_writes_nothing(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        source = self.home / "backup"
        source.write_text("$(touch /tmp/evil)\n")
        source.chmod(0o600)
        self.args.action = "import-git-backup"
        self.args.value = str(source)
        self.args.current_sha256 = developer.sha(b"")
        with self.assertRaises(ValueError):
            developer.main(self.args, lambda *_: True)
        source.write_text("[user]\n name = Previous\n")
        self.args.dry_run = True
        self.assertEqual(developer.main(self.args, lambda *_: True), 0)
        self.assertFalse(self.state.exists())

    def test_checklist_readonly_and_explicit_acknowledgement(self):
        self.args.action = "list"
        self.assertEqual(
            checklist.main(self.args, lambda *_: True, state=str(self.state)), 0
        )
        self.assertFalse(self.state.exists())
        data = json.loads(self.out.getvalue())
        self.assertEqual(len(data["tasks"]), 25)
        self.args.action = "done"
        self.args.value = "drivers"
        self.assertEqual(
            checklist.main(self.args, lambda *_: False, state=str(self.state)), 4
        )
        self.assertFalse(self.state.exists())
        self.assertEqual(
            checklist.main(self.args, lambda *_: True, state=str(self.state)), 0
        )
        path = self.state / "checklist.json"
        self.assertEqual(checklist.read(path), {"drivers": "done"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.args.action = "skipped"
        checklist.main(self.args, lambda *_: True, state=str(self.state))
        self.assertEqual(checklist.read(path), {"drivers": "skipped"})

    def test_checklist_invalid_state_and_symlinks_rejected(self):
        self.args.action = "done"
        self.args.value = "not-a-task"
        with self.assertRaises(ValueError):
            checklist.main(self.args, lambda *_: True, state=str(self.state))
        self.state.mkdir(mode=0o700)
        path = self.state / "checklist.json"
        path.write_text(json.dumps({"schema": 1, "tasks": {"drivers": "secret"}}))
        path.chmod(0o600)
        self.args.action = "list"
        with self.assertRaises(ValueError):
            checklist.main(self.args, lambda *_: True, state=str(self.state))
        path.unlink()
        path.symlink_to(self.home / "elsewhere")
        with self.assertRaises(ValueError):
            checklist.main(self.args, lambda *_: True, state=str(self.state))

    def test_checklist_review_cancel_does_not_save_partial_answers(self):
        self.args.action = "review"
        with (
            patch("checklist.sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=["done", KeyboardInterrupt]),
            self.assertRaises(KeyboardInterrupt),
        ):
            checklist.main(self.args, lambda *_: True, state=str(self.state))
        self.assertFalse(self.state.exists())

    def test_optional_banner_is_interactive_only_and_never_installs(self):
        content = developer.shell_content(b"# retained\n", "bash", "fastfetch")
        self.assertIn(b"--banner fastfetch", content)
        self.assertIn(b"[[ $- != *i* ]]", developer.shell_helper("bash").read_bytes())
        self.assertEqual(content, developer.shell_content(content, "bash", "fastfetch"))
        self.assertNotIn(b"fastfetch", developer.shell_content(content, "bash"))
        self.assertIn(
            b"status is-interactive", developer.shell_helper("fish").read_bytes()
        )
        with self.assertRaises(ValueError):
            developer.shell_content(b"", "bash", "evil;sh")

    def test_vendor_wrapper_preserves_arguments_exit_codes_and_user_functions(self):
        folder = self.home / "vendor/bin"
        folder.mkdir(parents=True)
        tool = folder / "fixture"
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n')
        tool.chmod(0o700)
        for shell in ("bash", "zsh", "fish"):
            if not shutil.which(shell):
                continue
            config = self.home / (shell + ".rc")
            config.write_bytes(developer.shell_content(b"", shell))
            cp = subprocess.run(
                [
                    shell,
                    "-c",
                    'source "$argv[1]"; vbin fixture "two words" three'
                    if shell == "fish"
                    else 'source "$1"; vbin fixture "two words" three',
                    *([str(config)] if shell == "fish" else ["fixture", str(config)]),
                ],
                cwd=self.home,
                capture_output=True,
                text=True,
            )
            self.assertEqual(cp.returncode, 7, (shell, cp.stderr))
            self.assertEqual(cp.stdout, "two words\nthree\n")
        config = self.home / "bash.rc"
        cp = subprocess.run(
            [
                "bash",
                "-c",
                'vbin() { printf preserved; }; source "$1"; vbin',
                "fixture",
                str(config),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.stdout, "preserved")


class HubMigration(unittest.TestCase):
    def response(self, files):
        return {"id": "publisher/model", "sha": "a" * 40, "siblings": files}

    def row(self, name):
        return {
            "rfilename": name,
            "size": 100,
            "lfs": {"sha256": "b" * 64, "size": 100},
        }

    def test_rank_scope_offset_encoded_without_claiming_quality(self):
        with patch(
            "models.catalogue_json",
            return_value=[
                {"id": "owner/model"},
                {"id": "owner/model"},
                {"id": "../bad"},
                {"id": "bad/$(exec)"},
            ],
        ) as get:
            result = models.search(
                "tiny coder", backend="vllm", rank="trending", scope="warm", offset=25
            )
        url = get.call_args.args[0]
        for token in (
            "sort=trendingScore",
            "inference_provider=all",
            "skip=25",
            "pipeline_tag=text-generation",
            "tiny+coder",
        ):
            self.assertIn(token, url)
        self.assertEqual(len(result), 1)
        self.assertIn("not quality", result[0]["note"])
        with self.assertRaises(ValueError):
            models.search("coder", offset=-1)

    def test_pinned_gguf_shards_have_exact_url_size_and_publisher_digest(self):
        files = [
            self.row("tiny-Q4_K_M-00001-of-00002.gguf"),
            self.row("tiny-Q4_K_M-00002-of-00002.gguf"),
            self.row("mmproj-Q4_K_M.gguf"),
        ]
        with patch("models.catalogue_json", return_value=self.response(files)):
            result = models.model_files("publisher/model", "a" * 40, quant="Q4_K_M")
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][0]["publisher_sha256"], "b" * 64)
        self.assertIn("/resolve/" + "a" * 40 + "/", result["files"][0]["url"])
        self.assertIn("Independently verify", result["note"])

    def test_incomplete_shards_revision_conflicts_and_bad_metadata_fail(self):
        for payload in (
            self.response([self.row("tiny-Q4-00001-of-00002.gguf")]),
            {**self.response([]), "sha": "c" * 40},
            self.response([{"rfilename": "tiny.gguf", "size": True}]),
            self.response([self.row("tiny.gguf"), self.row("tiny.gguf")]),
        ):
            with (
                self.subTest(payload=payload),
                patch("models.catalogue_json", return_value=payload),
                self.assertRaises(ValueError),
            ):
                models.model_files("publisher/model", "a" * 40)
        with patch("models.catalogue_json") as get, self.assertRaises(ValueError):
            models.model_files("publisher/model", "main")
        get.assert_not_called()

    def test_safetensors_discovery_excludes_executable_pickle_and_nested_paths(self):
        files = [
            self.row(name)
            for name in (
                "config.json",
                "model.safetensors",
                "unsafe.py",
                "pytorch_model.bin",
                "../escape.json",
                "sub/config.json",
            )
        ]
        with patch("models.catalogue_json", return_value=self.response(files)):
            result = models.model_files("publisher/model", "a" * 40, backend="vllm")
        self.assertEqual(
            [x["name"] for x in result["files"]], ["config.json", "model.safetensors"]
        )
