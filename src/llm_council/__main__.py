import os

import uvicorn

from llm_council.main import _is_localhost


def main():
    host = os.getenv("COUNCIL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("COUNCIL_PORT", "8765"))
    api_key = os.getenv("COUNCIL_API_KEY", "").strip()
    if not _is_localhost(host) and not api_key:
        raise SystemExit(
            "ERROR: COUNCIL_API_KEY must be set when binding to non-localhost. "
            "Set COUNCIL_API_KEY or use COUNCIL_HOST=127.0.0.1"
        )
    uvicorn.run("llm_council.main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()
