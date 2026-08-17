#!/usr/bin/env python3
"""
Frictionless launcher for LLM Council server.
Usage:
    python run.py
"""
import os
import sys
from pathlib import Path

# Add src to module resolution path
src_dir = str(Path(__file__).resolve().parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from council.main import start

if __name__ == "__main__":
    start()
