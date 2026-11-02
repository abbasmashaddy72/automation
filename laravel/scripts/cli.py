"""Internal script-relative launcher for the two public Bash entrypoints."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from laravel_toolkit import provision,deploy
import subprocess

if __name__=='__main__':
    try:
        if len(sys.argv)<2 or sys.argv[1] not in ('provision','deploy'):raise ValueError('Unknown Laravel workflow')
        raise SystemExit((provision if sys.argv[1]=='provision' else deploy).main(sys.argv[2:]))
    except (KeyboardInterrupt,EOFError):print('Interrupted; inspect private operation receipts before retrying',file=sys.stderr);raise SystemExit(130)
    except ValueError as exc:print('Laravel error:',str(exc),file=sys.stderr);raise SystemExit(2)
    except (OSError,subprocess.SubprocessError) as exc:print('Laravel IO/process failure ('+type(exc).__name__+', errno='+str(getattr(exc,'errno',None))+'); inspect private receipts and preserved candidate; output withheld to protect credentials',file=sys.stderr);raise SystemExit(2)
