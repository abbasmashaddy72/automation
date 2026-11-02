"""Isolated Git/shell recovery and owned-agent contracts; no host config writes."""
from argparse import Namespace
import contextlib
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import developer
import shell_migration
import ssh_agent


class Environment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.home=Path(self.temp.name)
        self.runtime=self.home/'runtime';self.runtime.mkdir(mode=0o700)
        env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'config'),'XDG_STATE_HOME':str(self.home/'state'),'XDG_RUNTIME_DIR':str(self.runtime)});env.start();self.addCleanup(env.stop)
        self.args=Namespace(action='shell',shell='bash',name='Fixture',email='fixture@example.invalid',transport='ssh',banner='none',fish_greeting='keep',
            use_toolkit_agent=False,migrate_legacy=False,current_sha256=None,value=None,dry_run=False,yes=True,identity_file=None)
        redirect=contextlib.redirect_stdout(io.StringIO());redirect.__enter__();self.addCleanup(redirect.__exit__,None,None,None)


class Recovery(Environment):
    def test_git_transport_native_expansion_is_explicit_idempotent_and_reversible(self):
        if not shutil.which('git'):self.skipTest('Git unavailable')
        path=self.home/'.gitconfig';path.write_text('[user]\n name = Keep\n[core]\n editor = vi\n')
        original=path.read_bytes();self.args.action='git-transport'
        self.assertEqual(developer.main(self.args,lambda *_:False),4);self.assertEqual(path.read_bytes(),original)
        self.assertEqual(developer.main(self.args,lambda *_:True),0);after=path.read_bytes()
        self.assertEqual(developer.main(self.args,lambda *_:True),0);self.assertEqual(path.read_bytes(),after)
        env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':str(path)}
        result=subprocess.run(['git','ls-remote','--get-url','https://github.com/fixture/project'],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'git@github.com:fixture/project')
        self.args.transport='https';self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertNotIn('insteadOf',path.read_text());self.assertIn('Keep',path.read_text());self.assertIn('editor = vi',path.read_text())

    def test_transport_conflict_and_invalid_choice_preserve_user_data(self):
        if not shutil.which('git'):self.skipTest('Git unavailable')
        original=b'[url "ssh://different/"]\n insteadOf = https://github.com/\n'
        with self.assertRaises(ValueError):developer.transport(original,'ssh')
        with self.assertRaises(ValueError):developer.transport(original,'$(bad)')

    def test_exact_blocks_migrate_without_loose_deletions(self):
        original='# existing\n2026-01-01 01:02:03 user-line\n'+shell_migration.AGENT_BLOCK+'\n# retained\n'
        result=shell_migration.migrate(original,'bash')
        self.assertNotIn('eval',result);self.assertIn('user-line',result);self.assertIn('# retained',result)
        legacy='# before\n# === BEGIN CUSTOM DEV SHELL SETUP ===\nold_body\n# === END CUSTOM DEV SHELL SETUP ===\n# after\n'
        self.assertEqual(shell_migration.migrate(legacy,'zsh'),'# before\n# after\n')
        for content in (legacy.replace('# === END CUSTOM DEV SHELL SETUP ===',''),shell_migration.AGENT_BLOCK.replace('ssh-add','other-command'),
                        legacy.replace('old_body','# === BEGIN USER BLOCK ==='),
                        '# === CUSTOM DEV SHELL SETUP ===\nuser-data\n'):
            with self.assertRaises(ValueError):shell_migration.migrate(content,'bash')

    def test_migration_digest_and_conflict_safe_restore(self):
        path=self.home/'.bashrc';original=('# retained\n'+shell_migration.AGENT_BLOCK+'\n').encode();path.write_bytes(original)
        self.args.migrate_legacy=True
        with self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        self.args.current_sha256=developer.sha(original);self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertNotIn('eval',path.read_text());self.assertIn('# retained',path.read_text())
        receipt=next((self.home/'state/automation-toolkit/developer').glob('*.json'))
        after=path.read_bytes();path.write_bytes(after+b'# later\n');self.args.action='restore';self.args.value=receipt.name
        with self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        path.write_bytes(after);self.assertEqual(developer.main(self.args,lambda *_:True),0);self.assertEqual(path.read_bytes(),original)

    def test_shell_backup_import_does_not_execute_or_activate_backup(self):
        path=self.home/'.bashrc';path.write_text('# current\n');backup=self.home/'old-shell.backup'
        sentinel=self.home/'executed';backup.write_text('touch '+str(sentinel)+'\n');backup.chmod(0o600)
        self.args.action='import-shell-backup';self.args.value=str(backup);self.args.current_sha256=developer.sha(path.read_bytes())
        self.assertEqual(developer.main(self.args,lambda *_:True),0);self.assertFalse(sentinel.exists());self.assertEqual(path.read_text(),'# current\n')
        receipt=next((self.home/'state/automation-toolkit/developer').glob('*.json'));self.assertEqual(receipt.stat().st_mode&0o777,0o600)
        self.args.action='restore';self.args.value=receipt.name;self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertEqual(path.read_bytes(),backup.read_bytes());self.assertFalse(sentinel.exists())

    def test_syntax_failure_and_restore_review_race_preserve_file(self):
        path=self.home/'.bashrc';path.write_text('if then\n');before=path.read_bytes()
        with self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        self.assertEqual(path.read_bytes(),before)
        path.write_text('# original\n');developer.main(self.args,lambda *_:True)
        receipt=next((self.home/'state/automation-toolkit/developer').glob('*.json'));self.args.action='restore';self.args.value=receipt.name
        def approve(*args):path.write_text('# concurrent edit\n');return True
        with self.assertRaises(ValueError):developer.main(self.args,approve)
        self.assertEqual(path.read_text(),'# concurrent edit\n')

    def test_shell_agent_connection_preserves_other_agents_in_all_shells(self):
        folder=self.runtime/'automation-ssh-agent';folder.mkdir(mode=0o700)
        listener=socket.socket(socket.AF_UNIX);listener.bind(str(folder/'agent.sock'));self.addCleanup(listener.close)
        for shell in ('bash','zsh','fish'):
            if not shutil.which(shell):continue
            content=developer.shell_content(b'',shell,use_agent=True,greeting='off' if shell=='fish' else 'keep');shell_migration.check_syntax(content,shell)
            path=self.home/(shell+'.rc');path.write_bytes(content)
            source='source "$argv[1]"; printf "%s" "$SSH_AUTH_SOCK"' if shell=='fish' else 'source "$1"; printf "%s" "$SSH_AUTH_SOCK"'
            command=[shell,'--no-config','-c',source,str(path)] if shell=='fish' else [shell,'-f' if shell=='zsh' else '--norc','-c',source,'fixture',str(path)]
            env={**os.environ};env.pop('SSH_AUTH_SOCK',None)
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,(shell,result.stderr));self.assertEqual(result.stdout,str(folder/'agent.sock'))
            result=subprocess.run(command,env={**env,'SSH_AUTH_SOCK':'existing-other-agent'},capture_output=True,text=True)
            self.assertEqual(result.stdout,'existing-other-agent')

    def test_syntax_check_never_executes_inherited_startup_hook(self):
        sentinel=self.home/'executed';hook=self.home/'bash-env';hook.write_text('touch '+str(sentinel)+'\n')
        with patch.dict(os.environ,{'BASH_ENV':str(hook)}):shell_migration.check_syntax(b'export FIXTURE="$(false)"\n','bash')
        self.assertFalse(sentinel.exists())


