"""Contract tests for cross-family package resolution, never touching host packages."""
import argparse
import importlib.util
import io
import contextlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT/'lib'))
import automation as a
import catalog as c


class CatalogTests(TestCase):
    def test_every_family_has_complete_baseline(self):
        for family in c.FAMILIES:
            with self.subTest(family=family):
                for pkg in ('git','curl','python3','nodejs','podman','flatpak','unzip'):
                    self.assertIsNotNone(c.native_name(pkg, family))
    def test_shelly_only_arch(self):
        for family in c.FAMILIES:
            self.assertEqual(bool(c.native_name('shelly',family)),family=='arch')
    def test_no_guessed_package_names(self):
        self.assertIsNone(c.native_name('tiny-rdm-bin','alpine'))
        self.assertIsNone(c.native_name('unknown-package','debian'))
    def test_explicit_mapping(self):
        self.assertEqual(c.native_name('python3','arch'),'python')
        self.assertEqual(c.native_name('firefox','opensuse'),'MozillaFirefox')
    def test_arch_defaults_preserved(self):
        arch = a.package_catalog({'family':'arch','desktop':True})
        self.assertGreaterEqual(sum(p['default'] for p in arch),54)
    def test_other_family_categories_show_unavailable_entries(self):
        deb = a.package_catalog({'family':'debian','desktop':True})
        self.assertIn('shelly',[p['id'] for p in deb])
        self.assertIn('firefox',[p['id'] for p in deb])
    def test_explicit_source_selection_safeguard(self):
        for fam in c.FAMILIES:
            self.assertIsNone(c.native_name('void-bin',fam) if fam!='arch' else None)

class Commands(TestCase):
    def test_native_install_cmd_uses_mapping(self):
        self.assertEqual(a.install_cmd('firefox',{'family':'opensuse'})[-1],'MozillaFirefox')
        self.assertEqual(a.install_cmd('python3',{'family':'arch'})[-1],'python')
    def test_absent_native_refused(self):
        with self.assertRaises(ValueError):
            a.install_cmd('void-bin',{'family':'debian'})
    def test_never_enable_repositories(self):
        for family in c.FAMILIES:
            self.assertNotIn('add-repository',' '.join(a.install_cmd('git',{'family':family})))
    def test_unknown_distribution_does_not_guess(self):
        self.assertEqual(a.get_family({'ID':'mystery','ID_LIKE':'foo'}),'unknown')
    def test_arch_parent_detection(self):
        self.assertEqual(a.get_family({'ID':'cachyos','ID_LIKE':'arch'}),'arch')

class PlanTests(TestCase):
    def args(self,**kwargs):
        values = {'select':['git'], 'exclude':None, 'interactive':False,'yes':True,
                  'non_interactive':True,'dry_run':True,'command':'packages',
                  'action':'install','prefer_flatpak':False,'prefer_shelly':False,
                  'enable_aur':False,'no_lerd':False}
        values.update(kwargs)
        return argparse.Namespace(**values)
    def info(self,family):
        return {'family':family,'manager':a.MANAGERS[family],'desktop':True,
                'arch':'x86_64','init':'systemd','user_systemd':True,
                'wsl':False,'container':False}
    def test_unknown_source_is_unavailable(self):
        with patch.object(a,'installed',return_value=False),\
             patch.object(a,'available',return_value=False),\
             patch.object(a,'flatpak_available',return_value=False):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(a.packages_action(self.args(select=['void-bin']),self.info('debian'),{}),5)
                self.assertIn('unavailable',output.getvalue())
    def test_prefer_flatpak_never_reinstalls_native_installed(self):
        with patch.object(a,'installed',return_value=True),\
             patch.object(a,'flatpak_available',return_value=True),\
             patch.object(a,'run') as runner:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.packages_action(self.args(select=['firefox']),self.info('debian'),{'AUTOMATION_PREFER_FLATPAK':'true'}),0)
            runner.assert_not_called()
    def test_nonarch_never_invokes_aur(self):
        with patch.object(a,'installed',return_value=False),\
             patch.object(a,'available',return_value=False),\
             patch.object(a,'aur_available') as aur,\
             patch.object(a,'flatpak_available',return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.packages_action(self.args(select=['shelly']),self.info('debian'),{'AUTOMATION_ENABLE_AUR':'true'}),5)
            aur.assert_not_called()
    def test_native_batch_and_dry_run(self):
        with patch.object(a,'installed',return_value=False),\
             patch.object(a,'available',return_value=True),\
             patch.object(a,'run',return_value=0) as runner:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.packages_action(self.args(select=['git,curl,unzip']),self.info('debian'),{}),0)
            self.assertEqual(runner.call_count,1)
            self.assertEqual(runner.call_args.args[0][-3:],['git','curl','unzip'])
    def test_explicit_cli_exclusions_no_removal(self):
        with patch.object(a,'installed',return_value=False),patch.object(a,'available',return_value=True),\
             patch.object(a,'run',return_value=0) as runner:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.packages_action(self.args(select=['git,curl'],exclude=['curl']),self.info('rhel'),{}),0)
            self.assertNotIn('curl',runner.call_args.args[0])
