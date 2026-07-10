import os
from contextlib import contextmanager
from contextvars import ContextVar

from llm_council.provider_caps import caps_for


_cloud_keys_var: ContextVar[dict[str, str]] = ContextVar("cloud_keys", default={})


HEADER_TO_PROVIDER = {
    "x-openai-api-key": "openai",
    "x-anthropic-api-key": "anthropic",
    "x-gemini-api-key": "gemini",
    "x-groq-api-key": "groq",
    "x-openrouter-api-key": "openrouter",
}


def extract_cloud_keys(headers) -> dict[str, str]:
    if not headers:
        return {}

    extracted = {}
    for header_name, provider in HEADER_TO_PROVIDER.items():
        value = headers.get(header_name)
        if value:
            extracted[provider] = value
    return extracted


@contextmanager
def scoped_cloud_keys(keys: dict[str, str] | None):
    token = _cloud_keys_var.set(dict(keys or {}))
    try:
        yield
    finally:
        _cloud_keys_var.reset(token)


def get_cloud_keys() -> dict[str, str]:
    return dict(_cloud_keys_var.get() or {})


def get_api_key_for_model(model_id: str) -> str | None:
    provider = caps_for(model_id)[1].provider
    return get_cloud_keys().get(provider)


def litellm_kwargs_for_model(model_id: str) -> dict:
    if caps_for(model_id)[1].provider == "ollama":
        base = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
        if base:
            return {"api_base": base}
        return {}
    api_key = get_api_key_for_model(model_id)
    if not api_key:
        return {}
    return {"api_key": api_key}
