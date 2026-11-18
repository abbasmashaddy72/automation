"""Regression cases for cross-source discovery, moved legacy tools and visible progress."""

from __future__ import annotations
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import automation
import cache
import discovery
import progress
import sources


class SourceDiscoveryTests(unittest.TestCase):
    def arch(self):
        return {
            "id": "cachyos",
            "family": "arch",
            "version": "rolling",
            "arch": "x86_64",
            "manager": "pacman",
            "desktop": True,
        }

    def args(self, **overrides):
        data = dict(
            select=["winscp"],
            exclude=None,
            replace=None,
            source=None,
            command="packages",
            action="plan",
            interactive=False,
            dry_run=True,
            yes=False,
            non_interactive=True,
            enable_aur=False,
            allow_standalone_dev=False,
            output=None,
        )
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_all_installed_helpers_checked_on_arch(self):
        values = {n: "/usr/bin/" + n for n in sources.HELPERS}
        self.assertEqual(
            sources.arch_sources(self.arch(), which=lambda n: values.get(n)),
            list(sources.HELPERS),
        )
        self.assertEqual(
            sources.arch_sources({"family": "debian"}, which=lambda n: values.get(n)),
            [],
        )

    def test_installed_intellij_alias_wins_over_flatpak(self):
        with (
            patch.object(
                automation,
                "installed",
                side_effect=lambda name, family, **kwargs: name == "intellij-idea-oss",
            ),
            patch.object(automation, "installed_source", return_value="pacman"),
            patch.object(automation, "flatpak_installed") as flatpak,
            patch.object(automation, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                automation.packages_action(
                    self.args(
                        select=["intellij-idea-community-edition"],
                        action="install",
                        yes=True,
                    ),
                    self.arch(),
                    {"AUTOMATION_PREFER_FLATPAK": "true"},
                ),
                0,
            )
            self.assertIn("installed    pacman → intellij-idea-oss", output.getvalue())
            flatpak.assert_not_called()
            run.assert_not_called()

    def test_approved_exact_aur_wins_over_flatpak_fallback(self):
        with (
            patch.object(automation, "installed", return_value=False),
            patch.object(automation, "available", return_value=False),
            patch.object(automation, "flatpak_installed", return_value=False),
            patch.object(automation, "flatpak_available", return_value=True) as flatpak,
            patch.object(
                sources,
                "search_exact",
                return_value=[
                    {
                        "source": "shelly",
                        "package": "postman-bin",
                    }
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                automation.packages_action(
                    self.args(select=["postman-bin"], enable_aur=True), self.arch(), {}
                ),
                0,
            )
            self.assertIn("available    shelly", output.getvalue())
            flatpak.assert_not_called()

    def test_arch_missing_package_waits_for_choice_instead_of_using_flatpak(self):
        with (
            patch.object(automation, "installed", return_value=False),
            patch.object(automation, "available", return_value=False),
            patch.object(automation, "flatpak_installed", return_value=False),
            patch.object(automation, "flatpak_available", return_value=True) as flatpak,
            patch.object(sources, "search_exact", return_value=[]),
            patch.object(automation, "_recommend", return_value=[]),
            patch.object(automation, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                automation.packages_action(
                    self.args(
                        select=["postman-bin"],
                        action="install",
                        yes=True,
                        enable_aur=True,
                    ),
                    self.arch(),
                    {},
                ),
                5,
            )
            self.assertIn("Choose a package from search results", output.getvalue())
            flatpak.assert_not_called()
            run.assert_not_called()

    def test_exact_name_required_no_description_false_positive(self):
        self.assertFalse(
            sources.exact_metadata(
                "paru",
                "winscp",
                "Name : wine-tools\nDescription : winscp helper\nRepository : aur",
            )
        )
        self.assertTrue(
            sources.exact_metadata(
                "paru", "winscp", "Repository : aur\nName : winscp\nVersion : 6.0"
            )
        )
        self.assertFalse(
            sources.exact_metadata("yay", "winscp", "Repository : extra\nName : winscp")
        )
        self.assertTrue(
            sources.exact_metadata("shelly", "winscp", "aur/winscp 6.4.2-1")
        )
        self.assertTrue(
            sources.exact_metadata("shelly", "winscp", "Name: winscp\nVersion: 6.4.2")
        )
        self.assertTrue(
            sources.exact_metadata("shelly", "winscp", "winscp 6.4.2-1 installed=no")
        )
        self.assertFalse(
            sources.exact_metadata("shelly", "winscp", "Search results: winscp library")
        )

    def test_exact_search_checks_each_helper(self):
        responses = {
            "shelly": "unstructured results without metadata",
            "paru": "Repository : aur\nName : winscp\nVersion : 1.0",
            "yay": "Repository : extra\nName : winscp",
            "pamac": "Name : winscp\nRepository : aur",
        }
        seen = []

        def runner(cmd):
            seen.append(cmd)
            return SimpleNamespace(returncode=0, stdout=responses[cmd[0]])

        found = sources.search_exact(
            "winscp", self.arch(), runner=runner, which=lambda _: "/usr/bin/mock"
        )
        self.assertEqual({r["source"] for r in found}, {"paru", "pamac"})
        self.assertEqual({r[0] for r in seen}, set(sources.HELPERS))
        self.assertIn(["shelly", "search", "aur", "--detail", "winscp"], seen)

    def test_unsupported_aur_source_refused(self):
        with self.assertRaises(ValueError):
            sources.helper_install_cmd("other", "winscp")
        for source in ("shelly", "paru", "yay", "pamac"):
            command = sources.helper_install_cmd(source, "winscp")
            self.assertNotIn("--noconfirm", command)
            self.assertNotIn("--no-confirm", command)

    def test_no_confirm_approves_package_plan_without_enabling_aur(self):
        with (
            patch.object(automation, "config", return_value={}),
            patch.object(automation, "platform_info", return_value=self.arch()),
            patch.object(automation, "packages_action", return_value=0) as install,
        ):
            for action in ("install", "repair"):
                self.assertEqual(
                    automation.main(
                        ["packages", action, "--select", "postman-bin", "--no-confirm"]
                    ),
                    0,
                )
                args = install.call_args.args[0]
                self.assertTrue(args.yes)
                self.assertFalse(args.enable_aur)

    def test_no_confirm_does_not_approve_other_workflows(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            automation.main(["zed", "replace", "profile.json", "--no-confirm"])
        self.assertEqual(error.exception.code, 2)

    def test_winscp_readonly_plan_shows_aur_even_if_disabled(self):
        with (
            patch.object(automation.os, "geteuid", return_value=1000),
            patch.object(automation, "installed", return_value=False),
            patch.object(automation, "package_native_name", return_value=None),
            patch.object(automation, "flatpak_installed", return_value=False),
            patch.object(automation, "flatpak_available", return_value=False),
            patch.object(
                sources,
                "search_exact",
                return_value=[
                    {
                        "package": "winscp",
                        "source": "paru",
                        "identity": "exact-name-aur-community",
                    }
                ],
            ),
            patch.object(automation, "_recommend", return_value=[]),
        ):
            result = io.StringIO()
            with contextlib.redirect_stdout(result):
                rc = automation.packages_action(self.args(), self.arch(), {})
            self.assertEqual(rc, 0)
            self.assertIn("Exact-name AUR candidates", result.getvalue())
            self.assertIn("requires --enable-aur", result.getvalue())
            self.assertIn("AUR opt-in", result.getvalue())
            self.assertNotIn("no-compatible-source", result.getvalue())

    def test_winscp_install_requires_explicit_aur_option(self):
        matches = [
            {
                "package": "winscp",
                "source": "shelly",
                "identity": "exact-name-aur-community",
            },
            {
                "package": "winscp",
                "source": "paru",
                "identity": "exact-name-aur-community",
            },
        ]
        with (
            patch.object(automation.os, "geteuid", return_value=1000),
            patch.object(automation, "installed", return_value=False),
            patch.object(automation, "package_native_name", return_value=None),
            patch.object(automation, "flatpak_installed", return_value=False),
            patch.object(automation, "flatpak_available", return_value=False),
            patch.object(sources, "search_exact", return_value=matches),
            patch.object(automation, "run", return_value=0) as runner,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = automation.packages_action(
                    self.args(
                        action="install", source=["winscp=paru"], enable_aur=True
                    ),
                    self.arch(),
                    {},
                )
            self.assertEqual(rc, 0)
            self.assertEqual(runner.call_args.args[0], ["paru", "-S", "winscp"])
            runner.reset_mock()
            with patch.object(automation.sys.stdin, "isatty", return_value=False):
                self.assertEqual(
                    automation.packages_action(
                        self.args(
                            action="install",
                            source=["winscp=shelly"],
                            enable_aur=True,
                            no_confirm=True,
                            dry_run=False,
                        ),
                        self.arch(),
                        {},
                    ),
                    4,
                )
            runner.assert_not_called()
            with self.assertRaises(ValueError):
                automation.packages_action(
                    self.args(action="install", source=["winscp=paru"]), self.arch(), {}
                )
            runner.assert_not_called()

    def test_no_broad_redis_alternatives_for_tinyrdm(self):
        rows = [
            {"package": "php-redis", "description": "PHP plugin", "source": "native"},
            {
                "package": "nginx-mod-redis",
                "description": "Redis connector",
                "source": "native",
            },
            {"package": "tiny-rdm", "description": "Tiny RDM app", "source": "native"},
        ]
        got = discovery.rank("tiny-rdm-bin", rows)
        self.assertEqual([x["package"] for x in got], ["tiny-rdm"])

    def test_explicit_source_for_other_package_rejected(self):
        with self.assertRaises(ValueError):
            automation._source_overrides(SimpleNamespace(source=["winscp=evil;rm"]))


class ArchitectureAndProgressTests(unittest.TestCase):
    def test_families_are_not_conflated(self):
        self.assertEqual(
            automation.get_family({"ID": "opensuse-tumbleweed", "ID_LIKE": "suse"}),
            "opensuse",
        )
        self.assertEqual(
            automation.get_family({"ID": "rocky", "ID_LIKE": "rhel fedora"}), "rhel"
        )

    def test_rolling_release_is_not_unknown(self):
        with patch.object(automation, "lerd_compat", return_value=[]):
            info = automation.platform_info({"ID": "cachyos", "ID_LIKE": "arch"})
        self.assertEqual(info["version"], "rolling")

    def test_readonly_repo_cache_is_short_lived_and_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            key = ["native-exact", "arch", "winscp"]
            self.assertTrue(cache.put(key, True, folder=d))
            self.assertIs(cache.get(key, folder=d), True)
            self.assertIsNone(cache.get(key + ["another"], folder=d))
            self.assertEqual(cache.clear(folder=d), 1)
            self.assertIsNone(cache.get(key, folder=d))

    def test_spinner_does_not_block_quick_tasks(self):
        class Output(io.StringIO):
            def isatty(self):
                return False

        output = Output()
        with progress.waiting("read-only query", delay=0.1, stream=output):
            pass
        self.assertEqual(output.getvalue(), "")
        with progress.waiting("long query", delay=0.01, stream=output):
            time.sleep(0.05)
        self.assertIn("[working]", output.getvalue())

    def test_retired_opensuse_entrypoints_are_not_reintroduced(self):
        self.assertFalse((ROOT / "archlinux").exists())
        self.assertFalse((ROOT / "opensuse").exists())
        self.assertFalse((ROOT / "modules/legacy/opensuse").exists())
        self.assertNotIn(
            "AUTOMATION_ALLOW_UNSAFE_LEGACY", (ROOT / "setup.sh").read_text()
        )
        self.assertTrue((ROOT / "lib/providers.py").is_file())
        self.assertTrue((ROOT / "lib/developer.py").is_file())

    def test_prereqs_no_implicit_gum_from_wizard(self):
        setup = (ROOT / "setup.sh").read_text()
        self.assertIn("opts+=(--without-ui)", setup)
        self.assertIn("--with-ui", (ROOT / "scripts/prerequisites.sh").read_text())


if __name__ == "__main__":
    unittest.main()


class DistributionAndSourcesTests(unittest.TestCase):
    def test_dynamic_exact_probe_for_catalog_gap(self):
        import providers

        info = {"family": "fedora", "id": "fedora", "arch": "x86_64", "version": "43"}
        self.assertIn("dbeaver", providers.candidates("dbeaver", info))
        with patch.object(
            providers,
            "exact_available",
            side_effect=lambda name, host, runner=None: name == "dbeaver",
        ):
            self.assertEqual(providers.choose_native("dbeaver", info), "dbeaver")

    def test_flatpak_respects_configured_scope(self):
        with (
            patch.object(automation.shutil, "which", return_value="/usr/bin/flatpak"),
            patch.object(
                automation,
                "_query",
                side_effect=[
                    SimpleNamespace(returncode=1),
                    SimpleNamespace(returncode=0),
                ],
            ) as query,
        ):
            self.assertEqual(automation.flatpak_scope("postman-bin"), "--system")
            self.assertEqual(query.call_count, 2)

    def test_no_untrusted_flatpak_remote_created(self):
        with patch.object(automation.shutil, "which", return_value=None):
            self.assertIsNone(automation.flatpak_scope("postman-bin"))


class PackagePlannerSafetyTests(unittest.TestCase):
    def test_install_review_lists_resolved_packages_before_confirmation(self):
        info = {
            "id": "debian",
            "family": "debian",
            "manager": "apt-get",
            "desktop": True,
        }
        args = SimpleNamespace(
            select=["firefox", "postman-bin", "winscp"],
            exclude=None,
            replace=None,
            source=None,
            command="packages",
            action="install",
            interactive=False,
            dry_run=False,
            yes=False,
            non_interactive=True,
            enable_aur=False,
            allow_standalone_dev=False,
            output=None,
        )
        output = io.StringIO()

        def decline(*_):
            review = output.getvalue().split("Unavailable selections (1): winscp\n", 1)[
                1
            ]
            self.assertIn("Packages to install (2):", review)
            self.assertIn("firefox-esr [apt-get] (selected as firefox)", review)
            self.assertIn(
                "com.getpostman.Postman [flatpak] (selected as postman-bin)", review
            )
            self.assertNotIn("winscp", review)
            return False

        with (
            patch.object(automation, "installed", return_value=False),
            patch.object(
                automation, "available", side_effect=lambda name, _: name == "firefox"
            ),
            patch.object(
                automation.providers, "choose_native", return_value="firefox-esr"
            ),
            patch.object(automation, "flatpak_installed", return_value=False),
            patch.object(
                automation,
                "flatpak_available",
                side_effect=lambda name: name == "postman-bin",
            ) as flatpak,
            patch.object(automation, "_recommend", return_value=[]),
            patch.object(automation, "approved", side_effect=decline),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(automation.packages_action(args, info, {}), 4)
        self.assertNotIn("firefox", [call.args[0] for call in flatpak.call_args_list])

    def test_unverified_catalog_candidate_is_unavailable(self):
        info = {
            "id": "debian",
            "family": "debian",
            "manager": "apt-get",
            "desktop": False,
        }
        args = SimpleNamespace(
            select=["tiny-rdm-bin"],
            exclude=None,
            replace=None,
            source=None,
            command="packages",
            action="plan",
            interactive=False,
            dry_run=True,
            yes=False,
            non_interactive=True,
            enable_aur=False,
            allow_standalone_dev=False,
            output=None,
        )
        with (
            patch.object(automation, "installed", return_value=False),
            patch.object(
                automation, "package_native_name", return_value="tiny-rdm-bin"
            ),
            patch.object(automation, "available", return_value=False),
            patch.object(automation, "flatpak_available", return_value=False),
            patch.object(automation, "_recommend", return_value=[]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(automation.packages_action(args, info, {}), 0)
            self.assertIn("unavailable", output.getvalue())
            self.assertNotIn(
                "tiny-rdm-bin                      available", output.getvalue()
            )
