import asyncio
import os
import subprocess
from typing import AsyncIterator, Iterable

from hardware_detect import get_hardware_suggestion
from provider_caps import caps_for


def _ollama_tag(model: str) -> str:
    if caps_for(model)[1].provider == "ollama" and "/" in model:
        return model.split("/", 1)[1]
    return model


def _iter_ollama_models(config: dict) -> Iterable[str]:
    """Yield the Ollama tags a roster needs.

    Tolerates malformed rosters. A client posting a list instead of the seat-id
    dict used to raise AttributeError deep inside the SSE generator, which killed
    the stream before a single event was written — the UI just hung with no error.
    """
    if not isinstance(config, dict):
        return
    seen = set()
    for seat in config.values():
        if not isinstance(seat, dict):
            continue
        model = seat.get("model", "")
        if not isinstance(model, str) or not model:
            continue
        if caps_for(model)[1].provider == "ollama":
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


async def pull_model_stream(tag: str) -> AsyncIterator[dict]:
    """Run `ollama pull <tag>`, yielding progress events as they arrive.

    Ollama's CLI writes its progress bar using carriage returns, not newlines,
    so both are treated as line breaks here to surface live percentage updates
    instead of one giant buffered line at the end.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama", "pull", tag,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        yield {"type": "error", "message": "ollama command not found"}
        yield {"type": "done", "success": False, "returncode": 127}
        return

    buffer = b""
    while True:
        chunk = await proc.stdout.read(256)
        if not chunk:
            break
        buffer += chunk
        while True:
            idx_candidates = [i for i in (buffer.find(b"\r"), buffer.find(b"\n")) if i != -1]
            if not idx_candidates:
                break
            idx = min(idx_candidates)
            line = buffer[:idx].decode(errors="replace").strip()
            buffer = buffer[idx + 1:]
            if line:
                yield {"type": "line", "text": line}

    tail = buffer.decode(errors="replace").strip()
    if tail:
        yield {"type": "line", "text": tail}

    returncode = await proc.wait()
    yield {"type": "done", "success": returncode == 0, "returncode": returncode}
