"""Provisioning failure/review contracts; host packages/services never touched."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from laravel_toolkit import provision,common

class ProvisioningContracts(unittest.TestCase):
    def args(self,*flags):
        with patch.object(provision,'provision',return_value=0) as call:provision.main(list(flags))
        return call.call_args.args[0]
    def fixture(self,root):
        osfile=root/'os-release';osfile.write_text('ID=ubuntu\nVERSION_ID="24.04"\n');return osfile
    def test_readonly_planning_and_invalid_database_never_invoke_installer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);osfile=self.fixture(root);args=self.args('--domain=example.test','--dry-run')
            calls=[]
            with contextlib.redirect_stdout(io.StringIO()),patch.object(provision,'available',return_value=False):
                self.assertEqual(provision.provision(args,command=lambda *a,**k:calls.append(a),os_path=osfile,system=root),0)
            self.assertEqual(calls,[]);self.assertFalse((root/'var').exists())
            args.database_name='bad-name'
            with self.assertRaises(ValueError):provision.provision(args,os_path=osfile,system=root)
    def test_service_repository_tls_ssh_approvals_fail_before_any_package_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);osfile=self.fixture(root)
            for flags in (['--yes'],['--yes','--tls-email=admin@example.test'],['--yes','--harden-ssh']):
                args=self.args('--domain=example.test',*flags)
                with contextlib.redirect_stdout(io.StringIO()),patch.object(provision.os,'geteuid',return_value=0),patch.object(provision,'apt') as apt:
                    with self.assertRaises(ValueError):provision.provision(args,os_path=osfile,system=root)
                    apt.assert_not_called()
    def test_external_download_failure_and_review_never_execute(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);osfile=self.fixture(root)
            args=self.args('--provision-url=https://example.com/script','--sha256='+'a'*64,'--check')
            with patch.object(common,'verified_script',side_effect=ValueError('fixture download failure')),patch.object(common,'run') as execute:
                with self.assertRaises(ValueError):provision.provision(args,os_path=osfile,system=root)
                execute.assert_not_called()
            args.check=False;args.yes=True
            with contextlib.redirect_stdout(io.StringIO()),patch.object(common,'verified_script',return_value=b'#!/bin/bash\ntrue\n'),patch.object(provision.os,'geteuid',return_value=0),patch.object(common,'private',side_effect=lambda value,**kw:value),patch.object(common,'lock',return_value=contextlib.nullcontext()):
                calls=[]
                self.assertEqual(provision.provision(args,command=lambda *a,**kw:calls.append(a),os_path=osfile,system=root),4)
                self.assertEqual(calls,[])
                state=root/'var/lib/automation-toolkit/laravel/external'/('a'*64+'.json')
                self.assertEqual(json.loads(state.read_text())['status'],'verified-awaiting-review')
    def test_invalid_or_forge_urls_never_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);osfile=self.fixture(root)
            for url in ('https://forge.laravel.com/x','http://example.test/x','https://secret:token@example.test/x'):
                args=self.args('--provision-url='+url,'--sha256='+'a'*64,'--yes')
                with patch.object(common,'verified_script') as fetch:
                    with self.assertRaises(ValueError):provision.provision(args,os_path=osfile,system=root)
                    fetch.assert_not_called()
