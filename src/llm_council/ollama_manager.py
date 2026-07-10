import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Iterable

from llm_council.hardware_detect import get_hardware_suggestion
from llm_council.provider_caps import caps_for

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


def ollama_base_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def _ollama_tag(model: str) -> str:
    if caps_for(model)[1].provider == "ollama" and "/" in model:
        return model.split("/", 1)[1]
    return model


def _normalize_tag(tag: str) -> str:
    """Ollama treats `name` and `name:latest` as the same model — compare them as such."""
    return tag if ":" in tag else f"{tag}:latest"


def _iter_ollama_models(config: dict) -> Iterable[str]:
    seen = set()
    for seat in config.values():
        model = seat.get("model", "")
        if caps_for(model)[1].provider == "ollama":
            tag = _ollama_tag(model)
            if tag not in seen:
                seen.add(tag)
                yield tag


def _installed_models_via_http() -> list[str] | None:
    """Query the Ollama HTTP API. Returns None if the server is unreachable."""
    try:
        with urllib.request.urlopen(f"{ollama_base_url()}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _installed_models_via_cli() -> list[str] | None:
    """Fall back to the `ollama list` CLI. Returns None if the CLI is unavailable or fails."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except Exception:
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    models = []
    for line in lines[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def get_installed_models() -> list[str] | None:
    """List installed Ollama models. Returns None when Ollama itself is unreachable."""
    models = _installed_models_via_http()
    if models is not None:
        return models
    return _installed_models_via_cli()


def is_ollama_running() -> bool:
    return get_installed_models() is not None


def get_required_models(config: dict | None = None) -> list[str]:
    config = config or get_hardware_suggestion()["config"]
    return list(_iter_ollama_models(config))


def get_missing_models(config: dict | None = None) -> list[str]:
    installed = {_normalize_tag(model) for model in get_installed_models() or []}
    return [model for model in get_required_models(config) if _normalize_tag(model) not in installed]


def _pull_model_via_http(tag: str) -> dict | None:
    try:
        req = urllib.request.Request(
            f"{ollama_base_url()}/api/pull",
            data=json.dumps({"name": tag, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1800) as resp:
            body = json.loads(resp.read().decode())
        status = body.get("status", "")
        return {
            "model": tag,
            "success": status == "success",
            "stdout": status,
            "stderr": "" if status == "success" else json.dumps(body)[-4000:],
            "returncode": 0 if status == "success" else 1,
        }
    except (urllib.error.URLError, OSError, ValueError):
        return None


def pull_model(tag: str) -> dict:
    result = _pull_model_via_http(tag)
    if result is not None:
        return result
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


def _status_hint(running: bool, missing: list[str]) -> str:
    if not running:
        return (
            f"Ollama is not reachable at {ollama_base_url()}. "
            "Start it with `ollama serve` (install from https://ollama.com/download), "
            "or set OLLAMA_BASE_URL if it runs elsewhere."
        )
    if missing:
        pulls = "\n".join(f"ollama pull {tag}" for tag in missing)
        return f"Missing local models. Install them with one command per line:\n{pulls}"
    return ""


def ensure_models_for_config(config: dict, auto_pull: bool = False) -> dict:
    required = get_required_models(config)
    installed = get_installed_models()
    running = installed is not None
    installed = installed or []

    def _missing_from(current: list[str]) -> list[str]:
        normalized = {_normalize_tag(model) for model in current}
        return [model for model in required if _normalize_tag(model) not in normalized]

    missing = _missing_from(installed)
    pulled = []

    if auto_pull and running:
        for model in list(missing):
            result = pull_model(model)
            pulled.append(result)
        installed = get_installed_models() or []
        missing = _missing_from(installed)

    return {
        "provider": "ollama",
        "base_url": ollama_base_url(),
        "ollama_running": running,
        "required": required,
        "installed": installed,
        "missing": missing,
        "pulled": pulled,
        "ready": (not required) or (running and not missing),
        "auto_pull_enabled": auto_pull,
        "hint": "" if not required else _status_hint(running, missing),
    }


def auto_pull_enabled() -> bool:
    return os.getenv("COUNCIL_BOOTSTRAP_LOCAL_MODELS", "false").lower() == "true"
