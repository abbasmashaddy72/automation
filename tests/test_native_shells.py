"""Execute generated shell integration with native runtimes and private fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import developer

class NativeShellIntegration(unittest.TestCase):
    def run_shell(self,shell):
        executable=shutil.which(shell)
        if not executable:self.skipTest('Native '+shell+' runtime unavailable')
        with tempfile.TemporaryDirectory(prefix='automation-shell-test-') as temp:
            root=Path(temp);home=root/'home';home.mkdir()
            paths=[home/'.local/bin',home/'bin',home/'.config/composer/vendor/bin',home/'.composer/vendor/bin']
            for path in paths:path.mkdir(parents=True,exist_ok=True)
            vendor=root/'vendor/bin';vendor.mkdir(parents=True)
            tool=vendor/'fixture';tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');tool.chmod(0o700)
            config=root/'integration';config.write_bytes(developer.shell_content(b'# existing setting\n',shell))
            assertion=root/'assert-env.py';assertion.write_text('import json,os\nprint(json.dumps(os.environ["PATH"].split(os.pathsep)))\n')
            env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(home/'.config'),'PATH':os.defpath,
                'AUTOMATION_SHELL_FIXTURE':str(config),'AUTOMATION_SHELL_ASSERT':str(assertion)}
            for name in ('BASH_ENV','ENV','ZDOTDIR','SSH_AUTH_SOCK'):env.pop(name,None)
            command='source "$AUTOMATION_SHELL_FIXTURE"; source "$AUTOMATION_SHELL_FIXTURE"; vbin fixture "two words"; python3 "$AUTOMATION_SHELL_ASSERT"'
            flags={'bash':['--noprofile','--norc','-c'],'zsh':['-f','-c'],'fish':['--no-config','--command']}[shell]
            result=subprocess.run([executable,*flags,command],cwd=root,env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            lines=result.stdout.splitlines();self.assertEqual(lines[0],'two words')
            actual=json.loads(lines[-1])
            for path in paths:self.assertEqual(actual.count(str(path)),1,(shell,actual))
    def test_bash_runtime(self):self.run_shell('bash')
    def test_fish_runtime(self):self.run_shell('fish')
    def test_zsh_runtime(self):self.run_shell('zsh')