class OwnedAgent(Environment):
    def setUp(self):
        super().setUp();self.args.action='ssh-agent';self.args.value='configure';self.binary=shutil.which('ssh-agent')
        if not self.binary:self.skipTest('OpenSSH agent unavailable')

    def control(self,*args):
        if '--property=LoadState' in args:return Namespace(returncode=0,stdout='LoadState=not-found\nActiveState=inactive\n')
        if '--property=UnitFileState' in args:return Namespace(returncode=0,stdout='ActiveState=inactive\nUnitFileState=disabled\n')
        if '--property=ActiveState' in args:return Namespace(returncode=0,stdout='active\n')
        return Namespace(returncode=0,stdout='')

    def configure(self):
        with patch('ssh_agent.control',side_effect=self.control):return developer.main(self.args,lambda *_:True)

    def test_owned_configuration_is_private_and_never_starts_or_loads_keys(self):
        with patch('ssh_agent.control',side_effect=self.control) as calls:self.assertEqual(developer.main(self.args,lambda *_:True),0)
        path,binary=ssh_agent.owned();self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertIn('RuntimeDirectoryMode=0700',path.read_text());self.assertIn(' -D -a ',path.read_text())
        self.assertFalse(any(call.args[0] in ('start','enable','stop','restart') for call in calls.call_args_list))
        self.assertFalse((self.runtime/'automation-ssh-agent').exists())

    def test_dryrun_refusal_foreign_unit_and_failed_reload_preserve_state(self):
        self.args.dry_run=True;self.assertEqual(self.configure(),0);self.assertFalse(developer.target('ssh-agent').exists())
        self.args.dry_run=False
        with patch('ssh_agent.control',side_effect=self.control):self.assertEqual(developer.main(self.args,lambda *_:False),4)
        def bad(*args):return Namespace(returncode=1,stdout='') if args[0]=='daemon-reload' else self.control(*args)
        with patch('ssh_agent.control',side_effect=bad),self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        self.assertFalse(developer.target('ssh-agent').exists())
        path=developer.target('ssh-agent');path.write_text('[Service]\nExecStart=/other\n')
        with self.assertRaises(ValueError):self.configure()
        self.assertIn('/other',path.read_text())

    def test_loaded_foreign_unit_and_concurrent_creation_not_adopted(self):
        with patch('ssh_agent.control',return_value=Namespace(returncode=0,stdout='LoadState=loaded\nActiveState=active\n')),self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        def conflicting(source,target):Path(target).write_text('concurrent unit');raise FileExistsError()
        with patch('ssh_agent.control',side_effect=self.control),patch('ssh_agent.os.link',side_effect=conflicting),self.assertRaises(FileExistsError):developer.main(self.args,lambda *_:True)
        self.assertEqual(developer.target('ssh-agent').read_text(),'concurrent unit')

    def test_edit_during_review_prevents_lifecycle(self):
        self.configure();self.args.value='stop'
        def approve(*args):path=developer.target('ssh-agent');path.write_text(path.read_text()+'# later\n');return True
        with patch('ssh_agent.control',side_effect=self.control) as control,self.assertRaises(ValueError):developer.main(self.args,approve)
        self.assertFalse(any(call.args[0]=='stop' for call in control.call_args_list))

    def test_uninstall_requires_stopped_disabled_and_preserves_user_files(self):
        self.configure();self.args.value='uninstall';key=self.home/'user-key';key.write_text('preserve-key');rc=self.home/'.bashrc';rc.write_text('# preserve\n')
        with patch('ssh_agent.control',return_value=Namespace(returncode=0,stdout='ActiveState=active\nUnitFileState=enabled\n')),self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        self.assertTrue(developer.target('ssh-agent').exists())
        with patch('ssh_agent.control',side_effect=self.control):self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertFalse(developer.target('ssh-agent').exists());self.assertEqual(key.read_text(),'preserve-key');self.assertEqual(rc.read_text(),'# preserve\n')

    def test_lifecycle_targets_only_owned_unit_and_start_is_idempotent(self):
        self.configure();started=False;calls=[]
        def control(*args):
            nonlocal started
            calls.append(args)
            if args[0]=='start':started=True
            if '--property=ActiveState' in args:return Namespace(returncode=0,stdout='active\n' if started else 'inactive\n')
            return Namespace(returncode=0,stdout='')
        with patch('ssh_agent.control',side_effect=control),patch('ssh_agent.probe',return_value='missing'):
            self.args.value='start';self.assertEqual(developer.main(self.args,lambda *_:True),0)
            for action in ('stop','enable','disable'):
                self.args.value=action;self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.args.value='start'
        with patch('ssh_agent.control',side_effect=control),patch('ssh_agent.probe',return_value='ready-empty'):
            self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertEqual(sum(row[0]=='start' for row in calls),1)
        self.assertTrue(all(ssh_agent.NAME in row for row in calls))

    def test_agent_backup_restore_requires_inactive_state_and_explicit_reload(self):
        self.configure();receipt=next((self.home/'state/automation-toolkit/developer').glob('*.json'))
        self.args.action='restore';self.args.value=receipt.name
        with patch('ssh_agent.control',return_value=Namespace(returncode=0,stdout='ActiveState=active\nUnitFileState=enabled\n')),self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        with patch('ssh_agent.control',side_effect=self.control) as control:self.assertEqual(developer.main(self.args,lambda *_:True),0)
        self.assertFalse(developer.target('ssh-agent').exists());self.assertFalse(any(row.args[0]=='daemon-reload' for row in control.call_args_list))

    def test_unsafe_socket_is_refused_without_protocol_calls(self):
        folder=self.runtime/'automation-ssh-agent';folder.mkdir(mode=0o700)
        file=self.home/'not-a-socket';file.write_text('private fixture');(folder/'agent.sock').symlink_to(file)
        with patch('ssh_agent.subprocess.run') as run,self.assertRaises(ValueError):ssh_agent.probe()
        run.assert_not_called();self.assertEqual(file.read_text(),'private fixture')

    def test_later_runtime_files_prevent_stop_and_are_never_removed(self):
        self.configure();folder=self.runtime/'automation-ssh-agent';folder.mkdir(mode=0o700);data=folder/'user-data';data.write_text('preserve')
        self.args.value='stop'
        with patch('ssh_agent.control',side_effect=self.control) as control,self.assertRaises(ValueError):developer.main(self.args,lambda *_:True)
        self.assertFalse(any(call.args[0]=='stop' for call in control.call_args_list));self.assertEqual(data.read_text(),'preserve')

    def test_native_systemd_static_validation(self):
        tool=shutil.which('systemd-analyze')
        if not tool:self.skipTest('systemd-analyze unavailable')
        self.configure();path=developer.target('ssh-agent')
        result=subprocess.run([tool,'--user','verify',str(path)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_native_temporary_agent_protocol_and_teardown(self):
        self.configure()
        folder=self.runtime/'automation-ssh-agent';folder.mkdir(mode=0o700);path=folder/'agent.sock'
        process=subprocess.Popen([self.binary,'-D','-a',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and not path.exists():time.sleep(0.02)
            self.assertEqual(ssh_agent.probe(),'ready-empty');self.assertEqual(ssh_agent.environment()['SSH_AUTH_SOCK'],str(path))
            if shutil.which('ssh-keygen'):
                folder=self.home/'.ssh';folder.mkdir(mode=0o700);key=folder/'fixture'
                result=subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','automation-fixture','-f',str(key)],capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.args.value='add';self.args.identity_file=str(key)
                with patch('ssh_agent.control',side_effect=self.control):self.assertEqual(developer.main(self.args,lambda *_:True),0)
                self.assertEqual(ssh_agent.probe(),'ready-with-keys')
        finally:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        self.assertIsNotNone(process.poll())
