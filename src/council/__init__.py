"""LLM Council application package.

The migration keeps the existing module-level imports working while external
callers move to the stable ``council.*`` package paths.
"""

import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# Several modules read their settings at import time (DB path, LLM timeout,
# concurrency), so .env must be loaded before any of them is imported. Search
# from the working directory so an installed `council-serve` picks up ./.env.
load_dotenv(find_dotenv(usecwd=True))

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)
