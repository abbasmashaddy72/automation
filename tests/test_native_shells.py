"""Execute generated shell integration with native runtimes and private fixtures."""

import json
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import developer


class NativeShellIntegration(unittest.TestCase):
    def test_existing_configuration_preview_reads_only_the_selected_safe_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".config/fish/config.fish"
            config.parent.mkdir(parents=True)
            original = b"echo '<fixture>'\r\n"
            config.write_bytes(original)
            zsh = root / ".zshrc"
            zsh.touch()
            with (
                patch.object(Path, "home", return_value=root),
                patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / ".config")}),
            ):
                for shell, expected in (
                    ("fish", (True, original.decode())),
                    ("bash", (False, "")),
                    ("zsh", (True, "")),
                ):
                    output = StringIO()
                    with redirect_stdout(output):
                        developer.show_shell(shell)
                    preview = json.loads(output.getvalue())
                    self.assertEqual((preview["exists"], preview["content"]), expected)
                (root / ".bashrc").symlink_to(config)
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    developer.show_shell("bash")
            self.assertEqual(config.read_bytes(), original)

    def test_compact_loader_replaces_inline_block_and_round_trips_options(self):
        from terminal_setup import (
            integration_options,
            DEVELOPMENT_COMMANDS,
            CLEANUP_COMMANDS,
            AI_COMMANDS,
        )

        before = b"# preserved prefix\r\n# BEGIN AUTOMATION TOOLKIT\nold toolkit code\n# END AUTOMATION TOOLKIT\r\n# preserved suffix\r\n"
        for shell in developer.SHELLS:
            greeting = "off" if shell == "fish" else "keep"
            options = dict(
                banner="fastfetch",
                greeting=greeting,
                use_agent=True,
                terminal_ai=True,
                project_cleanup_aliases=shell != "bash",
            )
            content = developer.shell_content(before, shell, **options)
            self.assertTrue(content.startswith(b"# preserved prefix\r\n"))
            self.assertTrue(content.endswith(b"# preserved suffix\r\n"))
            self.assertEqual(
                content, developer.shell_content(content, shell, **options)
            )
            self.assertNotIn(b"old toolkit code", content)
            self.assertNotIn(b"function vbin", content)
            self.assertLessEqual(len(content.splitlines()), 12)
            self.assertEqual(
                integration_options(content.decode()),
                {
                    "banner": "fastfetch",
                    "fish_greeting": greeting,
                    "use_toolkit_agent": True,
                    "terminal_ai": True,
                    "project_cleanup_aliases": shell != "bash",
                    "commands": [
                        *DEVELOPMENT_COMMANDS,
                        *(CLEANUP_COMMANDS if shell != "bash" else ()),
                        *AI_COMMANDS,
                    ],
                },
            )

    def test_project_cleanup_aliases_match_across_fish_and_zsh_and_keep_personal_definitions(
        self,
    ):
        for shell in ("fish", "zsh"):
            executable = shutil.which(shell)
            if not executable:
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("rm", "npm", "composer"):
                    program = root / name
                    program.write_text(f'#!/bin/sh\nprintf "{name}:%s\\n" "$*"\n')
                    program.chmod(0o700)
                config = root / "startup"
                config.write_bytes(
                    developer.shell_content(b"", shell, project_cleanup_aliases=True)
                )
                env = {
                    **os.environ,
                    "HOME": directory,
                    "ZDOTDIR": directory,
                    "XDG_CONFIG_HOME": directory,
                    "TERM": "dumb",
                    "PATH": directory + os.pathsep + os.defpath,
                    "FIXTURE_RC": str(config),
                }
                flags = ["--no-config"] if shell == "fish" else ["-d", "-f"]
                existing = (
                    "alias clean-composer 'echo personal'"
                    if shell == "fish"
                    else "alias clean-composer='echo personal'"
                )
                checks = (
                    (
                        'source "$FIXTURE_RC"; eval clean-npm; eval clean-composer',
                        [
                            "rm:-rf -- node_modules package-lock.json",
                            "npm:install",
                            "rm:-rf -- vendor composer.lock",
                            "composer:install",
                        ],
                    ),
                    (
                        existing + '; source "$FIXTURE_RC"; eval clean-composer',
                        ["personal"],
                    ),
                )
                for command, expected in checks:
                    result = subprocess.run(
                        [executable, *flags, "-ic", command],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), expected)

    def test_explicit_selection_enables_only_selected_commands(self):
        from terminal_setup import integration_options

        for shell in developer.SHELLS:
            executable = shutil.which(shell)
            if not executable:
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rc = root / "startup"
                vendor = root / "vendor/bin"
                vendor.mkdir(parents=True)
                pint = vendor / "pint"
                pint.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
                pint.chmod(0o700)
                env = {
                    **os.environ,
                    "HOME": directory,
                    "ZDOTDIR": directory,
                    "XDG_CONFIG_HOME": directory,
                    "TERM": "dumb",
                    "PATH": os.defpath,
                    "FIXTURE_RC": str(rc),
                }
                flags = {
                    "fish": ["--no-config"],
                    "zsh": ["-d", "-f"],
                    "bash": ["--noprofile", "--norc"],
                }[shell]
                selected = ["pint", "ai-ask"] + (
                    ["clean-composer"] if shell != "bash" else []
                )
                for commands in ([], selected):
                    config = developer.shell_content(b"", shell, commands=commands)
                    rc.write_bytes(config)
                    self.assertEqual(
                        set(integration_options(config.decode())["commands"]),
                        set(commands),
                    )
                    verify = (
                        'source "$FIXTURE_RC"; not type -q vbin; and not type -q clean-npm; or exit 1; '
                        if shell == "fish"
                        else 'source "$FIXTURE_RC"; ! command -v vbin >/dev/null && ! command -v clean-npm >/dev/null || exit 1; '
                    )
                    if commands:
                        verify += (
                            "eval 'pint \"two words\"'; automation_ai suggest >/dev/null; test $status -eq 2"
                            if shell == "fish"
                            else "eval 'pint \"two words\"'; automation_ai suggest >/dev/null; test $? -eq 2"
                        )
                    else:
                        verify += (
                            "not type -q pint; and not type -q ai"
                            if shell == "fish"
                            else "! command -v pint >/dev/null && ! command -v ai >/dev/null"
                        )
                    result = subprocess.run(
                        [executable, *flags, "-ic", verify],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.splitlines(), ["two words"] if commands else []
                    )

    def run_shell(self, shell):
        executable = shutil.which(shell)
        if not executable:
            self.skipTest("Native " + shell + " runtime unavailable")
        with tempfile.TemporaryDirectory(prefix="automation-shell-test-") as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            paths = [
                home / ".local/bin",
                home / "bin",
                home / ".config/composer/vendor/bin",
                home / ".composer/vendor/bin",
            ]
            for path in paths:
                path.mkdir(parents=True, exist_ok=True)
            vendor = root / "vendor/bin"
            vendor.mkdir(parents=True)
            tool = vendor / "fixture"
            tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            tool.chmod(0o700)
            config = root / "integration"
            config.write_bytes(developer.shell_content(b"# existing setting\n", shell))
            assertion = root / "assert-env.py"
            assertion.write_text(
                'import json,os\nprint(json.dumps(os.environ["PATH"].split(os.pathsep)))\n'
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "PATH": os.defpath,
                "AUTOMATION_SHELL_FIXTURE": str(config),
                "AUTOMATION_SHELL_ASSERT": str(assertion),
            }
            for name in ("BASH_ENV", "ENV", "ZDOTDIR", "SSH_AUTH_SOCK"):
                env.pop(name, None)
            command = 'source "$AUTOMATION_SHELL_FIXTURE"; source "$AUTOMATION_SHELL_FIXTURE"; vbin fixture "two words"; python3 "$AUTOMATION_SHELL_ASSERT"'
            flags = {
                "bash": ["--noprofile", "--norc", "-c"],
                "zsh": ["-f", "-c"],
                "fish": ["--no-config", "--command"],
            }[shell]
            result = subprocess.run(
                [executable, *flags, command],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[0], "two words")
            actual = json.loads(lines[-1])
            for path in paths:
                self.assertEqual(actual.count(str(path)), 1, (shell, actual))

    def test_bash_runtime(self):
        self.run_shell("bash")

    def test_fish_runtime(self):
        self.run_shell("fish")

    def test_zsh_runtime(self):
        self.run_shell("zsh")
