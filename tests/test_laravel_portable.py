"""Optional parent runner bridge. All Laravel tests live in the portable folder."""
from pathlib import Path
import unittest

def load_tests(loader,tests,pattern):
    previous=loader._top_level_dir
    folder=Path(__file__).resolve().parents[1]/'laravel/tests'
    try:return loader.discover(str(folder),pattern='test_*.py',top_level_dir=str(folder))
    finally:loader._top_level_dir=previous
