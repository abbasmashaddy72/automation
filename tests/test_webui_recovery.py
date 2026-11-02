"""Receipt recovery and data preservation; no real engine or app state is touched."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import webui


class Engine:
    image='ghcr.io/open-webui/open-webui@sha256:'+'a'*64
    def __init__(self):
        self.row=None; self.volume=None; self.calls=[]; self.sequence=0; self.fail_run=False
    def inspect(self,kind,name):
        if kind=='image':return {'Id':'e'*64}
        if kind=='volume':return self.volume
        if self.row is not None and name in (webui.NAME,self.row['Id']):return self.row
        return None
    def call(self,command,**kwargs):
        self.calls.append(command)
        if command[0]=='info':return subprocess.CompletedProcess(command,0,'true','')
        if command[:2]==['volume','create']:
            self.volume={'CreatedAt':'2026-11-02T12:00:00Z','Labels':{webui.LABEL:command[command.index('--label')+1].split('=',1)[1]},'fixture_data':'keep'}
        elif command[0]=='run':
            if self.fail_run:return subprocess.CompletedProcess(command,125,'','fixture creation failure')
            self.sequence+=1
            self.row={'Id':f'{self.sequence:064x}','Config':{'Labels':{webui.LABEL:command[command.index('--label')+1].split('=',1)[1]},'Image':self.image},
                'Mounts':[{'Name':webui.VOLUME,'Destination':'/app/backend/data'}], 'State':{'Running':True}}
            return subprocess.CompletedProcess(command,0,self.row['Id'],'')
        elif command[0]=='stop':self.row['State']['Running']=False
        elif command[0]=='start':self.row['State']['Running']=True
        elif command[0]=='rm':self.row=None
        else:raise AssertionError(command)
        return subprocess.CompletedProcess(command,0,'','')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.state=Path(temp.name)/'state'
        def state_dir(*,create=True):
            if create:self.state.mkdir(mode=0o700,exist_ok=True)
            return self.state
        self.engine=Engine()
        for manager in (patch('webui.os.geteuid',return_value=1000),patch('webui.shutil.which',return_value='/usr/bin/podman'),
                patch('webui.journal.state_dir',side_effect=state_dir),patch('webui.inspect',side_effect=self.engine.inspect),
                patch('webui.call',side_effect=self.engine.call)):
            manager.start();self.addCleanup(manager.stop)
    def main(self,*args):
        with contextlib.redirect_stdout(io.StringIO()):return webui.main(list(args))
    def install(self):return self.main('install','--image',self.engine.image,'--yes')
    def removed(self):
        self.install();self.main('stop','--yes');self.main('remove','--yes')

    def test_failed_creation_preserves_intent_and_data_then_recovers_without_volume_recreation(self):
        self.engine.fail_run=True
        self.assertEqual(self.install(),125)
        self.assertIsNone(webui.receipt());self.assertIsNotNone(webui.pending())
        volume=self.engine.volume
        self.engine.fail_run=False
        self.assertEqual(self.main('recover','--yes'),0)
        self.assertIs(self.engine.volume,volume);self.assertIsNone(webui.pending())
        self.assertEqual(sum(cmd[:2]==['volume','create'] for cmd in self.engine.calls),1)

    def test_interruption_before_receipt_publication_recovers_observed_container_without_relaunch(self):
        writer=webui.write_metadata
        def interrupt(path,value,**kwargs):
            if path==webui.receipt_path():raise InterruptedError('fixture interruption')
            writer(path,value,**kwargs)
        with patch('webui.write_metadata',side_effect=interrupt),self.assertRaises(InterruptedError):self.install()
        identifier=self.engine.row['Id'];pending=webui.pending_path().read_bytes()
        self.assertEqual(self.main('recover','--dry-run'),0)
        self.assertEqual(webui.pending_path().read_bytes(),pending);self.assertIsNone(webui.receipt())
        self.assertEqual(self.main('recover'),4)
        self.assertEqual(self.main('recover','--yes'),0)
        self.assertEqual(webui.receipt()['id'],identifier)
        self.assertEqual(sum(cmd[0]=='run' for cmd in self.engine.calls),1)

    def test_recovery_cleans_intent_after_interrupted_cleanup_of_committed_receipt(self):
        unlink=Path.unlink
        def interrupt(path,*args,**kwargs):
            if path==webui.pending_path():raise InterruptedError('fixture cleanup interruption')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupt),self.assertRaises(InterruptedError):self.install()
        before=webui.receipt_path().read_bytes()
        self.assertIsNotNone(webui.pending())
        self.assertEqual(self.main('recover','--yes'),0)
        self.assertEqual(webui.receipt_path().read_bytes(),before);self.assertIsNone(webui.pending())

    def test_explicit_recreate_preserves_volume_image_and_private_previous_receipt(self):
        self.removed();old=webui.receipt();volume=self.engine.volume
        self.assertEqual(self.main('recreate','--dry-run'),0)
        self.assertIsNone(webui.pending());self.assertIsNone(self.engine.row)
        self.assertEqual(self.main('recreate'),4)
        self.assertEqual(self.main('recreate','--yes'),0)
        self.assertIs(self.engine.volume,volume);self.assertEqual(volume['fixture_data'],'keep')
        self.assertNotEqual(webui.receipt()['id'],old['id']);self.assertEqual(webui.receipt()['image'],old['image'])
        backups=list(self.state.glob('open-webui.previous-*.json'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(backups[0].read_text())['id'],old['id'])

    def test_recreated_volume_or_different_image_never_adopted(self):
        self.removed()
        with self.assertRaises(ValueError):self.main('recreate','--image',self.engine.image.replace('a'*64,'b'*64),'--yes')
        self.engine.volume['CreatedAt']='2026-11-02T13:00:00Z'
        with self.assertRaises(ValueError):self.main('recreate','--yes')
        self.assertIsNone(webui.pending());self.assertIsNone(self.engine.row)

    def test_edited_receipt_is_preserved_when_recreation_cannot_commit(self):
        self.removed();call=self.engine.call
        def edited(command,**kwargs):
            result=call(command,**kwargs)
            if command[0]=='run':
                value=webui.receipt();value['port']=3001
                webui.receipt_path().write_text(json.dumps(value))
            return result
        with patch('webui.call',side_effect=edited),self.assertRaises(ValueError):self.main('recreate','--yes')
        self.assertEqual(webui.receipt()['port'],3001);self.assertIsNotNone(webui.pending())
        self.assertIsNotNone(self.engine.row)

    def test_pending_recovery_never_adopts_a_foreign_container_or_altered_volume(self):
        self.engine.fail_run=True;self.install();self.engine.fail_run=False
        intent=webui.pending()
        self.engine.row={'Id':'f'*64,'Config':{'Labels':{},'Image':intent['image']},'Mounts':[]}
        with self.assertRaises(ValueError):self.main('recover','--yes')
        self.engine.row=None;self.engine.volume['Labels']={}
        with self.assertRaises(ValueError):self.main('recover','--yes')
        self.assertIsNone(webui.receipt());self.assertIsNotNone(webui.pending())

    def test_metadata_rejects_duplicates_unknown_keys_and_broken_links(self):
        self.engine.fail_run=True;self.install()
        value=webui.pending();path=webui.pending_path()
        path.write_text(json.dumps(value)[:-1]+',"port":3001}')
        with self.assertRaises(ValueError):webui.pending()
        path.write_text(json.dumps({**value,'hook':'anything'}))
        with self.assertRaises(ValueError):webui.pending()
        path.unlink();path.symlink_to(self.state/'missing')
        with self.assertRaises(ValueError):webui.pending()

class EngineIsolationTests(unittest.TestCase):
    def test_remote_connection_environment_is_ignored(self):
        with patch.dict(os.environ,{'CONTAINER_HOST':'ssh://private-host','CONTAINER_CONNECTION':'private'}),\
                patch('webui.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            webui.call(['info'])
        self.assertEqual(run.call_args.args[0],['podman','--remote=false','info'])
        self.assertNotIn('CONTAINER_HOST',run.call_args.kwargs['env'])
        self.assertNotIn('CONTAINER_CONNECTION',run.call_args.kwargs['env'])
