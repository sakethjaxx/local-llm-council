import json
import os


def load_presets():
    path = os.path.join(os.path.dirname(__file__), "presets.json")
    with open(path) as f:
        return json.load(f)


def get_demo_catalog():
    data = load_presets()
    return {
        "presets": data["presets"],
        "samples": data.get("samples", []),
    }
