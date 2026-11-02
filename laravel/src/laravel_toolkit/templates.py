"""Only bundled data templates, with fixed literal replacement fields."""
from pathlib import Path
import re
from . import common

ROOT=Path(__file__).resolve().parents[2]/'templates'


def render(name,values):
    if not re.fullmatch(r'[a-z-]+\.(?:conf|service|timer)\.tpl',name):raise ValueError('Unknown template name')
    path=common.checked(ROOT/name)
    if not path.is_file() or path.stat().st_size>65536:raise ValueError('Template missing or oversized')
    text=path.read_text()
    for key,value in values.items():text=text.replace('@@'+key+'@@',str(value))
    if re.search(r'@@[A-Z_]+@@',text):raise ValueError('Template has unresolved fields')
    return text.encode()
