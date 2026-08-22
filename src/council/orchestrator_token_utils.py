import tiktoken
import litellm

TOKEN_SAFETY_MARGIN = 1.15

_MODEL_TOKEN_MULTIPLIERS = (
    (("gpt-", "gpt3", "gpt4", "o1", "o3", "o4", "chatgpt", "text-embedding", "davinci", "curie"), 1.0),
    (("llama-3", "llama3", "meta-llama-3"), 1.08),
    (("qwen2", "qwen-2", "deepseek"), 1.15),
    (("gemma", "gemma2", "gemma3"), 1.20),
    (("mistral", "mixtral"), 1.12),
    (("claude", "anthropic"), 1.05),
    (("gemini",), 1.05),
)

_TOKEN_ENCODINGS: dict[str, object] = {}


def _is_openai_model(model: str) -> bool:
    base = (model or "").replace("ollama/", "").split("/")[-1].lower()
    return any(base.startswith(prefix) for prefix in _MODEL_TOKEN_MULTIPLIERS[0][0])


def _token_multiplier_for(model: str) -> float:
    base = (model or "").replace("ollama/", "").split("/")[-1].lower()
    for prefixes, multiplier in _MODEL_TOKEN_MULTIPLIERS:
        if any(base.startswith(prefix) for prefix in prefixes):
            return multiplier
    return TOKEN_SAFETY_MARGIN


def _count_tokens(model: str, text: str) -> int:
    text = text or ""
    try:
        encoding_key = model or "default"
        if encoding_key not in _TOKEN_ENCODINGS:
            try:
                _TOKEN_ENCODINGS[encoding_key] = tiktoken.encoding_for_model(model.replace("ollama/", ""))
            except KeyError:
                _TOKEN_ENCODINGS[encoding_key] = tiktoken.get_encoding("cl100k_base")
        count = len(_TOKEN_ENCODINGS[encoding_key].encode(text))
    except Exception:
        try:
            count = litellm.token_counter(model=model, text=text)
        except Exception:
            count = len(text) // 4
    multiplier = _token_multiplier_for(model)
    if multiplier != 1.0:
        count = int(count * multiplier)
    return count


def _truncate_to_token_budget(model: str, text: str, max_tokens: int) -> str:
    marker = "\n[truncated]"
    if max_tokens <= 0:
        return ""
    if _count_tokens(model, text) <= max_tokens:
        return text

    # If even the bare marker doesn't fit, return nothing.
    if _count_tokens(model, marker) > max_tokens:
        return ""

    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if _count_tokens(model, candidate + marker) <= max_tokens:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best + marker


def _render_fair_sections(model: str, items: list[tuple[str, str]], budget: int, head_fmt: str) -> str:
    """Render labelled sections so each item gets an EQUAL share of the token
    budget and is individually truncated. Prevents the tail-drop bias where the
    last members are always the ones cut under context pressure."""
    if not items or budget <= 0:
        return ""
    per_item = max(1, budget // len(items))
    out = ""
    for label, text in items:
        head = head_fmt.format(label=label)
        body_budget = max(1, per_item - _count_tokens(model, head) - 2)
        out += head + _truncate_to_token_budget(model, text, body_budget) + "\n\n"
    return out
