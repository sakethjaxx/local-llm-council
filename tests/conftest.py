import os
import sys
import tempfile

# Store singletons are constructed during import. Point them at a throwaway
# database before pytest collects modules so tests never touch council_runs.db.
os.environ.setdefault(
    "COUNCIL_DB_PATH",
    os.path.join(tempfile.mkdtemp(prefix="council-test-"), "test_runs.db"),
)
os.environ.setdefault("COUNCIL_METRICS_FILE", "")
# Never let the developer's checkout .env (keys, DB path, API key) leak into tests.
_EMPTY_ENV = os.path.join(tempfile.mkdtemp(prefix="council-test-env-"), "empty.env")
open(_EMPTY_ENV, "w").close()
os.environ.setdefault("COUNCIL_ENV_FILE", _EMPTY_ENV)
# Roster suggestions depend on GPU memory; pin it so results don't vary by host.
os.environ.setdefault("COUNCIL_GPU_VRAM_GB", "24")

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
# Temporary compatibility path for tests that still exercise individual modules
# directly. Runtime entry points use the package path: ``council.main:app``.
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "council"))
