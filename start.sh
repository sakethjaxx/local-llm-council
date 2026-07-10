#!/usr/bin/env bash
# LLM Council — one-command setup + start (Linux/macOS)
set -e

echo "Starting Local LLM Council..."

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Python 3.12+ is required but was not found."
  echo "Install it from https://www.python.org/downloads/ and re-run this script."
  exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 3.12+ is required (found $("$PYTHON" --version))."
  exit 1
fi

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv venv
fi

echo "Installing dependencies (first run can take a few minutes)..."
./venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

if [ ! -f ".env" ] && [ -f "env.example" ]; then
  cp env.example .env
  echo "Created .env from env.example (defaults are fine for local use)."
fi

if curl -sf --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  echo "Ollama detected."
else
  echo "Warning: Ollama is not reachable at http://localhost:11434."
  echo "The UI will start, but council runs need Ollama:"
  echo "  1. Install: https://ollama.com/download"
  echo "  2. Start it, then: ollama pull llama3.2"
fi

echo "Server starting on http://localhost:8765"
exec ./venv/bin/python -m llm_council.main
