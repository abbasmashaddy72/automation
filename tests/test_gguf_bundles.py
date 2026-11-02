"""Checksummed GGUF bundles, aggregate budgets, restart and legacy recovery."""
from argparse import Namespace
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ai'),str(ROOT/'lib')]
import gguf
import manager
import models
import services
import snapshots


class Bundles(unittest.TestCase):
    def setUp(self):
        from fixture_services import assume_systemctl
        assume_systemctl(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=self.root/'store';self.legacy=self.root/'old';self.files={};self.requests=[]
        self.value={'schema':1,'repository':'publisher/tiny','revision':'a'*40,'quantization':'Q4_K_M','files':[]}
        for index in (2,1):
            name=f'tiny-Q4_K_M-{index:05}-of-00002.gguf';data=b'GGUFfixture'+bytes([index]);url='https://example.invalid/'+name
            self.files[url]=data
            self.value['files'].append({'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'url':url})
        self.manifest=self.root/'bundle.json';self.manifest.write_text(json.dumps(self.value))
        env=patch.dict(os.environ,{'HOME':str(self.root),'XDG_CONFIG_HOME':str(self.root/'config'),'XDG_CACHE_HOME':str(self.root/'runtime')});env.start();self.addCleanup(env.stop)
        hardware=patch('gguf.ai_health.hardware',return_value={'available_memory_mib':4096});hardware.start();self.addCleanup(hardware.stop)
        network=patch('models.urllib.request.build_opener',return_value=Mock(open=self.open));network.start();self.addCleanup(network.stop)
        out=contextlib.redirect_stdout(io.StringIO());out.__enter__();self.addCleanup(out.__exit__,None,None,None)

    def open(self,request,timeout):
        self.requests.append(request.full_url)
        value=self.files[request.full_url]
        if isinstance(value,BaseException):raise value
        response=io.BytesIO(value);response.status=200;return response

    def download(self,**options):return gguf.download(self.store,self.value,yes=True,**options)

    def target(self):return snapshots.destination(gguf.bundle_root(self.store,self.value),gguf.validate(self.value)[1])

    def legacy_model(self):
        folder=self.legacy/'models'/'publisher--tiny--Q4_K_M';folder.mkdir(parents=True)
        for row in self.value['files']:(folder/row['path']).write_bytes(self.files[row['url']])
        (folder/gguf.MARKER).write_text(json.dumps({'directory':folder.name,'repository':self.value['repository'],'quantization':'Q4_K_M','files':[row['path'] for row in self.value['files']]}))
        (self.legacy/'config').mkdir();(self.legacy/'config/selected-model').write_text('publisher/tiny\n');(self.legacy/'config/runtime-settings').write_text('context=32768\n')
        return folder

    def test_download_validates_every_shard_and_selects_first_independent_of_order(self):
        self.assertEqual(self.download(),0);self.assertEqual(len(self.requests),2)
        path=gguf.resolve(self.store,self.value);self.assertTrue(path.name.endswith('00001-of-00002.gguf'))
        _,value=gguf.validate(self.value);self.assertEqual(snapshots.owned(self.target()),value)
        self.assertEqual(self.target().parent.parent.parent.name,'Q4_K_M')

    def test_verified_bundle_reuse_and_dryrun_never_send_network_requests(self):
        self.assertEqual(self.download(dry_run=True),0);self.assertFalse(self.store.exists());self.assertEqual(self.requests,[])
        self.assertEqual(gguf.download(self.store,self.value),4);self.assertFalse(self.store.exists())
        self.download();self.requests.clear();self.assertEqual(self.download(),0);self.assertEqual(self.requests,[])

    def test_partial_download_is_not_selectable_and_retry_reuses_verified_shard(self):
        second=self.value['files'][1]['url'];saved=self.files[second];self.files[second]=OSError('fixture failure')
        with self.assertRaises(OSError):self.download()
        self.assertFalse(self.target().exists())
        self.files[second]=saved;self.requests.clear();self.assertEqual(self.download(),0)
        self.assertEqual(self.requests,[second]);self.assertFalse(list(self.store.rglob('.download-*')))

    def test_checksum_or_header_failure_does_not_publish_a_bundle(self):
        first=self.value['files'][0]['url'];self.files[first]=b'wrong-content'
        with self.assertRaises(ValueError):self.download()
        self.assertFalse(self.target().exists())
        data=b'BAD!fixture\x02';self.files[first]=data
        self.value['files'][0].update(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        with self.assertRaises(ValueError):self.download()
        self.assertFalse(self.target().exists())

    def test_total_ram_and_disk_budgets_are_checked_before_any_download(self):
        value=copy.deepcopy(self.value)
        for row in value['files']:row['size']=200*1024**2
        with patch('gguf.ai_health.hardware',return_value={'available_memory_mib':600}),self.assertRaises(ValueError):gguf.download(self.store,value,yes=True)
        self.assertFalse(self.store.exists());self.assertEqual(self.requests,[])
        with patch('gguf.ai_health.hardware',return_value={'available_memory_mib':0,'memory_mib':10000}),self.assertRaises(ValueError):self.download()
        with patch('gguf.shutil.disk_usage',return_value=Namespace(free=64*1024**2)),self.assertRaises(ValueError):self.download()
        self.assertFalse(self.store.exists());self.assertEqual(self.requests,[])

    def test_unsafe_or_incomplete_bundle_manifests_are_rejected(self):
        values=[]
        for field,value in [('quantization','x/../y'),('revision','main')]:
            invalid=copy.deepcopy(self.value);invalid[field]=value;values.append(invalid)
        for key,value in [('url','http://example.invalid/model.gguf'),('url','https://example.invalid/model.gguf?token=secret'),('url','https://example.invalid/\nmodel.gguf'),('url',None),('size',True),('sha256','unverified'),('path','../tiny.gguf')]:
            invalid=copy.deepcopy(self.value);invalid['files'][0][key]=value;values.append(invalid)
        invalid=copy.deepcopy(self.value);invalid['files'].pop();values.append(invalid)
        invalid=copy.deepcopy(self.value);invalid['files'][0]['path']='other-00002-of-00002.gguf';values.append(invalid)
        for value in values:
            with self.subTest(value=value),self.assertRaises(ValueError):gguf.validate(value)
        for names in ([['unexpected']],['tiny.gguf','other.gguf'],['tiny.gguf','x-00001-of-00001.gguf']):
            with self.assertRaises(ValueError):gguf.series(names)
        self.assertEqual(self.requests,[])

    def test_single_file_does_not_require_a_quantization_in_its_filename(self):
        value=copy.deepcopy(self.value);value['files']=value['files'][:1];value['files'][0]['path']='fixture.gguf'
        self.assertEqual(gguf.validate(value)[1]['files'][0]['path'],'fixture.gguf')

    def test_inventory_marks_changed_or_incomplete_bundles_unverified(self):
        self.download();row=gguf.inventory(self.store)[0];self.assertEqual(row['status'],'verified')
        path=gguf.resolve(self.store,self.value);path.write_bytes(b'changed')
        self.assertEqual(gguf.inventory(self.store)[0]['status'],'unverified')
        with self.assertRaises(ValueError):gguf.resolve(self.store,self.value)

    def test_legacy_inventory_is_readonly_and_import_preserves_markers_selection_and_models(self):
        folder=self.legacy_model();before={p.name:p.read_bytes() for p in folder.iterdir()}
        data=gguf.legacy_inventory(self.legacy);self.assertEqual(data['selected_repository'],'publisher/tiny');self.assertEqual(data['context'],32768)
        self.assertIn('no deletion ownership',data['models'][0]['verification'])
        self.assertFalse(self.store.exists());self.assertEqual(gguf.import_legacy(self.store,self.value,self.legacy,yes=True),0)
        self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()});self.assertEqual(self.requests,[])
        self.assertFalse((folder/snapshots.RECEIPT).exists());self.assertTrue(gguf.resolve(self.store,self.value).is_file())

    def test_legacy_corruption_symlinks_executable_settings_and_mismatch_are_rejected(self):
        folder=self.legacy_model();settings=self.legacy/'config/runtime-settings';settings.write_text('context=$(evil)\n')
        with self.assertRaises(ValueError):gguf.legacy_inventory(self.legacy)
        settings.write_text('context=32768\n');marker=folder/gguf.MARKER;value=json.loads(marker.read_text());value['files'].pop();marker.write_text(json.dumps(value))
        with self.assertRaises(ValueError):gguf.import_legacy(self.store,self.value,self.legacy,yes=True)
        value['files']=[row['path'] for row in self.value['files']];marker.write_text(json.dumps(value))
        file=folder/value['files'][0];file.unlink();file.symlink_to(folder/value['files'][1])
        with self.assertRaises(ValueError):gguf.legacy_inventory(self.legacy)
        self.assertFalse(self.store.exists())

    def test_import_rejects_overlapping_tree_and_conflicting_independent_hashes(self):
        self.legacy_model()
        with self.assertRaises(ValueError):gguf.import_legacy(self.legacy/'copies',self.value,self.legacy,yes=True)
        wrong=copy.deepcopy(self.value);wrong['files'][0]['sha256']='f'*64
        with self.assertRaises(ValueError):gguf.import_legacy(self.store,wrong,self.legacy,yes=True)
        self.assertFalse(self.store.exists())

    def test_explicit_recovery_omits_corrupt_selection_state_without_editing_it(self):
        folder=self.legacy_model();selection=self.legacy/'config/selected-model';settings=self.legacy/'config/runtime-settings'
        selection.write_text('$(untrusted)\n');settings.write_text('context=$(untrusted)\n')
        with self.assertRaises(ValueError):gguf.import_legacy(self.store,self.value,self.legacy,yes=True)
        data=gguf.legacy_inventory(self.legacy,ignore_state=True)
        self.assertIsNone(data['selected_repository']);self.assertIsNone(data['context']);self.assertEqual(data['legacy_state'],'explicitly ignored')
        self.assertEqual(gguf.import_legacy(self.store,self.value,self.legacy,yes=True,ignore_state=True),0)
        self.assertEqual(selection.read_text(),'$(untrusted)\n');self.assertEqual(settings.read_text(),'context=$(untrusted)\n')
        self.assertTrue((folder/gguf.MARKER).exists())

    def test_select_recovers_alias_and_old_context_without_starting_or_changing_old_state(self):
        self.legacy_model();gguf.import_legacy(self.store,self.value,self.legacy,yes=True)
        exe=self.root/'llama-server';exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o700)
        args=Namespace(backend='llamacpp',action='gguf-select',manifest=self.manifest,root=str(self.store),legacy_root=self.legacy,
            model=None,quant=None,revision=None,model_alias=None,context=None,cpu_threads=None,cpu_quota=None,port=None,key_file=None,executable=str(exe),yes=True,dry_run=False)
        with patch('services.control',return_value=0) as control:self.assertEqual(gguf.main(args),0)
        value=services.read('llamacpp');self.assertEqual(value['context'],32768);self.assertEqual(value['model_alias'],'publisher/tiny:Q4_K_M')
        self.assertTrue(value['model'].endswith('00001-of-00002.gguf'))
        self.assertFalse(any(call.args[0] in ('start','restart','enable','disable','stop') for call in control.call_args_list))
        self.assertEqual((self.legacy/'config/selected-model').read_text(),'publisher/tiny\n')
        (self.legacy/'config/selected-model').write_text('other/model\n')
        with self.assertRaises(ValueError):gguf.main(args)

    def test_remove_requires_the_exact_reviewed_manifest_and_preserves_download_cache(self):
        self.download();args=Namespace(backend='llamacpp',action='gguf-remove',manifest=self.manifest,root=str(self.store),legacy_root=None,
            model=None,quant=None,revision=None,yes=True,dry_run=False)
        wrong=copy.deepcopy(self.value);wrong['files'][0]['sha256']='f'*64;self.manifest.write_text(json.dumps(wrong))
        with self.assertRaises(ValueError):gguf.main(args)
        self.assertTrue(self.target().exists());self.manifest.write_text(json.dumps(self.value))
        self.assertEqual(gguf.main(args),0);self.assertFalse(self.target().exists());self.assertTrue(list((self.store/'.downloads').rglob('*.gguf')))

    def test_cli_readonly_inventory_resolve_and_manifest_planning(self):
        self.legacy_model()
        for action,arguments in [('gguf-legacy-list',['--legacy-root',str(self.legacy)]),('gguf-list',['--root',str(self.store)]),
                                 ('gguf-download',['--manifest',str(self.manifest),'--root',str(self.store),'--dry-run'])]:
            result=subprocess.run(['bash',str(ROOT/'setup.sh'),'ai','llamacpp',action,*arguments],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.store.exists())

    def test_quota_is_validated_before_dispatch_or_prerequisite_installation(self):
        with patch('manager.subprocess.run') as run,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            manager.main(['llamacpp','configure','--cpu-quota','300x','--yes'])
        run.assert_not_called()

    def test_failed_activation_never_grants_ownership_of_a_concurrent_file(self):
        row=self.value['files'][0];cache=self.root/'single-download'
        def conflict(source,target,*args,**kwargs):
            Path(target).write_bytes(b'concurrent-user-model')
            raise FileExistsError('fixture concurrent activation')
        with patch('models.os.link',side_effect=conflict),self.assertRaises(FileExistsError):
            models.download(cache,row['path'],row['url'],row['sha256'],row['size'],yes=True)
        self.assertEqual((cache/row['path']).read_bytes(),b'concurrent-user-model')
        self.assertFalse((cache/(row['path']+'.receipt.json')).exists())
        with self.assertRaises(ValueError):models.remove(cache,row['path'],yes=True)

    def test_failed_receipt_commit_preserves_unowned_verified_bytes(self):
        row=self.value['files'][0];cache=self.root/'single-download'
        with patch('models.atomic_receipt',side_effect=OSError('fixture full disk')),self.assertRaises(OSError):
            models.download(cache,row['path'],row['url'],row['sha256'],row['size'],yes=True)
        self.assertEqual((cache/row['path']).read_bytes(),self.files[row['url']])
        self.assertFalse((cache/(row['path']+'.receipt.json')).exists())
        self.assertEqual(models.download(cache,row['path'],row['url'],row['sha256'],row['size'],yes=True),0)
        self.assertFalse((cache/(row['path']+'.receipt.json')).exists())

    def test_cached_bytes_still_require_a_valid_gguf_header(self):
        cache=self.root/'single-download';cache.mkdir();(cache/'bad.gguf').write_bytes(b'BAD!')
        with self.assertRaises(ValueError):models.download(cache,'bad.gguf','https://example.invalid/bad.gguf',hashlib.sha256(b'BAD!').hexdigest(),4,yes=True)
        self.assertEqual((cache/'bad.gguf').read_bytes(),b'BAD!');self.assertEqual(self.requests,[])

    def test_selection_refusal_dryrun_and_active_service_preserve_configuration(self):
        self.download();exe=self.root/'llama-server';exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o700)
        args=Namespace(backend='llamacpp',action='gguf-select',manifest=self.manifest,root=str(self.store),legacy_root=None,
            model=None,quant=None,revision=None,model_alias=None,context=None,cpu_threads=None,cpu_quota=None,port=None,key_file=None,executable=str(exe),yes=False,dry_run=False)
        with patch('services.control',return_value=0):
            self.assertEqual(gguf.main(args),4)
            config,_=services.paths('llamacpp');self.assertFalse(config.exists())
            args.dry_run=True;self.assertEqual(gguf.main(args),0);self.assertFalse(config.exists())
            args.dry_run=False;args.yes=True;self.assertEqual(gguf.main(args),0);before=config.read_bytes()
            args.context=32768;self.assertEqual(gguf.main(args),3);self.assertEqual(config.read_bytes(),before)


class UnifiedDownloadGuards(unittest.TestCase):
    def test_marker_only_gguf_never_grants_deletion_rights(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);asset=root/'tiny.gguf';asset.write_bytes(b'GGUFfixture')
            marker=root/'.llama-automation.json';marker.write_text('{}')
            with self.assertRaises((ValueError,OSError)):models.remove(root,'tiny.gguf',yes=True)
            self.assertEqual(asset.read_bytes(),b'GGUFfixture');self.assertEqual(marker.read_text(),'{}')

    def test_unpinned_unified_download_refuses_before_any_network_or_model_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'models'
            import manager
            with patch('models.urllib.request.build_opener') as download,contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                try:result=manager.main(['llamacpp','model-download','--root',str(root),'--model','tiny.gguf','--url','https://example.invalid/tiny.gguf','--yes'])
                except (ValueError,SystemExit):pass
                else:self.assertNotEqual(result,0)
                download.assert_not_called()
            self.assertFalse(root.exists())
