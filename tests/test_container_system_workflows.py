"""Disposable workflow completion requires observed fixture teardown."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import container_workflows

class ContainerWorkflowCompletion(unittest.TestCase):
    def probe(self,exists,output=None):
        calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            code=exists if argv[1:3]==['container','exists'] else 0
            return subprocess.CompletedProcess(argv,code,stdout=('BOOTSTRAP=yes\nPLAN=yes\nGIT_INSTALL_VERIFIED=yes\nREPEAT_INSTALL=yes\nUNAVAILABLE_EXIT=5\nUNPRIVILEGED_SYSTEM_REGRESSIONS=yes\nCHECKLIST_AUTOMATION=yes\n' if output is None else output),stderr='')
        with patch.object(container_workflows.subprocess,'run',side_effect=run):
            report=container_workflows.probe('ubuntu',source=Path('/fixture'),with_system_tests=True)
        return report,calls
    def test_success_requires_container_absence(self):
        report,calls=self.probe(1)
        self.assertEqual(report['status'],'pass');self.assertTrue(report['teardown'])
        command=next(row for row in calls if row[1]=='run')
        self.assertIn('AUTOMATION_WORKFLOW_SYSTEM_TESTS=yes',command)
        self.assertIn('type=bind,src=/fixture,dst=/toolkit,readonly',command)
    def test_running_or_unknown_fixture_is_a_failure(self):
        for code in (0,125):
            report,_=self.probe(code)
            self.assertEqual(report['status'],'fail');self.assertFalse(report['teardown'])
            self.assertEqual(report['reason'],'fixture_teardown_incomplete')

    def test_locked_engine_query_fails_without_pulling_or_starting(self):
        with patch.object(container_workflows.subprocess,'run',side_effect=subprocess.TimeoutExpired('podman',30)) as run:
            report=container_workflows.probe('ubuntu',allow_pull=True)
        self.assertEqual(report['status'],'fail');self.assertEqual(report['reason'],'engine_query_failed')
        self.assertEqual(run.call_count,1)

    def test_success_exit_without_requested_checks_is_a_failure(self):
        report,_=self.probe(1,output='exited without running the selected tests')
        self.assertEqual(report['status'],'fail');self.assertEqual(report['reason'],'requested_checks_missing')
        self.assertTrue(report['teardown'])
    def test_success_requires_actual_checklist_smoke_marker(self):
        report,_=self.probe(1,output='BOOTSTRAP=yes\nPLAN=yes\nGIT_INSTALL_VERIFIED=yes\nREPEAT_INSTALL=yes\nUNAVAILABLE_EXIT=5\nUNPRIVILEGED_SYSTEM_REGRESSIONS=yes\n')
        self.assertEqual(report['status'],'fail');self.assertFalse(report['checks']['checklist_automation'])
    def test_unsupported_selected_integration_is_rejected_before_engine_calls(self):
        import contextlib,io
        with patch.object(container_workflows.subprocess,'run') as run,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                container_workflows.main(['--allow-install','--skip-package-smoke','--with-lint','--containers','arch','--output','/not-created'])
        self.assertEqual(result.exception.code,2);run.assert_not_called()
