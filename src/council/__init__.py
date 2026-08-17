"""LLM Council application package.

The migration keeps the existing module-level imports working while external
callers move to the stable ``council.*`` package paths.
"""

import sys
from pathlib import Path


_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)
