"""Safe project skeletons; no network, post-install hooks or shell execution."""
from __future__ import annotations
from pathlib import Path

SITE_DIRECTORIES = ('Experiment', 'Local', 'Other-Languages', 'Packages-Git',
                    'Packages-Own', 'Personal-Git', 'Staging', 'Testing')


def layout(target, *, dry_run=False):
    """Create missing project folders only, without adopting or deleting projects."""
    root = Path(target).expanduser().absolute()
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError('Symlink project paths are forbidden')
    root = root.resolve()
    blocked = ('/etc', '/usr', '/var', '/root', '/boot', '/proc', '/sys', '/dev', '/bin', '/sbin')
    if (root == Path('/')
            or any(root == Path(p) or Path(p) in root.parents for p in blocked)):
        raise ValueError('Choose a project root under an existing directory')
    paths = [root, *(root/name for name in SITE_DIRECTORIES)]
    for path in paths:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('Symlink project paths are forbidden')
        if path.exists() and not path.is_dir():
            raise ValueError('A project directory conflicts with an existing file')
    missing = [path for path in paths if not path.exists()]
    parent=root.parent
    parents=[]
    while not parent.exists():parents.append(parent);parent=parent.parent
    if parent.stat().st_uid!=__import__('os').getuid():raise ValueError('Project layout must be created below a user-owned ancestor')
    missing=[*reversed(parents),*missing]
    if not dry_run:
        for path in missing:
            path.mkdir(mode=0o700)
    return {'target': str(root), 'missing': [str(p) for p in missing],
            'created': not dry_run, 'note': 'Existing projects preserved; park selected folders explicitly with Lerd.'}

TEMPLATES = {
    'python': {
        'README.md':'# Python Project\n\nCreate a venv, then run `python -m unittest discover`.\n',
        '.gitignore':'.venv/\n__pycache__/\n.pytest_cache/\n.env\n',
        'src/__init__.py':'',
        'tests/test_smoke.py': 'import unittest\n\n\nclass TestSmoke(unittest.TestCase):\n    def test_ready(self):\n        self.assertTrue(True)\n',
    },
    'node': {
        'README.md':'# Node Project\n\nRun `npm test` on Node.js 20+. No dependencies are installed automatically.\n',
        '.gitignore':'node_modules/\n.env\ndist/\n',
        'package.json':'{"name":"starter-project","version":"1.0.0","private":true,"type":"module","scripts":{"test":"node --test"}}\n',
        'test/smoke.test.js':'import test from "node:test";\nimport assert from "node:assert/strict";\ntest("ready", () => assert.ok(true));\n'
    }
}


def create(template, target, *, dry_run=False):
    if template not in TEMPLATES: raise ValueError('Supported templates: python, node')
    dest = Path(target).expanduser().absolute()
    if any(part.is_symlink() for part in (dest,*dest.parents)):
        raise ValueError('Symlink project paths are forbidden')
    dest = dest.resolve()
    blocked = (Path('/etc'),Path('/usr'),Path('/var'),Path('/root'),Path('/boot'),
               Path('/proc'),Path('/sys'),Path('/dev'),Path('/bin'),Path('/sbin'))
    if (dest == Path('/') or any(dest == b or b in dest.parents for b in blocked)
            or dest.exists() or not dest.parent.is_dir()
            or any(part.is_symlink() for part in (dest.parent, *dest.parent.parents))):
        raise ValueError('Target must be a new directory under an existing, non-symlink parent')
    if dry_run:return {'template':template,'target':str(dest),'files':sorted(TEMPLATES[template]),'created':False}
    # Atomic directory creation before writing files; refuse existing paths.
    dest.mkdir(mode=0o700)
    try:
        for relative, text in TEMPLATES[template].items():
            file=dest/relative
            file.parent.mkdir(parents=True,exist_ok=True)
            with file.open('x', encoding='utf-8') as f:f.write(text)
    except Exception:
        # Remove only the empty/skeleton tree we have just created.
        for path in sorted(dest.rglob('*'), key=lambda p:len(p.parts),reverse=True):
            if path.is_file():path.unlink()
            elif path.is_dir():path.rmdir()
        dest.rmdir()
        raise
    return {'template':template,'target':str(dest),'files':sorted(TEMPLATES[template]),'created':True}
