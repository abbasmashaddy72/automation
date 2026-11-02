"""Safe end-to-end prerequisites and configuration, packages, AI and portable workflows integration regression tests."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPrerequisiteEntrypoint(unittest.TestCase):
    def cli(self, *args, env=None):
        return subprocess.run(['bash', str(ROOT / 'setup.sh'), *args], text=True,
                              capture_output=True, timeout=35, env=env)

    def test_prerequisite_help_does_not_require_python(self):
        p = self.cli('prerequisites', '--help')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--with-lerd', p.stdout)
        self.assertIn('--yes', p.stdout)

    def test_host_check_read_only_and_no_os_install(self):
        p = self.cli('prerequisites', 'check')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Summary:', p.stdout)
        self.assertIn('Platform:', p.stdout)

    def test_unknown_flags_rejected(self):
        p = self.cli('prerequisites', 'install', '--execute-something')
        self.assertEqual(p.returncode, 2)

    def test_mock_distribution_detection_in_read_only_mode(self):
        for distro, family in [('arch', 'arch'), ('manjaro', 'arch'), ('ubuntu', 'debian'),
                               ('fedora', 'fedora'), ('rocky', 'rhel'),
                               ('opensuse-tumbleweed', 'opensuse'), ('alpine', 'alpine')]:
            with self.subTest(distro=distro), tempfile.TemporaryDirectory() as td:
                release = Path(td) / 'os-release'
                release.write_text('ID=' + distro + '\nVERSION_ID=1\n')
                p = self.cli('prerequisites', 'check', env={**os.environ,
                        'AUTOMATION_PREREQ_OS_RELEASE': str(release)})
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn(f'/ {family} /', p.stdout)

    def test_read_only_mode_does_not_execute_os_release_as_shell(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'unexpected'
            release = Path(td) / 'os-release'
            release.write_text(f'ID="ubuntu"\nNAME="$(touch {target})"\n')
            p = self.cli('prerequisites', 'check', env={**os.environ,
                         'AUTOMATION_PREREQ_OS_RELEASE': str(release)})
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse(target.exists())

    def test_missing_python_guidance_without_mutation(self):
        # Avoid altering PATH, instead assert the public bootstrap is discoverable
        # and expected script paths do not assume Python is installed.
        content = (ROOT / 'setup.sh').read_text()
        self.assertLess(content.index('prerequisites ]]; then'), content.index('python_ok()'))
        self.assertIn('exec bash "$ROOT/scripts/prerequisites.sh"', content)

    def test_auto_prereqs_and_minimal_dryrun(self):
        p = self.cli('--auto-prereqs', '--dry-run', '--install', '--profile=minimal',
                     '--no-auto-search')
        # Native availability differs (Fedora's wget2-wget is not an automatic replacement).
        self.assertIn(p.returncode,(0,5),p.stderr)
        if p.returncode==5:self.assertRegex(p.stdout,r'unavailable=[1-9]')
        self.assertIn('Platform:', p.stdout)
        self.assertIn('Review:', p.stdout)

    def test_optional_ui_absence_is_nonfatal(self):
        p = self.cli('prerequisites', 'install', '--dry-run', '--with-ui',
                     '--with-validation')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Summary:', p.stdout)

    def test_unsupported_distribution_cannot_install(self):
        with tempfile.TemporaryDirectory() as td:
            release=Path(td)/'os-release'
            release.write_text('ID=not_a_real_linux\n')
            p=self.cli('prerequisites','check',env={**os.environ,
                         'AUTOMATION_PREREQ_OS_RELEASE':str(release)})
            self.assertEqual(p.returncode,3)
            self.assertIn('unsupported',p.stdout)


class TestConsolidation(unittest.TestCase):
    def test_maintained_components_present(self):
        for item in ('lib/discovery.py','lib/providers.py','lib/lerd_ops.py',
                     'lib/journal.py','lib/wizard.py','ai/portable.py','ai/ai_health.py',
                     'scripts/validate.py','scripts/patch_manager.py',
                     'lib/workflows.py','lib/extensions.py','scripts/prerequisites.sh'):
            with self.subTest(item=item):
                self.assertTrue((ROOT/item).is_file(), item)

    def test_host_provisioning_retired_and_lerd_replacement_present(self):
        self.assertFalse((ROOT/'modules/legacy').exists())
        for name in ('setup.sh','lib/automation.py','ai/manager.py'):
            self.assertNotIn('modules/legacy',(ROOT/name).read_text())
        self.assertTrue((ROOT/'lib/lerd_ops.py').is_file())
        self.assertTrue((ROOT/'ai/legacy.py').is_file())  # bounded user-state recovery remains supported

    def test_local_configuration_is_ignored_and_excluded_from_source_inventory(self):
        import importlib.util
        self.assertIn('.env',(ROOT/'.gitignore').read_text().splitlines())
        spec=importlib.util.spec_from_file_location('patch_inventory',ROOT/'scripts/create-patch.py')
        inventory=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in ('.env','.env.production','fixture.key','model.gguf','model.safetensors','previous.zip'):
                (root/name).write_text('PRIVATE_FIXTURE=do-not-export\n')
            (root/'config').mkdir();(root/'config/defaults.env').write_text('AUTOMATION_PROFILE=minimal\n')
            exported=inventory.files(root)
            self.assertEqual(set(exported),{'config/defaults.env'})


if __name__ == '__main__':
    unittest.main()
