"""Safe checklist orchestration reuses maintained setup and preserves progress."""
from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import automation
import bootstrap
import checklist


class ChecklistAutomation(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name);self.root=self.home/'toolkit'
        (self.root/'config').mkdir(parents=True)
        (self.root/'config/defaults.env').write_text('AUTOMATION_PROFILE=minimal\nAUTOMATION_AI_THREADS=auto\n')
        self.state=self.home/'state';self.projects=self.home/'Custom Sites'
        self.settings={'AUTOMATION_PROJECT_SITES_DIR':str(self.projects)}
        env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'config')})
        env.start();self.addCleanup(env.stop)
        self.args=Namespace(action='automate',select=['configuration,projects'],value=None,dry_run=False)
        self.output=io.StringIO();redirect=contextlib.redirect_stdout(self.output)
        redirect.__enter__();self.addCleanup(redirect.__exit__,None,None,None)

    def run_checklist(self,approve=lambda *_:True):
        return checklist.main(self.args,approve,state=str(self.state),root=self.root,settings=self.settings)

    def test_readonly_checks_do_not_initialize_or_certify_identity(self):
        self.args.action='check'
        with patch('desktop.detect',return_value={'desktop':'headless'}):
            self.assertEqual(self.run_checklist(),0)
        result=json.loads(self.output.getvalue())
        self.assertTrue(all(row['status']=='pending' for row in result['checks']))
        self.assertFalse(self.projects.exists());self.assertFalse((self.root/'.env').exists())
        self.assertFalse(self.state.exists());self.assertFalse(result['git_config_file_present'])
        self.assertIn('Presence is not login',result['note'])

    def test_dryrun_and_rejected_approval_write_nothing(self):
        self.args.dry_run=True
        self.assertEqual(self.run_checklist(lambda *_:self.fail('Dry run requested approval')),0)
        self.args.dry_run=False
        self.assertEqual(self.run_checklist(lambda *_:False),4)
        self.assertFalse((self.root/'.env').exists());self.assertFalse(self.projects.exists())
        self.assertFalse(self.state.exists())

    def test_apply_preserves_configuration_projects_and_is_resumable(self):
        config=self.root/'.env';original=b'# retained\nAUTOMATION_PROFILE=developer'
        config.write_bytes(original);config.chmod(0o644)
        (self.projects/'Local').mkdir(parents=True)
        existing=self.projects/'Local/keep.txt';existing.write_text('existing project')
        self.assertEqual(self.run_checklist(),0)
        self.assertTrue(config.read_bytes().startswith(original+b'\n'))
        self.assertEqual(config.stat().st_mode&0o777,0o600)
        self.assertEqual(existing.read_text(),'existing project')
        self.assertTrue(all((self.projects/name).is_dir() for name in bootstrap.SITE_DIRECTORIES))
        before=config.read_bytes();mtime=config.stat().st_mtime_ns
        self.assertEqual(self.run_checklist(lambda *_:self.fail('Completed steps asked again')),0)
        self.assertEqual(config.read_bytes(),before);self.assertEqual(config.stat().st_mtime_ns,mtime)
        self.assertFalse(self.state.exists())

    def test_exact_selection_runs_only_selected_helper(self):
        self.args.select=['projects']
        with patch('configuration.ensure',side_effect=AssertionError('Unselected config')):
            self.assertEqual(self.run_checklist(),0)
        self.assertTrue(self.projects.is_dir());self.assertFalse((self.root/'.env').exists())

    def test_interrupted_second_step_resumes_without_rewriting_completed_config(self):
        native=bootstrap.layout
        def interrupted(target,**kwargs):
            if not kwargs.get('dry_run'):raise OSError('Fixture interruption')
            return native(target,**kwargs)
        with patch.object(bootstrap,'layout',side_effect=interrupted):
            with self.assertRaises(OSError):self.run_checklist()
        config=self.root/'.env';before=config.read_bytes();mtime=config.stat().st_mtime_ns
        self.assertFalse(self.projects.exists())
        self.assertEqual(self.run_checklist(),0)
        self.assertEqual(config.read_bytes(),before);self.assertEqual(config.stat().st_mtime_ns,mtime)
        self.assertFalse(self.state.exists())

    def test_validate_entire_selection_before_any_apply(self):
        self.projects.write_text('conflict')
        self.assertEqual(self.run_checklist(lambda *_:self.fail('Blocked selection requested approval')),3)
        self.assertFalse((self.root/'.env').exists());self.assertEqual(self.projects.read_text(),'conflict')

    def test_unknown_empty_duplicate_or_manual_selections_never_apply(self):
        for selected in (None,[],[''],['configuration,'],['configuration,configuration'],['drivers'],['configuration,drivers']):
            self.args.select=selected
            with self.assertRaises(ValueError):self.run_checklist()
        self.assertFalse((self.root/'.env').exists());self.assertFalse(self.projects.exists())

    def test_unsafe_configuration_is_blocked_without_disclosing_values(self):
        config=self.root/'.env';config.write_text('TOKEN=private-secret-fixture\n')
        self.assertEqual(self.run_checklist(),3)
        self.assertNotIn('private-secret-fixture',self.output.getvalue())
        self.assertFalse(self.projects.exists())
        config.unlink();config.symlink_to(self.home/'elsewhere')
        self.assertEqual(self.run_checklist(),3);self.assertFalse((self.home/'elsewhere').exists())

    def test_project_symlinks_are_blocked(self):
        elsewhere=self.home/'elsewhere';elsewhere.mkdir()
        self.projects.symlink_to(elsewhere,target_is_directory=True)
        self.assertEqual(self.run_checklist(),3)
        self.assertEqual(list(elsewhere.iterdir()),[]);self.assertFalse((self.root/'.env').exists())

    def test_removed_manual_entries_are_archived_and_survive_other_updates(self):
        self.state.mkdir(mode=0o700);path=self.state/'checklist.json'
        saved={'schema':1,'tasks':{'identity':'done','software':'skipped'}}
        path.write_text(json.dumps(saved));path.chmod(0o600);before=path.read_bytes()
        self.args.action='list';self.assertEqual(self.run_checklist(),0)
        result=json.loads(self.output.getvalue())
        self.assertEqual(result['archived_progress'],saved['tasks'])
        self.assertFalse({'identity','software'} & {row['id'] for row in result['tasks']})
        self.assertEqual(path.read_bytes(),before)
        self.args.action='done';self.args.value='theme';self.assertEqual(self.run_checklist(),0)
        self.assertEqual(checklist.read(path),{**saved['tasks'],'theme':'done'})
        self.args.value='identity'
        with self.assertRaisesRegex(ValueError,'developer git'):self.run_checklist()

    def test_review_never_prompts_for_replaced_entries(self):
        self.args.action='review'
        with patch('checklist.sys.stdin.isatty',return_value=True),patch('builtins.input',return_value='skipped') as ask:
            self.assertEqual(self.run_checklist(),0)
        self.assertEqual(ask.call_count,25)
        self.assertFalse({'identity','software'} & set(checklist.read(self.state/'checklist.json')))

    def test_cli_passes_effective_configuration_and_preserves_global_check(self):
        with patch.object(automation,'ROOT',self.root),patch.object(automation,'config',return_value=self.settings),patch.object(automation,'platform_info',return_value={}),patch.object(checklist,'main',return_value=0) as dispatch:
            self.assertEqual(automation.main(['checklist','automate','--select','projects','--dry-run']),0)
            self.assertEqual(dispatch.call_args.kwargs['settings'],self.settings)
            self.assertTrue(dispatch.call_args.args[0].dry_run)
        with patch.object(automation,'ROOT',self.root),patch.object(automation,'config',return_value=self.settings),patch.object(automation,'platform_info',return_value={'family':'debian'}),patch.object(checklist,'main') as dispatch,patch.object(automation,'lerd_compat',return_value=[]),patch.object(automation.providers,'capability',return_value={}),patch.object(automation,'conflicts',return_value={}):
            self.assertEqual(automation.main(['checklist','automate','--select','projects','--check']),0)
            dispatch.assert_not_called()
