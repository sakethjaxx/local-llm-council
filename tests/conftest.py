import sys
import os
import tempfile
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

_test_tmp = Path(__file__).resolve().parents[1] / ".pytest-tmp"
_test_tmp.mkdir(exist_ok=True)
tempfile.tempdir = str(_test_tmp)
class _WorkspaceTemporaryDirectory:
    def __init__(self, *args, **kwargs):
        del args, kwargs
        self.name = str(_test_tmp / f"tmp-{uuid.uuid4().hex}")

    def __enter__(self):
        Path(self.name).mkdir(parents=True, exist_ok=False)
        return self.name

    def __exit__(self, exc_type, exc, tb):
        # The managed sandbox can deny deletes for files it allowed tests to
        # create. Leave scratch directories behind; .gitignore keeps them quiet.
        return False

    def cleanup(self):
        return None


def _workspace_temporary_directory(*args, **kwargs):
    return _WorkspaceTemporaryDirectory(*args, **kwargs)


tempfile.TemporaryDirectory = _workspace_temporary_directory
