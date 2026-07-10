import json
from pathlib import Path


PRESETS_PATH = Path(__file__).resolve().parent / "resources" / "presets.json"


def load_presets():
    with PRESETS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_demo_catalog():
    data = load_presets()
    return {
        "presets": data["presets"],
        "samples": data.get("samples", []),
    }
