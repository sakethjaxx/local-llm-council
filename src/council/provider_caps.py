import re
from copy import deepcopy
from dataclasses import dataclass, field


# Value-level secret scrubbing. Key-name redaction misses secrets that arrive as
# free text — a user pasting their own key into a topic/note/attachment, or an LLM
# echoing one back. These land in council_runs.db / council_metrics.jsonl and
# exports unless scrubbed here (redact_config runs at every serialization edge).
_SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                 # OpenAI / Anthropic-style
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),             # Anthropic
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                 # Google API key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),            # GitHub tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),          # Slack tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),      # Bearer tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
]
_SECRET_REPLACEMENT = "[REDACTED_SECRET]"


def scrub_secret_values(text: str) -> str:
    if not text:
        return text
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(_SECRET_REPLACEMENT, text)
    return text


# Every pattern above is one run of these characters, except "Bearer <token>".
# \Z, not $: $ also matches just before a final newline, which would misplace the cut.
_TRAILING_WORD = re.compile(r"[A-Za-z0-9._-]*\Z")
_TRAILING_BEARER = re.compile(r"(?i)bearer\s*\Z")
_MAX_HELD_CHARS = 4096


class StreamScrubber:
    """Scrubs text that arrives in chunks, so a secret split across chunks is still caught.

    The trailing word (and a trailing "Bearer") is held back until the next chunk
    shows where it ends; call flush() when the stream finishes.
    """

    def __init__(self) -> None:
        self._held = ""

    def feed(self, chunk: str) -> str:
        text = self._held + (chunk or "")
        cut = _TRAILING_WORD.search(text).start()
        bearer = _TRAILING_BEARER.search(text[:cut])
        if bearer:
            cut = bearer.start()
        if len(text) - cut > _MAX_HELD_CHARS:
            cut = len(text)
        self._held = text[cut:]
        return scrub_secret_values(text[:cut])

    def flush(self) -> str:
        held, self._held = self._held, ""
        return scrub_secret_values(held)


@dataclass(frozen=True)
class ProviderCaps:
    provider: str
    response_format: bool
    cost_per_1k_input: float
    cost_per_1k_output: float
    rate_limit_tpm: int | None


@dataclass(frozen=True)
class ModelCaps:
    model_id: str
    provider: str
    vision: bool
    context_window: int
    notes: str = ""
    strengths: list[str] = field(default_factory=list)
    tool_use: bool = False


PROVIDERS: dict[str, ProviderCaps] = {
    "ollama": ProviderCaps("ollama", False, 0.0, 0.0, None),
    "openai": ProviderCaps("openai", True, 0.0, 0.0, None),
    "anthropic": ProviderCaps("anthropic", True, 0.0, 0.0, None),
    "gemini": ProviderCaps("gemini", True, 0.0, 0.0, None),
    "groq": ProviderCaps("groq", True, 0.0, 0.0, None),
}


