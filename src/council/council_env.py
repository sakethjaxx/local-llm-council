"""Load .env settings before any module reads configuration at import time.

Precedence, highest first:
1. Variables already in the process environment (never overridden).
2. The file named by COUNCIL_ENV_FILE, when set (it replaces the checkout file).
3. The .env at the root of this source checkout (a directory with pyproject.toml).

The working directory is never searched: starting the server from an untrusted
folder must not be able to change its configuration.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

CHECKOUT_ROOT = Path(__file__).resolve().parents[2]

# LiteLLM calls load_dotenv() on import (searching the working directory) unless it
# runs in PRODUCTION mode; that would bypass the precedence above.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")


def load_council_env(checkout_root: Path = CHECKOUT_ROOT) -> Path | None:
    """Load the configured .env file, if any; return the file that was loaded."""
    explicit = os.getenv("COUNCIL_ENV_FILE", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise SystemExit(f"COUNCIL_ENV_FILE is set to {path}, which is not a readable file.")
        load_dotenv(path, override=False)
        return path
    candidate = checkout_root / ".env"
    if (checkout_root / "pyproject.toml").is_file() and candidate.is_file():
        load_dotenv(candidate, override=False)
        return candidate
    return None


load_council_env()
