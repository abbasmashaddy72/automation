"""Model-copy and vLLM migration tests use temporary assets, homes and units only."""
from argparse import Namespace
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ai'),str(ROOT/'lib')]
import auth
import legacy
import manager
import services
import snapshots


class SnapshotMigration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'hub';self.store=self.root/'store';self.revision='a'*40
        env=patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.root/'config')});env.start();self.addCleanup(env.stop)
        self.repo='publisher/tiny';self.repo_dir=self.cache/'models--publisher--tiny'
        self.snapshot=self.repo_dir/'snapshots'/self.revision;self.snapshot.mkdir(parents=True)
        self.blobs=self.repo_dir/'blobs';self.blobs.mkdir()
        self.value={'schema':1,'repository':self.repo,'revision':self.revision,'files':[]}
        for name,data in [('config.json',b'{}'),('nested/tokenizer.json',b'{"fixture":true}'),('model.safetensors',b'model-fixture')]:
            sha=hashlib.sha256(data).hexdigest();blob=self.blobs/sha;blob.write_bytes(data)
            path=self.snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.symlink_to(os.path.relpath(blob,path.parent))
            self.value['files'].append({'path':name,'size':len(data),'sha256':sha})
        self.output=io.StringIO();redirect=contextlib.redirect_stdout(self.output);redirect.__enter__();self.addCleanup(redirect.__exit__,None,None,None)

    def copy(self,**kwargs):return snapshots.import_snapshot(self.store,self.value,cache=self.cache,yes=True,**kwargs)

    def target(self):return snapshots.destination(self.store,self.value)

    def test_inventory_is_revision_aware_readonly_and_counts_expected_blob_links(self):
        rows=snapshots.inventory(self.cache)
        self.assertEqual(rows[0]['revision'],self.revision);self.assertEqual(rows[0]['files'],3)
        self.assertEqual(rows[0]['bytes'],sum(row['size'] for row in self.value['files']))
        second=self.snapshot.parent/('b'*40);second.mkdir()
        (second/'config.json').symlink_to('../../blobs/'+self.value['files'][0]['sha256'])
        self.assertEqual(len(snapshots.inventory(self.cache)),2)
        self.assertFalse(self.store.exists());self.assertIn('no deletion rights',rows[0]['ownership'])
        self.assertEqual(snapshots.inventory(self.root/'absent'),[])

    def test_escape_cyclic_and_directory_symlinks_are_rejected(self):
        link=self.snapshot/'config.json';link.unlink();link.symlink_to(self.root/'outside')
        (self.root/'outside').write_text('private-data')
        with self.assertRaises(ValueError):snapshots.inventory(self.cache)
        link.unlink();link.symlink_to('config.json')
        with self.assertRaises(ValueError):snapshots.inventory(self.cache)
        link.unlink();link.symlink_to(self.blobs/self.value['files'][0]['sha256'])
        renamed=self.repo_dir/'snapshots-original';self.snapshot.parent.rename(renamed)
        (self.repo_dir/'snapshots').symlink_to(renamed,target_is_directory=True)
        with self.assertRaises(ValueError):snapshots.inventory(self.cache)

    def test_copy_is_private_independent_idempotent_and_preserves_original_cache(self):
        original={p.name:p.read_bytes() for p in self.blobs.iterdir()}
        self.assertEqual(self.copy(),0);target=self.target()
        self.assertEqual(target.stat().st_mode&0o777,0o700)
        for row in self.value['files']:
            path=target/row['path'];self.assertFalse(path.is_symlink());self.assertEqual(path.stat().st_nlink,1)
            self.assertNotEqual(path.stat().st_ino,(self.blobs/row['sha256']).stat().st_ino)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(snapshots.owned(target),self.value);self.assertEqual(self.copy(),0)
        self.assertEqual(original,{p.name:p.read_bytes() for p in self.blobs.iterdir()})
        self.assertFalse(list(self.store.glob('.snapshot-*')))

    def test_regular_legacy_gguf_directory_can_be_copied_without_adoption(self):
        source=self.root/'legacy-model';source.mkdir();(source/'tiny.gguf').write_bytes(b'GGUFfixture')
        row={'path':'tiny.gguf','size':11,'sha256':hashlib.sha256(b'GGUFfixture').hexdigest()}
        value={**self.value,'files':[row]}
        self.assertEqual(snapshots.import_snapshot(self.store,value,source=source,yes=True),0)
        self.assertTrue((source/'tiny.gguf').exists());self.assertFalse((source/snapshots.RECEIPT).exists())

    def test_malformed_manifest_paths_duplicates_checksums_and_shards_refused(self):
        row=self.value['files'][0]
        for files in ([{**row,'path':'../config.json'}],[{**row,'path':'x//config.json'}],[{**row,'path':'unsafe.py'}],
                      [row,row],[{**row,'size':True}],[{**row,'sha256':'unverified'}],
                      [{**row,'path':'model-00001-of-00002.safetensors'}]):
            with self.subTest(files=files),self.assertRaises(ValueError):snapshots.validate({**self.value,'files':files})
        with self.assertRaises(ValueError):snapshots.validate({**self.value,'revision':'main'})
        with self.assertRaises(ValueError):snapshots.validate({**self.value,'repository':'a--b/c'})

    def test_json_duplicate_fields_and_oversized_manifest_are_rejected(self):
        path=self.root/'manifest.json';path.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):snapshots.manifest(path)
        path.write_text(' '*262145)
        with self.assertRaises(ValueError):snapshots.manifest(path)
        path.write_text(json.dumps(self.value));self.assertEqual(snapshots.manifest(path),self.value)

    def test_dryrun_and_refusal_do_not_create_any_store(self):
        self.assertEqual(self.copy(dry_run=True),0);self.assertFalse(self.store.exists())
        self.assertEqual(snapshots.import_snapshot(self.store,self.value,cache=self.cache),4);self.assertFalse(self.store.exists())

    def test_invalid_source_checksum_or_disk_space_prevents_publication(self):
        row=self.value['files'][0];blob=self.blobs/row['sha256'];blob.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.store.exists());blob.write_bytes(b'{}')
        with patch('snapshots.shutil.disk_usage',return_value=Namespace(free=0)),self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.store.exists())

    def test_existing_empty_or_unmanaged_target_never_overwritten(self):
        self.store.mkdir(mode=0o700);target=self.target();target.mkdir(parents=True,mode=0o700)
        target.parent.chmod(0o700);target.parent.parent.chmod(0o700)
        with self.assertRaises((ValueError,FileNotFoundError)):self.copy()
        self.assertEqual(list(target.iterdir()),[])

    def test_source_change_during_copy_never_creates_a_valid_receipt(self):
        native=Path.open;changed=False
        def open_file(path,*args,**kwargs):
            nonlocal changed
            if args and args[0]=='xb' and not changed:
                changed=True;(self.blobs/self.value['files'][0]['sha256']).write_bytes(b'new-content')
            return native(path,*args,**kwargs)
        with patch.object(Path,'open',open_file),self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.target().exists());self.assertFalse(list(self.store.glob('.snapshot-*')))

    def test_source_overlap_and_public_or_symlink_store_are_rejected(self):
        with self.assertRaises(ValueError):snapshots.import_snapshot(self.cache/'copies',self.value,cache=self.cache,yes=True)
        self.store.mkdir(mode=0o755)
        with self.assertRaises(ValueError):self.copy()
        self.store.rmdir();self.store.symlink_to(self.root/'elsewhere')
        with self.assertRaises(ValueError):self.copy()

    def test_active_owned_service_prevents_removal_without_stopping_it(self):
        self.copy();config,unit=services.paths('vllm');config.parent.mkdir(parents=True);config.write_text('{}')
        unit.parent.mkdir(parents=True);unit.write_text('fixture-unit')
        with patch('services.owned',return_value=True),patch('services.read',return_value={'model':str(self.target())}),patch('subprocess.run',return_value=Namespace(returncode=0,stdout='active\n')) as run,self.assertRaises(ValueError):
            snapshots.remove_snapshot(self.store,self.repo,self.revision,yes=True)
        self.assertEqual(run.call_args.args[0][2],'show');self.assertTrue(self.target().exists())

    def test_caught_interruption_leaves_no_deletion_authority_and_no_cache_changes(self):
        native=os.link;count=0
        def interrupted(source,target,*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise KeyboardInterrupt()
            return native(source,target,*args,**kwargs)
        with patch('snapshots.os.link',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):self.copy()
        self.assertFalse((self.target()/snapshots.RECEIPT).exists());self.assertTrue((self.snapshot/'config.json').exists())
        with self.assertRaises((ValueError,FileNotFoundError)):snapshots.remove_snapshot(self.store,self.repo,self.revision,yes=True)
        self.assertFalse(list(self.store.glob('.snapshot-*')))

    def test_removal_only_observed_copy_and_never_original_cache(self):
        self.copy();target=self.target()
        self.assertEqual(snapshots.remove_snapshot(self.store,self.repo,self.revision,dry_run=True),0);self.assertTrue(target.exists())
        self.assertEqual(snapshots.remove_snapshot(self.store,self.repo,self.revision),4);self.assertTrue(target.exists())
        self.assertEqual(snapshots.remove_snapshot(self.store,self.repo,self.revision,yes=True),0)
        self.assertFalse(target.exists());self.assertEqual(len(snapshots.inventory(self.cache)),1)

    def test_unified_cli_inventory_copy_dryrun_and_owned_removal(self):
        manifest=self.root/'reviewed.json';manifest.write_text(json.dumps(self.value))
        def cli(*args):
            return subprocess.run(['bash',str(ROOT/'setup.sh'),'ai','vllm',*args],capture_output=True,text=True,timeout=30)
        listed=cli('cache-list','--cache-root',str(self.cache))
        self.assertEqual(listed.returncode,0,listed.stderr);self.assertEqual(json.loads(listed.stdout)[0]['revision'],self.revision)
        arguments=['snapshot-import','--cache-root',str(self.cache),'--manifest',str(manifest),'--root',str(self.store)]
        result=cli(*arguments,'--dry-run');self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(self.store.exists())
        result=cli(*arguments,'--yes');self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(self.target().exists())
        result=cli('snapshot-remove','--root',str(self.store),'--model',self.repo,'--revision',self.revision,'--yes')
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(self.target().exists());self.assertTrue(self.snapshot.exists())

    def test_later_edit_unknown_file_empty_directory_hardlink_and_symlink_prevent_removal(self):
        self.copy();target=self.target();asset=target/'config.json'
        for mutate,restore in (
            (lambda:asset.write_bytes(b'changed'),lambda:asset.write_bytes(b'{}')),
            (lambda:(target/'later.txt').write_text('user'),lambda:(target/'later.txt').unlink()),
            (lambda:(target/'later-dir').mkdir(),lambda:(target/'later-dir').rmdir()),
            (lambda:asset.chmod(0o644),lambda:asset.chmod(0o600)),
            (lambda:os.link(asset,self.root/'other-link'),lambda:(self.root/'other-link').unlink())):
            mutate()
            with self.assertRaises(ValueError):snapshots.remove_snapshot(self.store,self.repo,self.revision,yes=True)
            self.assertTrue(asset.exists());restore()
        asset.unlink();asset.symlink_to(self.blobs/self.value['files'][0]['sha256'])
        with self.assertRaises(ValueError):snapshots.remove_snapshot(self.store,self.repo,self.revision,yes=True)


class VllmSettingsMigration(unittest.TestCase):
    def setUp(self):
        from fixture_services import assume_systemctl
        assume_systemctl(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.root/'config'),'XDG_CACHE_HOME':str(self.root/'cache')});env.start();self.addCleanup(env.stop)
        self.unit=self.root/'config/systemd/user/vllm-local.service';self.unit.parent.mkdir(parents=True)
        self.exe=self.root/'vllm';self.exe.write_text('#!/bin/sh\nexit 0\n');self.exe.chmod(0o700)
        self.model=self.root/'model';self.model.mkdir();(self.model/'config.json').write_text('{}')
        self.text=(f'# Managed by 92-vllm-playground-setup.sh\n[Service]\nType=simple\nCPUQuota=200%\n'
            f'Environment=HF_HOME={self.root}/legacy-models\nEnvironment=HF_HUB_CACHE={self.root}/legacy-models/hub\n'
            f'Environment=VLLM_CACHE_ROOT={self.root}/legacy-runtime-cache\nEnvironment=VLLM_CPU_KVCACHE_SPACE=2\n'
            'Environment=VLLM_CPU_OMP_THREADS_BIND=nobind\nEnvironment=OMP_NUM_THREADS=3\nEnvironment=HF_HUB_DISABLE_TELEMETRY=1\n'
            f'ExecStart={self.exe} serve publisher/tiny --host 127.0.0.1 --port 18096 --dtype bfloat16 --max-model-len 512 '
            f'--download-dir {self.root}/legacy-models/hub --enable-auto-tool-choice --tool-call-parser hermes\n')
        self.unit.write_text(self.text);self.unit.chmod(0o600)
        self.args=Namespace(backend='vllm',action='legacy-import',legacy_unit=self.unit,model=str(self.model),executable=None,model_alias=None,
            key_file=None,cpu_quota=None,port=None,context=None,cpu_threads=None,dtype=None,kv_cache_gib=None,tool_parser=None,ignore_legacy_preload=False,yes=True,dry_run=False)

    def test_preserves_dtype_threads_quota_context_alias_and_tool_parser(self):
        value,_,_=legacy.parse(self.args)
        self.assertEqual(value['vllm_options'],{'dtype':'bfloat16','kv_cache_gib':2,'omp_bind':'nobind','tool_parser':'hermes'})
        self.assertEqual((value['context'],value['threads'],value['cpu_quota'],value['model_alias']),(512,3,200,'publisher/tiny'))
        with patch.dict(os.environ,{'VLLM_API_KEY':'stale-secret','VLLM_PLUGINS':'unreviewed','VLLM_CPU_KVCACHE_SPACE':'999','HF_HOME':'/external-cache'}):
            command,env=services.invocation(value)
        self.assertIn('bfloat16',command);self.assertIn('publisher/tiny',command);self.assertIn('hermes',command)
        self.assertNotIn('VLLM_API_KEY',env);self.assertEqual(env['VLLM_PLUGINS'],'');self.assertEqual(env['VLLM_CPU_KVCACHE_SPACE'],'2')
        self.assertEqual(env['OMP_NUM_THREADS'],'3');self.assertEqual(env['VLLM_CPU_OMP_THREADS_BIND'],'nobind')
        self.assertEqual(env['HF_HUB_OFFLINE'],'1');self.assertNotEqual(env['HF_HOME'],'/external-cache')
        self.assertFalse((self.root/'cache').exists())

    def test_import_configures_new_unit_without_changing_old_unit_cache_or_services(self):
        original=self.unit.read_bytes()
        with patch('legacy.subprocess.run',return_value=Namespace(returncode=0,stdout='ActiveState=inactive\nUnitFileState=disabled\n')),patch('services.control',return_value=0),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(legacy.main(self.args),0)
        value=services.read('vllm');self.assertEqual(value['vllm_options']['dtype'],'bfloat16')
        self.assertEqual(self.unit.read_bytes(),original);self.assertFalse((self.root/'legacy-models').exists());self.assertFalse((self.root/'cache').exists())

    def test_private_key_import_is_compared_without_source_execution_or_logging(self):
        source=self.root/'legacy/key.env';source.parent.mkdir(mode=0o700);secret='sk-local-'+'k'*40;source.write_text('VLLM_API_KEY='+secret);source.chmod(0o600)
        key=self.root/'private/api-key';auth.save(key,secret);self.args.key_file=key
        self.unit.write_text(self.text+'EnvironmentFile='+str(source)+'\n')
        self.args.action='legacy-plan'
        with contextlib.redirect_stdout(io.StringIO()) as out:self.assertEqual(legacy.main(self.args),0)
        self.assertNotIn(secret,out.getvalue());self.assertTrue(source.exists())
        source.write_text('VLLM_API_KEY='+'x'*40)
        with self.assertRaises(ValueError):legacy.parse(self.args)
        source.write_text('VLLM_API_KEY=$(evil)')
        with self.assertRaises(ValueError):legacy.parse(self.args)

    def test_unknown_environment_preload_missing_local_model_and_partial_tool_flags_refused(self):
        for text in (self.text+'Environment=PYTHONPATH=/evil\n',self.text+'Environment=VLLM_CPU_OMP_THREADS_BIND=0-999\n',
                     self.text.replace('--tool-call-parser hermes',''),self.text+'Environment=LD_PRELOAD=/unreviewed.so\n',
                     self.text+'Environment=VLLM_CACHE_ROOT=$(evil)\n'):
            self.unit.write_text(text)
            with self.assertRaises(ValueError):legacy.parse(self.args)
        self.unit.write_text(self.text);self.args.model=None
        with self.assertRaises(ValueError):legacy.parse(self.args)
        self.args.model=str(self.model);self.unit.write_text(self.text+'Environment=LD_PRELOAD=/unreviewed.so\n');self.args.ignore_legacy_preload=True
        value,_,_=legacy.parse(self.args);_,env=services.invocation(value)
        self.assertNotIn('LD_PRELOAD',env)

    def test_runtime_cache_created_only_by_approved_runtime_preparation(self):
        value,_,_=legacy.parse(self.args);services.invocation(value)
        self.assertFalse((self.root/'cache').exists())
        services.prepare_runtime(value);path=services.runtime_cache();self.assertEqual(path.stat().st_mode&0o777,0o700)

    def test_options_are_backend_specific_and_strictly_allowlisted(self):
        value,_,_=legacy.parse(self.args)
        for options in ({'dtype':'$(exec)'},{'kv_cache_gib':True},{'kv_cache_gib':65},{'tool_parser':'remote-plugin'},{'env':{'VLLM_API_KEY':'secret'}}):
            with self.assertRaises(ValueError):services.validate({**value,'vllm_options':options})


class UnreceiptedDeletionRefusal(unittest.TestCase):
    def test_markerless_model_store_never_grants_deletion_or_service_control(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'external';revision='a'*40
            target=root/'publisher'/'tiny'/revision
            for path in (root,root/'publisher',root/'publisher'/'tiny',target):path.mkdir(mode=0o700)
            model=target/'config.json';model.write_text('{}');before=model.read_bytes()
            with patch('services.control') as control,self.assertRaises((ValueError,OSError)):
                snapshots.remove_snapshot(root,'publisher/tiny',revision,yes=True)
            control.assert_not_called();self.assertEqual(model.read_bytes(),before)
