"""Safe package discovery: lookup is read-only and candidates are never silently installed."""
import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
import automation as cli
import discovery


class SearchTests(unittest.TestCase):
    def test_unsafe_queries_rejected(self):
        for term in ('-R /','$(touch /tmp/x)','a;rm -rf /','', '../etc/passwd', 'a'*150):
            with self.subTest(term=term), self.assertRaises(ValueError):
                discovery.validate_term(term)

    def test_parsers_native(self):
        cases = {
            'debian': ('code - Visual Studio Code\ncodium - Community editor\n', 'code'),
            'arch': ('extra/code 1.0-1\n    Visual Studio Code\nextra/codecs 1.1-1\n', 'code'),
            'fedora': ('code.x86_64 : Visual Studio Code\n', 'code'),
            'opensuse': ('S | Name | Summary | Type\n--+------+---------+--------\n  | code | Visual Studio Code | package\n', 'code'),
            'alpine': ('code-1.1-r1 - Visual Studio Code\n', 'code'),
        }
        for fam,(text,want) in cases.items():
            with self.subTest(fam=fam):
                self.assertIn(want,[x['package'] for x in discovery.parse_search(fam,text)])

    def test_near_match_not_equivalence(self):
        s=discovery.rank('visual-studio-code-bin',[{'package':'code','description':'Visual Studio Code','source':'native'},
                 {'package':'unrelated','description':'other','source':'native'}],limit=3)
        self.assertEqual(s[0]['package'],'code')
        self.assertEqual(s[0]['relation'],'similar / verify identity')
        self.assertNotIn('unrelated',[x['package'] for x in s])

    def test_no_codec_false_positives_for_code(self):
        candidates=[{'package':p,'description':'Codec library','source':'native'} for p in ('iso-codes','libavcodec61','libcodec2-1.2','libqrencode4')]
        self.assertEqual(discovery.rank('visual-studio-code-bin',candidates),[])

    def test_no_external_repositories_and_correct_family(self):
        expected={'arch':'pacman','debian':'apt-cache','fedora':'dnf','rhel':'dnf','opensuse':'zypper','alpine':'apk'}
        for fam,cmd in expected.items():
            with self.subTest(family=fam):
                self.assertEqual(discovery.search_command(fam,'code')[0],cmd)
                self.assertNotIn('add-repo', ' '.join(discovery.search_command(fam,'code')))

    def test_unavailable_has_visible_recommendations(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        with patch.object(cli,'installed',return_value=False),patch.object(cli,'available',return_value=False),\
             patch.object(discovery,'suggest',return_value=[{'package':'code','source':'native','description':'Code editor', 'confidence':92,'relation':'similar / verify identity'}]),\
             patch.object(cli,'run') as execute:
            args=SimpleNamespace(select=['visual-studio-code-bin'],exclude=None,interactive=False,command='packages',action='plan',dry_run=True,yes=False,non_interactive=True,replace=[])
            with contextlib.redirect_stdout(io.StringIO()) as s:
                self.assertEqual(cli.packages_action(args,info,{'AUTOMATION_AUTO_SEARCH':'true'}),0)
            self.assertIn('code',s.getvalue())
            self.assertIn('recommend',s.getvalue().lower())
            execute.assert_not_called()

    def test_explicit_replacement_validated(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        args=SimpleNamespace(select=['visual-studio-code-bin'],exclude=None,interactive=False,command='packages',action='install',dry_run=True,yes=True,non_interactive=True,replace=['visual-studio-code-bin=code'])
        with patch.object(cli,'installed',return_value=False),patch.object(cli,'available',return_value=False),\
             patch.object(cli,'native_exact_available',return_value=True),patch.object(cli,'run',return_value=0) as execute:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.packages_action(args,info,{}),0)
            self.assertIn('code',execute.call_args.args[0])

    def test_no_install_unverified_replacement(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        args=SimpleNamespace(select=['visual-studio-code-bin'],exclude=None,interactive=False,command='packages',action='install',dry_run=False,yes=True,non_interactive=True,replace=['visual-studio-code-bin=no-such-package'])
        with patch.object(cli,'installed',return_value=False),patch.object(cli,'available',return_value=False),\
             patch.object(cli,'native_exact_available',return_value=False),patch.object(cli,'run') as execute:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertNotEqual(cli.packages_action(args,info,{}),0)
            execute.assert_not_called()

if __name__=='__main__': unittest.main()

class CustomPackageTests(unittest.TestCase):
    def test_custom_verified_native_package_can_be_selected(self):
        info={'family':'debian','manager':'apt-get','desktop':False}
        args=SimpleNamespace(select=['htop'],exclude=None,interactive=False,command='packages',action='install',dry_run=True,yes=True,non_interactive=True,replace=[])
        with patch.object(cli,'installed',return_value=False),patch.object(cli,'native_exact_available',return_value=True),\
             patch.object(cli,'run',return_value=0) as runner:
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(cli.packages_action(args,info,{}),0)
            self.assertIn('htop',runner.call_args.args[0])

    def test_custom_unverified_never_installed(self):
        info={'family':'alpine','manager':'apk','desktop':False}
        args=SimpleNamespace(select=['totally-unknown-package'],exclude=None,interactive=False,command='packages',action='install',dry_run=False,yes=True,non_interactive=True,replace=[])
        with patch.object(cli,'installed',return_value=False),patch.object(cli,'native_exact_available',return_value=False),\
             patch.object(discovery,'suggest',return_value=[]),patch.object(cli,'run') as runner:
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(cli.packages_action(args,info,{}),5)
            runner.assert_not_called()
