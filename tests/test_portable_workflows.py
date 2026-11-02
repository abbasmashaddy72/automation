"""Portable workflows regression contracts: portable, offline and explicitly non-destructive."""
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import automation
import bootstrap
import extensions
import workflows


class PortableWorkflows(unittest.TestCase):
    def test_profile_roundtrip_and_forbidden_keys(self):
        with tempfile.TemporaryDirectory() as td:
            source = pathlib.Path(td) / 'developer.json'
            payload = workflows.profile_data({'AUTOMATION_PROFILE': 'minimal', 'AUTOMATION_AI_PORT': '8094',
                                              'PASSWORD': 'SECRET', 'AUTOMATION_STATE_DIR': '/private'})
            workflows.write_json(source, payload)
            self.assertNotIn('SECRET', source.read_text())
            with patch('workflows.journal.state_dir', return_value=pathlib.Path(td)):
                imported = workflows.import_profile(source, '', automation.validate_settings)
                self.assertEqual(workflows.saved_profile('developer', '', automation.validate_settings)['AUTOMATION_AI_PORT'], '8094')
                self.assertEqual(workflows.list_profiles(''), ['developer'])
                self.assertEqual(imported.stat().st_mode & 0o077, 0)
                self.assertRaises(ValueError, workflows.import_profile, source, '', automation.validate_settings)
            payload['settings']['AUTOMATION_STATE_DIR'] = '/etc'
            self.assertRaises(ValueError, workflows.validate_profile, payload, automation.validate_settings)

    def test_profile_rejects_malicious_settings(self):
        for obj in ({'schema':2,'type':'automation-profile','settings':{}},
                    {'schema':1,'type':'automation-profile','settings':{'AUTOMATION_AI_CONTEXT':'$(evil)'}},
                    {'schema':1,'type':'automation-profile','settings':{'AUTOMATION_LERD':'maybe'}}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError): workflows.validate_profile(obj, automation.validate_settings)

    def test_no_overwrite_or_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            target=pathlib.Path(td)/'p.json'
            workflows.write_json(target, workflows.profile_data({}))
            with self.assertRaises(ValueError): workflows.write_json(target, {})
            link=pathlib.Path(td)/'link.json'; link.symlink_to(target)
            with self.assertRaises(ValueError): workflows.write_json(link, {})

    def test_plan_is_machine_readable_without_secrets(self):
        data=workflows.plan_data({'id':'arch','family':'arch','arch':'x86_64','version':'1','manager':'pacman', 'token':'secret'},
                                 [{'name':'git','status':'available','actual':'git','source':'pacman','suggestions':['do not include']}])
        self.assertEqual(workflows.validate_plan(data)[0]['name'], 'git')
        self.assertNotIn('secret', json.dumps(data))
        with self.assertRaises(ValueError): workflows.validate_plan({'type':'automation-plan', 'schema':1,'packages':[{'name':'x;rm -rf /','status':'available'}]})

    def test_offline_receipts_detect_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); cache=root/'cache';cache.mkdir()
            plan=root/'plan.json'; manifest=root/'offline.json'
            workflows.write_json(plan, workflows.plan_data({'family':'debian'},
                                 [{'name':'git','status':'available','source':'apt-get','actual':'git'}]))
            archive=cache/'git_2.0_amd64.deb';archive.write_bytes(b'package test artifact')
            row=workflows.prepare_offline(plan, cache, manifest, ['git=git_2.0_amd64.deb'])
            self.assertEqual(row['artifacts'][0]['status'],'verified-local')
            self.assertTrue(workflows.verify_offline(manifest, cache)['ok'])
            archive.write_bytes(b'tampered')
            self.assertEqual(workflows.verify_offline(manifest, cache)['mismatched'],['git_2.0_amd64.deb'])
            with self.assertRaises(ValueError): workflows.prepare_offline(plan,cache,root/'bad.json',['git=../passwd'])
            with self.assertRaises(ValueError): workflows.prepare_offline(plan,cache,root/'bad.json',['other=git_2.0_amd64.deb'])

    def test_offline_uncached_is_partial_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); cache=root/'cache';cache.mkdir()
            plan=root/'plan.json'; manifest=root/'manifest.json'
            workflows.write_json(plan,workflows.plan_data({'family':'debian'},
                [{'name':'git','status':'available','source':'apt-get','actual':'git'}]))
            workflows.prepare_offline(plan,cache,manifest)
            report=workflows.verify_offline(manifest,cache)
            self.assertTrue(report['integrity_ok'])
            self.assertFalse(report['complete'])
            self.assertFalse(report['ok'])
            self.assertEqual(report['not_cached'],['git'])

    def test_offline_rejects_wrong_distro_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);cache=root/'cache';cache.mkdir()
            (cache/'git.rpm').write_bytes(b'test')
            plan=root/'plan.json';workflows.write_json(plan,workflows.plan_data({'family':'debian'},
                [{'name':'git','status':'available','source':'apt-get','actual':'git'}]))
            self.assertRaises(ValueError,workflows.prepare_offline,plan,cache,root/'manifest.json',['git=git.rpm'])

    def test_offline_rejects_symlink_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); cache=root/'cache';cache.mkdir()
            actual=root/'actual.deb';actual.write_bytes(b'real')
            (cache/'fake.deb').symlink_to(actual)
            plan=root/'plan.json'; workflows.write_json(plan,workflows.plan_data({}, [{'name':'git','status':'available','source':'apt-get','actual':'git'}]))
            with self.assertRaises(ValueError): workflows.prepare_offline(plan,cache,root/'manifest.json',['git=fake.deb'])

    def test_provider_is_declarative_and_rejects_commands(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'provider.json'
            payload={'schema':1,'id':'mytools','packages':{'editor':{'arch':'vim','debian':'vim'}}}
            workflows.write_json(path,payload)
            plugin=extensions.read_provider(path)
            self.assertEqual(extensions.resolve(plugin,['editor'],'debian'),['vim'])
            self.assertRaises(ValueError,extensions.resolve,plugin,['editor'],'alpine')
            payload['command']='curl | bash'
            path.unlink();workflows.write_json(path,payload)
            self.assertRaises(ValueError,extensions.read_provider,path)

    def test_project_bootstrap_no_existing_path_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            dest=pathlib.Path(td)/'myapp'
            preview=bootstrap.create('python',dest,dry_run=True)
            self.assertFalse(dest.exists())
            self.assertFalse(preview['created'])
            result=bootstrap.create('python',dest)
            self.assertTrue((dest/'tests/test_smoke.py').exists())
            self.assertTrue(result['created'])
            self.assertRaises(ValueError,bootstrap.create,'python',dest)
            self.assertRaises(ValueError,bootstrap.create,'laravel',pathlib.Path(td)/'laravel')

    def test_static_dashboard_escapes_untrusted_data(self):
        doc=workflows.dashboard_html({'<script>':{'package':'<img src=x onerror=alert(1)>','source':'native'}},
                                      {'latest':{'event':'<iframe>'}})
        self.assertNotIn('<script>',doc)
        self.assertNotIn('<iframe>',doc)
        self.assertIn('&lt;script&gt;',doc)
        self.assertIn('Content-Security-Policy',doc)
        self.assertNotIn('https://',doc)

    def test_profile_configuration_precedence(self):
        from argparse import Namespace
        args=Namespace(non_interactive=False,no_lerd=False,enable_aur=False,prefer_flatpak=False,
                       prefer_shelly=False,no_auto_search=False,profile='minimal',saved_profile='team')
        with patch('automation.config_file',return_value={'AUTOMATION_PROFILE':'developer', 'AUTOMATION_LERD':'false'}), \
             patch('automation.workflows.saved_profile',return_value={'AUTOMATION_PROFILE':'default','AUTOMATION_LERD':'true'}), \
             patch.dict('os.environ',{'AUTOMATION_PROFILE':'developer'},clear=True):
            settings=automation.config(args)
            self.assertEqual(settings['AUTOMATION_PROFILE'],'minimal')  # CLI beats environment
            self.assertEqual(settings['AUTOMATION_LERD'],'false')       # .env beats imported profile

    def test_provider_forbids_reserved_backends(self):
        with tempfile.TemporaryDirectory() as td:
            for value in ('lerd','ai-ollama'):
                path=pathlib.Path(td)/'provider.json'
                payload={'schema':1,'id':'test','packages':{'service':{'debian':value}}}
                if path.exists(): path.unlink()
                workflows.write_json(path,payload)
                self.assertRaises(ValueError,extensions.read_provider,path)

    def test_cli_profile_plan_provider_and_bootstrap_flow(self):
        import os, shutil, subprocess
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            # Exercise saved-profile defaults in a clean checkout. A contributor's
            # local .env intentionally overrides imported profile settings.
            checkout=root/'toolkit'
            checkout.mkdir()
            shutil.copy2(ROOT/'setup.sh',checkout/'setup.sh')
            for directory in ('lib','ai','scripts','config'):
                shutil.copytree(ROOT/directory,checkout/directory,
                                ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            state=root/'state'
            env={key:value for key,value in os.environ.items() if not key.startswith('AUTOMATION_')}
            env.update(AUTOMATION_STATE_DIR=str(state),PYTHONDONTWRITEBYTECODE='1')
            def cli(*args):
                return subprocess.run(['bash',str(checkout/'setup.sh'),*args],capture_output=True,text=True,env=env)
            source=root/'team.json'
            r=cli('profiles','export',str(source),'--select','git','--profile','minimal')
            self.assertEqual(r.returncode,0,r.stderr)
            r=cli('profiles','import',str(source))
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual((state/'profiles/team.json').stat().st_mode & 0o077,0)
            r=cli('packages','plan','--saved-profile','team','--no-auto-search','--output',str(root/'plan.json'))
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertFalse((root/'plan.json').exists())
            r=cli('packages','export','--saved-profile','team','--no-auto-search','--output',str(root/'plan.json'))
            self.assertEqual(r.returncode,0,r.stderr)
            plan=workflows.read_json(root/'plan.json')
            self.assertEqual(plan['packages'][0]['name'],'git')
            r=cli('providers','plan',str(ROOT/'tests/fixtures/providers/native_tools.json'),'--select','git-client')
            self.assertEqual(r.returncode,0,r.stderr)
            r=cli('projects','init','node',str(root/'newapp'),'--dry-run')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertFalse((root/'newapp').exists())
            r=cli('projects','init','node',str(root/'newapp'),'--yes')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue((root/'newapp/package.json').exists())
            r=cli('dashboard','export',str(root/'dashboard.html'))
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual((root/'dashboard.html').stat().st_mode & 0o077,0)

    def test_cli_prints_workflow_help(self):
        import subprocess
        p=subprocess.run(['bash',str(ROOT/'setup.sh'),'--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0)
        for term in ('profiles','offline','projects','providers','dashboard','--saved-profile','--output'):
            self.assertIn(term,p.stdout)


if __name__=='__main__': unittest.main()
