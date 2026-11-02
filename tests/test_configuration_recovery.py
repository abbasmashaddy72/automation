"""Configuration and recovery regression contracts: Lerd overlap, settings, trust and recovery."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'lib'))
import automation as a
import catalog
import discovery


class LerdSelectionTests(unittest.TestCase):
    def args(self, selection):
        return argparse.Namespace(select=[selection], exclude=None, interactive=False,
            yes=True, non_interactive=True, dry_run=True, command='packages', action='install',
            replace=[], allow_standalone_dev=False)
    def info(self):
        return dict(family='debian',manager='apt-get',desktop=True,arch='x86_64',
                    init='systemd',user_systemd=True,wsl=False,container=False)
    def test_lerd_selected_removes_standalone_servers_but_not_tools(self):
        with patch.object(a,'installed',return_value=False), patch.object(a,'available',return_value=True), \
             patch.object(a,'lerd_compat',return_value=[]), patch.object(a,'run',return_value=0) as run, \
             patch.object(a,'lerd_action',return_value=0):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc=a.packages_action(self.args('lerd,php,mariadb,redis,nginx,composer,nodejs,npm,nvm,git,dbeaver'),self.info(),{})
            self.assertIn(rc,(0,5))  # DBeaver requires a real, verified package source
            self.assertIn('Managed by Lerd',out.getvalue())
            command=' '.join(str(x) for call in run.call_args_list for x in call.args[0])
            self.assertIn('git',command)
            for name in ('php','mariadb','redis','nginx','composer','nodejs','npm','nvm'):
                self.assertNotIn(name,command)
    def test_explicit_override_can_select_standalone(self):
        with patch.object(a,'installed',return_value=False), patch.object(a,'available',return_value=True), \
             patch.object(a,'lerd_compat',return_value=[]), patch.object(a,'run',return_value=0) as run, \
             patch.object(a,'lerd_action',return_value=0):
            args=self.args('lerd,mariadb');args.allow_standalone_dev=True
            with contextlib.redirect_stdout(io.StringIO()):
                a.packages_action(args,self.info(),{})
            self.assertIn('mariadb',' '.join(run.call_args.args[0]))
    def test_unsupported_lerd_does_not_suppress_standalone(self):
        with patch.object(a,'installed',return_value=False), patch.object(a,'available',return_value=True), \
             patch.object(a,'lerd_compat',return_value=['systemd required']),patch.object(a,'run',return_value=0) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                a.packages_action(self.args('lerd,mariadb'),self.info(),{})
            self.assertIn('mariadb-server',run.call_args.args[0])
    def test_lerd_services_list_is_explicit(self):
        for name in ('php','php-fpm','mariadb','mysql-server','postgresql-server','redis','nginx','apache2','composer'):
            self.assertIn(name,catalog.LERD_MANAGED)


class IdentityTests(unittest.TestCase):
    def test_chromium_not_verified_google_chrome(self):
        suggestions=discovery.rank('google-chrome',[{'package':'chromium','source':'native','description':'browser'}])
        self.assertTrue(all(item.get('identity')!='verified-same-product' for item in suggestions))
    def test_unrelated_replacement_never_claimed_identical(self):
        s=discovery.rank('visual-studio-code-bin',[{'package':'codium','source':'native','description':'VSCodium'}])
        self.assertTrue(all(x['identity']!='verified-same-product' for x in s))


class SettingsTests(unittest.TestCase):
    def test_reject_incorrect_boolean(self):
        with self.assertRaises(ValueError):
            a.validate_settings({'AUTOMATION_LERD':'maybe'})
    def test_reject_bad_port_and_context(self):
        for conf in ({'AUTOMATION_AI_PORT':'0'}, {'AUTOMATION_AI_PORT':'65536'}, {'AUTOMATION_AI_CONTEXT':'2'}, {'AUTOMATION_AI_QUOTA':'banana'}):
            with self.subTest(conf=conf), self.assertRaises(ValueError): a.validate_settings(conf)
    def test_accepted_settings(self):
        a.validate_settings({'AUTOMATION_AI_PORT':'8094','AUTOMATION_AI_CONTEXT':'32768','AUTOMATION_AI_QUOTA':'300%',
                             'AUTOMATION_RETRIES':'2','AUTOMATION_NONINTERACTIVE':'true'})


class PatchTrustTests(unittest.TestCase):
    def test_local_unsigned_updates_and_optional_strict_policy(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        import patch_manager as p
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('manifest.json',json.dumps({'format':1,'operations':[]}))
            with zipfile.ZipFile(path) as z:
                with self.assertRaises(ValueError):p.verify_authenticity(z,allow_unsigned=False,trust_keys=[])
                self.assertEqual(p.verify_authenticity(z,trust_keys=[]),'local-checksums-only')




class SignedPatchTests(unittest.TestCase):
    @unittest.skipUnless(__import__('shutil').which('openssl'),'OpenSSL required')
    def test_signature_roundtrip_and_tamper_detection(self):
        import subprocess
        sys.path.insert(0,str(ROOT/'scripts'))
        import patch_manager as p
        with tempfile.TemporaryDirectory() as tmp:
            private,public=Path(tmp)/'private.pem',Path(tmp)/'public.pem'
            subprocess.run(['openssl','genpkey','-algorithm','ed25519','-out',str(private)],
                           capture_output=True,check=True)
            subprocess.run(['openssl','pkey','-in',str(private),'-pubout','-out',str(public)],
                           capture_output=True,check=True)
            manifest=b'{"format": 1, "operations": []}\n'
            msg,sig=Path(tmp)/'manifest',Path(tmp)/'sig'
            msg.write_bytes(manifest)
            subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(private),'-rawin',
                            '-in',str(msg),'-out',str(sig)],capture_output=True,check=True)
            archive=Path(tmp)/'signed.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('manifest.json',manifest)
                z.writestr('signature.ed25519',sig.read_bytes())
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(p.verify_authenticity(z,trust_keys=[public]),'signed-and-verified')
                with self.assertRaises(ValueError):p.verify_authenticity(z,trust_keys=[])
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('manifest.json',b'{"format": 1, "operations": [ ]}\n')
                z.writestr('signature.ed25519',sig.read_bytes())
            with zipfile.ZipFile(archive) as z:
                with self.assertRaises(ValueError):
                    p.verify_authenticity(z,trust_keys=[public],allow_unsigned=True)


class JournalTests(unittest.TestCase):
    def test_private_recovery_receipt(self):
        import journal
        with tempfile.TemporaryDirectory() as tmp:
            location=str(Path(tmp)/'state')
            journal.write('started',directory=location,session='x',packages=['git'])
            journal.write('action',directory=location,session='x',packages=['git'],source='apt-get',result=1)
            journal.write('failed',directory=location,session='x',result=1)
            receipt=Path(location)/'install-journal.jsonl'
            self.assertEqual(receipt.stat().st_mode & 0o777,0o600)
            self.assertEqual(journal.status(directory=location)['latest']['event'],'failed')
            self.assertIn('does NOT undo',journal.status(directory=location)['note'])

    def test_refuse_symlinked_state_directory(self):
        import journal
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target';target.mkdir()
            link=Path(tmp)/'link';link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError): journal.state_dir(str(link))


if __name__ == '__main__': unittest.main()