MODELS: dict[str, ModelCaps] = {
    "ollama/qwen2.5:3b": ModelCaps("ollama/qwen2.5:3b", "ollama", False, 32768, "Fast local generalist."),
    "ollama/qwen2.5:7b": ModelCaps("ollama/qwen2.5:7b", "ollama", False, 32768, "Balanced local generalist.", ["reasoning"]),
    "ollama/qwen2.5:14b": ModelCaps("ollama/qwen2.5:14b", "ollama", False, 32768, "Higher quality local generalist.", ["reasoning"]),
    "ollama/qwen2.5:32b": ModelCaps("ollama/qwen2.5:32b", "ollama", False, 32768, "Large local generalist.", ["reasoning"]),
    "ollama/qwen2.5-coder:7b": ModelCaps("ollama/qwen2.5-coder:7b", "ollama", False, 32768, "Local coding model.", ["code"]),
    "ollama/qwen2.5-coder:14b": ModelCaps("ollama/qwen2.5-coder:14b", "ollama", False, 32768, "Stronger local coding model.", ["code"]),
    "ollama/llama3.2:3b": ModelCaps("ollama/llama3.2:3b", "ollama", False, 131072, "Fast local model."),
    "ollama/llama3.1:8b": ModelCaps("ollama/llama3.1:8b", "ollama", False, 131072, "Balanced local Llama model.", ["reasoning"]),
    "ollama/llama3.1:70b": ModelCaps("ollama/llama3.1:70b", "ollama", False, 131072, "Large local Llama model.", ["reasoning"]),
    "ollama/mistral:7b": ModelCaps("ollama/mistral:7b", "ollama", False, 32768, "Compact local generalist.", ["reasoning"]),
    "ollama/llava:7b": ModelCaps("ollama/llava:7b", "ollama", True, 4096, "Local vision model."),
    "ollama/gemma2:2b": ModelCaps("ollama/gemma2:2b", "ollama", False, 8192, "Small local model."),
    "ollama/gemma2:9b": ModelCaps("ollama/gemma2:9b", "ollama", False, 8192, "Balanced local model.", ["reasoning"]),
    "ollama/gemma3:4b": ModelCaps("ollama/gemma3:4b", "ollama", True, 32768, "Local multimodal model.", ["reasoning"]),
    "ollama/qwen2.5vl:7b": ModelCaps("ollama/qwen2.5vl:7b", "ollama", True, 32768, "Local vision-language model.", ["reasoning"]),
    "ollama/minicpm-v:8b": ModelCaps("ollama/minicpm-v:8b", "ollama", True, 32768, "Local vision-language model."),
    "ollama/deepseek-r1:8b": ModelCaps("ollama/deepseek-r1:8b", "ollama", False, 32768, "Local reasoning model.", ["math", "reasoning"]),
    "ollama/deepseek-r1:14b": ModelCaps("ollama/deepseek-r1:14b", "ollama", False, 32768, "Stronger local reasoning model.", ["math", "reasoning"]),
    "ollama/deepseek-r1:32b": ModelCaps("ollama/deepseek-r1:32b", "ollama", False, 32768, "Large local reasoning model.", ["math", "reasoning"]),
    "openai/gpt-4o": ModelCaps("openai/gpt-4o", "openai", True, 128000, "OpenAI multimodal model.", ["code", "math", "reasoning"], True),
    "openai/gpt-4o-mini": ModelCaps("openai/gpt-4o-mini", "openai", True, 128000, "Small OpenAI multimodal model.", ["code", "reasoning"], True),
    "anthropic/claude-sonnet-4-6": ModelCaps("anthropic/claude-sonnet-4-6", "anthropic", True, 200000, "Anthropic frontier model.", ["code", "math", "reasoning"], True),
    "anthropic/claude-haiku-4-5": ModelCaps("anthropic/claude-haiku-4-5", "anthropic", True, 200000, "Anthropic fast model.", ["code", "reasoning"], True),
    "gemini/gemini-1.5-flash": ModelCaps("gemini/gemini-1.5-flash", "gemini", True, 1000000, "Gemini fast multimodal model.", ["code", "reasoning"], True),
    "gemini/gemini-1.5-pro": ModelCaps("gemini/gemini-1.5-pro", "gemini", True, 2000000, "Gemini large multimodal model.", ["code", "math", "reasoning"], True),
    "groq/llama-3.1-70b-versatile": ModelCaps("groq/llama-3.1-70b-versatile", "groq", False, 131072, "Groq-hosted Llama model.", ["reasoning"]),
    "groq/llama-3.1-8b-instant": ModelCaps("groq/llama-3.1-8b-instant", "groq", False, 131072, "Groq low-latency Llama model."),
}


SENSITIVE_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
)


def _provider_from_model(model_id: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return "ollama"


def caps_for(model_id: str) -> tuple[ModelCaps, ProviderCaps]:
    provider = _provider_from_model(model_id or "")
    provider_caps = PROVIDERS.get(provider, ProviderCaps(provider, False, 0.0, 0.0, None))
    model_caps = MODELS.get(
        model_id,
        ModelCaps(
            model_id=model_id,
            provider=provider_caps.provider,
            vision=False,
            context_window=4096,
            notes="Unknown model; using conservative defaults.",
            strengths=[],
            tool_use=False,
        ),
    )
    return model_caps, provider_caps


def supports_image_input(model_id: str) -> bool:
    return caps_for(model_id)[0].vision


_SENSITIVE_KEY_MARKERS = ("api_key", "apikey", "secret", "password", "authorization")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return (
        key in SENSITIVE_ENV_KEYS
        or any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)
        or lowered.endswith("token")  # token, access_token, refreshToken; not max_tokens or tokens_in
    )


def redact_config(cfg: dict) -> dict:
    """Copy of cfg without credential fields and with secret-looking values scrubbed.

    Numbers are never treated as credentials, so usage counters such as
    tokens_in or prompt_tokens survive.
    """
    def redact(value):
        if isinstance(value, dict):
            result = {}
            for key, nested in value.items():
                if _is_sensitive_key(str(key)) and not isinstance(nested, (int, float)):
                    continue
                result[key] = redact(nested)
            return result
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            return scrub_secret_values(value)
        return value

    return redact(deepcopy(cfg or {}))
