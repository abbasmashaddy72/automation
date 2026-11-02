"""Package execution regression contracts; no host package mutation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import automation as a
import catalog
import journal


class PlatformProviderContracts(unittest.TestCase):
    def test_releases_never_mix_family_package_managers(self):
        from providers import capability
        for id_, like, fam, mgr in [
            ('cachyos','arch','arch','pacman'),('ubuntu','debian','debian','apt-get'),
            ('rocky','rhel fedora','rhel','dnf'),('opensuse-tumbleweed','suse','opensuse','zypper'),
            ('alpine','','alpine','apk')]:
            info=a.platform_info({'ID':id_,'ID_LIKE':like,'VERSION_ID':'2026'})
            cap=capability(info)
            self.assertEqual((cap['family'],cap['manager']), (fam,mgr))
    def test_immutable_and_wsl_host_require_warning(self):
        from providers import capability
        info={'family':'fedora','id':'fedora','version':'42','manager':'dnf','immutable':True,'container':False,'wsl':False}
        self.assertFalse(capability(info)['host_install_allowed'])
        info.update(immutable=False,wsl=True)
        self.assertFalse(capability(info)['host_install_allowed'])
    def test_no_unsafe_fallback_on_unknown_distribution(self):
        from providers import capability
        self.assertFalse(capability({'family':'unknown','id':'custom'} )['host_install_allowed'])
    def test_check_exact_repository_name(self):
        from providers import exact_available
        info={'family':'opensuse','manager':'zypper'}
        class P:
            returncode=0
            stdout='Name : nginx-server\nStatus : not installed'
        self.assertFalse(exact_available('nginx', info, runner=lambda c:P()))
        P.stdout='Name : nginx\nStatus : not installed'
        self.assertTrue(exact_available('nginx', info, runner=lambda c:P()))
    def test_release_specific_alias_fallbacks(self):
        from providers import candidates
        self.assertEqual(candidates('firefox',{'family':'debian','id':'ubuntu','version':'24.04'})[0],'firefox')
        self.assertEqual(candidates('firefox',{'family':'debian','id':'debian','version':'12'})[0],'firefox-esr')


class SelectionContracts(unittest.TestCase):
    def test_stack_mode_excludes_lerd_overlapping_servers_only(self):
        from wizard import filtered_entries
        entries=[{'id':x,'category':'x','default':True} for x in ('lerd','php','nginx','dbeaver','git')]
        out=filtered_entries(entries,'lerd')
        self.assertEqual([x['id'] for x in out],['lerd','dbeaver','git'])
        self.assertEqual([x['id'] for x in filtered_entries(entries,'standalone')],['php','nginx','dbeaver','git'])
    def test_select_all_and_toggle_category_do_not_create_unknown_packages(self):
        from wizard import toggle_selection
        entries=[{'id':'git','category':'dev'},{'id':'wget','category':'essential'}]
        self.assertEqual(toggle_selection(set(),entries,'all'),{'git','wget'})
        self.assertEqual(toggle_selection({'git'},entries,'cat dev'),set())
        self.assertEqual(toggle_selection(set(),entries,'cat dev'),{'git'})
        with self.assertRaises(ValueError):toggle_selection(set(),entries,'cat unknown')
    def test_incompatible_lerd_retains_standalone_selection(self):
        from wizard import filtered_entries
        entries=[{'id':'lerd','category':'x'}, {'id':'php','category':'x'}]
        self.assertEqual([x['id'] for x in filtered_entries(entries,'standalone')],['php'])


class OwnedInstallContracts(unittest.TestCase):
    def test_record_claim_only_after_verified_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal.record_ownership('git','git','apt-get',directory=str(Path(tmp)/'state'),verified=True)
            ownership=journal.owned(directory=str(Path(tmp)/'state'))
            self.assertEqual(ownership['git']['package'],'git')
            self.assertEqual(ownership['git']['source'],'apt-get')
            self.assertFalse(ownership['git'].get('removable',True))
    def test_never_claim_unverified_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                journal.record_ownership('git','git','apt-get',directory=str(Path(tmp)/'state'),verified=False)
            self.assertEqual(journal.owned(directory=str(Path(tmp)/'state')),{})
    def test_install_checkpoint_separates_completed_and_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=str(Path(tmp)/'state')
            journal.write('started',directory=directory,session='trial',packages=['git','curl'])
            journal.write('action',directory=directory,session='trial',packages=['git'],source='apt-get',result=0)
            self.assertEqual(journal.pending(directory=directory,session='trial'),['curl'])
            self.assertEqual(journal.pending(directory=directory,session='absent'),[])
    def test_journal_path_remains_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=str(Path(tmp)/'state')
            journal.record_ownership('git','git','apt-get',directory=directory,verified=True)
            self.assertEqual((Path(directory)/'owned.json').stat().st_mode & 0o777,0o600)


class SafetyContracts(unittest.TestCase):
    def test_read_only_plans_do_not_create_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            info={'family':'debian','manager':'apt-get','desktop':False,'id':'debian','version':'12'}
            with patch.object(a,'installed',return_value=False), patch.object(a,'available',return_value=True), patch.object(a,'flatpak_available',return_value=False):
                status=a.main(['packages','--select','git','--dry-run'])
            self.assertEqual(status,0)
            self.assertFalse((Path(tmp)/'install-journal.jsonl').exists())
    def test_no_install_on_immutable_host(self):
        from providers import capability
        self.assertFalse(capability({'family':'fedora','id':'silverblue','immutable':True,'manager':'dnf'})['host_install_allowed'])

if __name__ == '__main__': unittest.main()

class PackageExecutionTests(unittest.TestCase):
    def info(self, **changes):
        return dict(family='debian',manager='apt-get',desktop=False,id='debian',version='12',
                    wsl=False,container=False,immutable=False,arch='x86_64',**changes)

    def args(self, **kwargs):
        import argparse
        value=dict(select=['git,curl'],exclude=None,interactive=False,command='packages',
                   action='install',dry_run=False,yes=True,non_interactive=True,replace=[],
                   allow_standalone_dev=False)
        value.update(kwargs)
        return argparse.Namespace(**value)

    def test_batch_ownership_requires_post_install_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=str(Path(tmp)/'state')
            # Simulate one initially absent package that becomes installed when
            # the package-manager transaction completes successfully.
            state_now={'installed':False}
            def check(*args):return state_now['installed']
            def execute(*args,**kwargs):state_now['installed']=True;return 0
            with patch.object(a,'installed',side_effect=check),\
                 patch.object(a,'available',return_value=True),\
                 patch.object(a,'native_exact_available',return_value=True),\
                 patch.object(a,'run',side_effect=execute),\
                 patch.object(a,'flatpak_available',return_value=False):
                result=a.packages_action(self.args(select=['git']),self.info(),{'AUTOMATION_STATE_DIR':state})
            self.assertEqual(result,0)
            self.assertIn('git',journal.owned(directory=state))
            self.assertEqual(journal.pending(directory=state),[])

    def test_success_code_without_post_install_is_failure_and_not_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=str(Path(tmp)/'state')
            with patch.object(a,'installed',return_value=False),\
                 patch.object(a,'available',return_value=True),\
                 patch.object(a,'native_exact_available',return_value=True),\
                 patch.object(a,'run',return_value=0),\
                 patch.object(a,'flatpak_available',return_value=False):
                result=a.packages_action(self.args(select=['git']),self.info(),{'AUTOMATION_STATE_DIR':state})
            self.assertEqual(result,1)
            self.assertNotIn('git',journal.owned(directory=state))
            self.assertEqual(journal.pending(directory=state),['git'])

    def test_immutable_host_prevents_approved_mutations(self):
        from io import StringIO
        import contextlib
        with patch.object(a,'installed',return_value=False),\
             patch.object(a,'available',return_value=True),\
             patch.object(a,'run') as run:
            immutable={**self.info(), 'immutable':True}
            with contextlib.redirect_stderr(StringIO()):
                result=a.packages_action(self.args(select=['git']),immutable,{})
            self.assertEqual(result,3)
            run.assert_not_called()

    def test_read_only_inventory_is_empty_in_private_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=str(Path(tmp)/'state')
            self.assertEqual(journal.owned(directory=state),{})
            self.assertEqual(journal.pending(directory=state),[])

class LerdDefaultContracts(unittest.TestCase):
    def test_incompatible_gui_defaults_exclude_lerd(self):
        import argparse
        from io import StringIO
        import contextlib
        info={'family':'debian','id':'debian','version':'13','desktop':True,
              'arch':'x86_64','manager':'apt-get','init':'other','user_systemd':False,
              'container':False,'wsl':False}
        args=argparse.Namespace(select=None,exclude=None,interactive=False,
                command='packages',action='plan',dry_run=True,yes=False,
                non_interactive=True,replace=[],allow_standalone_dev=False)
        with patch.object(a,'installed',return_value=True):
            with contextlib.redirect_stdout(StringIO()) as output:
                rc=a.packages_action(args,info,{})
        self.assertEqual(rc,0)
        self.assertIn('Lerd excluded from defaults',output.getvalue())
        self.assertNotIn('lerd                           ',output.getvalue())

    def test_user_explicit_lerd_still_displayed_when_unavailable(self):
        import argparse
        from io import StringIO
        import contextlib
        info={'family':'alpine','id':'alpine','version':'3.22','desktop':False,
              'arch':'x86_64','manager':'apk','init':'other','user_systemd':False,
              'container':False,'wsl':False}
        args=argparse.Namespace(select=['lerd'],exclude=None,interactive=False,
                command='packages',action='plan',dry_run=True,yes=False,
                non_interactive=True,replace=[],allow_standalone_dev=False)
        with patch.object(a,'installed',return_value=False):
            with contextlib.redirect_stdout(StringIO()) as output:
                rc=a.packages_action(args,info,{})
        self.assertEqual(rc,0)
        self.assertIn('lerd ',output.getvalue())
        self.assertIn('unavailable',output.getvalue())
