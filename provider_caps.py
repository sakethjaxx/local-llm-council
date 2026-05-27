from copy import deepcopy
from dataclasses import dataclass, field


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


def redact_config(cfg: dict) -> dict:
    def redact(value):
        if isinstance(value, dict):
            result = {}
            for key, nested in value.items():
                key_text = str(key)
                lowered = key_text.lower()
                if key_text in SENSITIVE_ENV_KEYS or any(marker in lowered for marker in ("api_key", "secret", "token")):
                    continue
                result[key] = redact(nested)
            return result
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(deepcopy(cfg or {}))
