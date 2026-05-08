import os
import subprocess
from typing import Iterable

from hardware_detect import get_hardware_suggestion


def _ollama_tag(model: str) -> str:
    if model.startswith("ollama/"):
        return model.split("/", 1)[1]
    return model


def _iter_ollama_models(config: dict) -> Iterable[str]:
    seen = set()
    for seat in config.values():
        model = seat.get("model", "")
        if model.startswith("ollama/"):
            tag = _ollama_tag(model)
            if tag not in seen:
                seen.add(tag)
                yield tag


def get_installed_models() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except FileNotFoundError:
        return []
    except Exception:
        return []

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return []

    models = []
    for line in lines[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def get_required_models(config: dict | None = None) -> list[str]:
    config = config or get_hardware_suggestion()["config"]
    return list(_iter_ollama_models(config))


def get_missing_models(config: dict | None = None) -> list[str]:
    installed = set(get_installed_models())
    return [model for model in get_required_models(config) if model not in installed]


def pull_model(tag: str) -> dict:
    try:
        result = subprocess.run(
            ["ollama", "pull", tag],
            capture_output=True,
            text=True,
            timeout=None,
            check=False,
        )
        return {
            "model": tag,
            "success": result.returncode == 0,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {
            "model": tag,
            "success": False,
            "stdout": "",
            "stderr": "ollama command not found",
            "returncode": 127,
        }
    except Exception as exc:
        return {
            "model": tag,
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": 1,
        }


def ensure_models_for_config(config: dict, auto_pull: bool = False) -> dict:
    required = get_required_models(config)
    installed = get_installed_models()
    missing = [model for model in required if model not in installed]
    pulled = []

    if auto_pull:
        for model in list(missing):
            result = pull_model(model)
            pulled.append(result)
        installed = get_installed_models()
        missing = [model for model in required if model not in installed]

    return {
        "provider": "ollama",
        "required": required,
        "installed": installed,
        "missing": missing,
        "pulled": pulled,
        "ready": not missing,
        "auto_pull_enabled": auto_pull,
    }


def auto_pull_enabled() -> bool:
    return os.getenv("COUNCIL_BOOTSTRAP_LOCAL_MODELS", "false").lower() == "true"
