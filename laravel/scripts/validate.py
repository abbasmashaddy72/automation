#!/usr/bin/env python3
"""Read-only validation of this folder alone; never installs prerequisites."""
import argparse
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['offline'],default='offline');parser.parse_args()
    checks=[]
    failures=[]
    for path in ROOT.rglob('*.py'):
        try:ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)))
        except (SyntaxError,UnicodeError):failures.append(str(path.relative_to(ROOT)))
    checks.append(dict(name='python-syntax',status='fail' if failures else 'pass',failures=failures))
    files=sorted(ROOT.rglob('*.sh'))
    results=[subprocess.run(['bash','-n',str(path)],capture_output=True).returncode for path in files]
    checks.append(dict(name='bash-syntax',status='fail' if any(results) else 'pass',scripts=len(files)))
    for tool,flags in (('shellcheck',['--severity=error']),('shfmt',['-l'])):
        if not shutil.which(tool):checks.append(dict(name=tool,status='skip',reason='tool_not_installed'));continue
        result=subprocess.run([tool,*flags,*map(str,files)],capture_output=True,text=True)
        checks.append(dict(name=tool,status='pass' if result.returncode==0 else 'fail',details=result.stdout+result.stderr))
    result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT,capture_output=True,text=True)
    checks.append(dict(name='unit-tests',status='pass' if result.returncode==0 else 'fail',details=result.stdout+result.stderr))
    print(json.dumps(dict(root=str(ROOT),checks=checks,summary={state:sum(check['status']==state for check in checks) for state in ('pass','fail','skip')}),indent=2))
    return int(any(check['status']=='fail' for check in checks))
if __name__=='__main__':raise SystemExit(main())
