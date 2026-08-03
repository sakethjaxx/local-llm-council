"""Hardware-aware council roster suggestion.

The council runs Phase 1 in parallel, so every *distinct* seat model may be
resident in Ollama at the same time. A naive RAM-tier lookup that assigns three
different 7-9B models will exceed the memory ceiling on a 16GB machine (three
models ~= 15GB of weights, plus KV cache and OS overhead), which makes Ollama
thrash — evicting and reloading models between calls — until requests time out.

This module instead sizes the roster to a *concurrent memory budget*:

    budget = total_ram - reserve
    a set of distinct models fits iff  EFF * sum(weights) <= budget

`EFF` pads each model's on-disk weight for the KV cache and activation memory it
needs under load. Real model diversity is only offered when at least two
"strong" (7B-class) models fit concurrently; otherwise a single best-fit model
is shared across all seats so it stays resident (fast, no swap, no timeouts).
"""

import time

import psutil

# Approx resident weight footprint in GB per known Ollama model.
_MODEL_GB = {
    "ollama/llama3.1:70b": 40.0,
    "ollama/qwen2.5:32b": 20.0,
    "ollama/deepseek-r1:32b": 20.0,
    "ollama/qwen2.5:14b": 9.0,
    "ollama/deepseek-r1:14b": 9.0,
    "ollama/gemma2:9b": 5.4,
    "ollama/llama3.1:8b": 4.9,
    "ollama/qwen2.5:7b": 4.7,
    "ollama/qwen2.5:3b": 2.0,
    "ollama/llama3.2:3b": 2.0,
    "ollama/gemma2:2b": 1.7,
}

# Candidate models best -> worst (quality-ranked, not size-ranked). Fit is a
# separate constraint; this list only decides *preference* among models that fit.
# Qwen leads its size class because it is the most reliable at the structured
# JSON the chairman must emit.
_PREF = [
    "ollama/llama3.1:70b",
    "ollama/qwen2.5:32b",
    "ollama/deepseek-r1:32b",
    "ollama/qwen2.5:14b",
    "ollama/deepseek-r1:14b",
    "ollama/qwen2.5:7b",
    "ollama/llama3.1:8b",
    "ollama/gemma2:9b",
    "ollama/qwen2.5:3b",
    "ollama/llama3.2:3b",
    "ollama/gemma2:2b",
]

# Concurrency pad: weights * EFF approximates real memory under active inference
# (KV cache + activations). Tuned so 16GB -> single 7B, 32GB -> three 7-9B.
_EFF = 1.4

# A model must be at least this big (GB) to count toward *diversity*. Prevents
# padding a "diverse" roster with weak 3B models that add noise, not signal.
_STRONG_GB = 4.0

# Cache the installed-model probe — get_default_council_config() is called on
# many code paths, and each probe shells out to `ollama list`.
_installed_cache: tuple[float, list[str]] | None = None
_INSTALLED_TTL = 60.0


def _normalize(model: str) -> str:
    """Bare ollama tag ('qwen2.5:7b') -> registry key ('ollama/qwen2.5:7b')."""
    m = model.strip()
    if not m:
        return m
    return m if m.startswith("ollama/") else f"ollama/{m}"


def _installed_models() -> list[str]:
    """Registry keys for models installed locally, or [] if none / unavailable."""
    global _installed_cache
    now = time.monotonic()
    if _installed_cache and now - _installed_cache[0] < _INSTALLED_TTL:
        return _installed_cache[1]
    tags: list[str] = []
    try:
        # Lazy import avoids a circular dependency (ollama_manager imports us).
        from ollama_manager import get_installed_models

        tags = [_normalize(t) for t in get_installed_models()]
    except Exception:
        tags = []
    _installed_cache = (now, tags)
    return tags


def _reserve_gb(total_ram_gb: float) -> float:
    """RAM held back for the OS, this app, and the sentence-transformers embedder."""
    return max(3.0, 0.2 * total_ram_gb)


def _fits(weights_gb: float, budget_gb: float) -> bool:
    return _EFF * weights_gb <= budget_gb


_PERSONAS = {
    "architect": (
        "Lead Architect", "#4D6BFE", "🐋",
        "You are the Lead Architect. Focus on SOLID principles, design patterns, "
        "maintainability, and code structure. Favor pragmatic, local-first "
        "solutions and call out unnecessary complexity.",
    ),
    "security": (
        "Security Auditor", "#FF4444", "🛡️",
        "You are the Senior Security Auditor. Focus strictly on OWASP "
        "vulnerabilities, injection flaws, unsafe defaults, and exposure risk. "
        "Prefer defenses that work in local self-hosted deployments.",
    ),
    "perf": (
        "Performance Eng", "#00FF00", "⚡",
        "You are the Performance Engineer. Focus on algorithmic cost, memory "
        "pressure, context bloat, and latency. Optimize for hardware-constrained "
        "local inference.",
    ),
    "chairman": (
        "Chairman", "#F5C842", "👑",
        "You are the Chairman. Synthesize the council and make a final verdict. "
        "Prefer recommendations that preserve free, open-weight, local execution.",
    ),
}


def _seat(role: str, model: str) -> dict:
    label, color, icon, persona = _PERSONAS[role]
    return {"label": label, "model": model, "color": color, "icon": icon, "persona": persona}


def _build_config(architect_model: str, security_model: str, perf_model: str, chairman_model: str) -> dict:
    return {
        "architect": _seat("architect", architect_model),
        "security": _seat("security", security_model),
        "perf": _seat("perf", perf_model),
        "chairman": _seat("chairman", chairman_model),
    }


def _get_model_gb(model: str) -> float:
    if model in _MODEL_GB:
        return _MODEL_GB[model]
    tag = model.split(":")[-1].lower() if ":" in model else ""
    if "70b" in tag: return 40.0
    if "32b" in tag or "33b" in tag: return 20.0
    if "14b" in tag or "15b" in tag: return 9.0
    if "8b" in tag or "9b" in tag: return 5.0
    if "7b" in tag: return 4.5
    if "3b" in tag or "4b" in tag: return 2.2
    if "1b" in tag or "2b" in tag: return 1.5
    return 4.5


def _pick_roster(total_ram_gb: float, installed: list[str] | None) -> dict:
    """Choose the best-fitting roster for the concurrent memory budget."""
    reserve = _reserve_gb(total_ram_gb)
    budget = total_ram_gb - reserve

    inst = set(installed or [])
    # Prefer models we can actually run right now; fall back to the full known
    # list (and recommend pulling) if nothing suitable is installed.
    available = [m for m in _PREF if m in inst] if inst else []
    from_installed = bool(available)
    pool = available if from_installed else list(_PREF)

    # --- Try real diversity: distinct STRONG models that fit concurrently. ---
    diverse: list[str] = []
    total_w = 0.0
    for m in pool:
        m_gb = _get_model_gb(m)
        if m_gb < _STRONG_GB:
            continue
        if len(diverse) >= 3:
            break
        if _fits(total_w + m_gb, budget):
            diverse.append(m)
            total_w += m_gb

    if len(diverse) >= 2:
        seats = list(diverse)
        while len(seats) < 3:
            seats.append(seats[-1])  # reuse an already-resident model, no new load
        chairman = diverse[0]        # strongest fitted model synthesizes
        strategy = "diverse"
        roster_models = list(dict.fromkeys(diverse + [chairman]))
        reason = (
            f"{len(diverse)} distinct models fit the ~{budget:.0f}GB concurrent "
            f"budget — running a genuinely diverse council."
        )
    else:
        # --- Single best-fit model shared across every seat (stays resident). ---
        best = next((m for m in pool if _fits(_get_model_gb(m), budget)), None)
        if best is None:
            best = pool[-1]  # nothing fits cleanly; best-effort smallest
        seats = [best, best, best]
        chairman = best
        strategy = "shared"
        roster_models = [best]
        reason = (
            f"A diverse roster would exceed the ~{budget:.0f}GB concurrent memory "
            f"budget and thrash, so all seats share {best.split('/')[-1]} — it "
            f"stays resident for fast, reliable runs."
        )

    config = _build_config(seats[0], seats[1], seats[2], chairman)
    to_pull = [m for m in roster_models if m not in inst]
    recommended_pull = [f"ollama pull {m.split('/', 1)[1]}" for m in to_pull]

    model_names = ", ".join(m.split("/", 1)[1] for m in roster_models)
    tier_name = (
        f"{total_ram_gb:.0f}GB RAM · {strategy} roster · {model_names}"
        + ("" if from_installed else " (not yet installed)")
    )
    return {
        "strategy": strategy,
        "budget_gb": round(budget, 1),
        "reason": reason,
        "tier_name": tier_name,
        "config": config,
        "recommended_pull": recommended_pull,
        "from_installed": from_installed,
    }


def get_hardware_suggestion(installed_models: list[str] | None = None) -> dict:
    """Suggest a council roster sized to this machine's memory ceiling.

    `installed_models` (registry keys or bare tags) overrides local detection —
    used by tests. When omitted, the locally installed Ollama models are probed
    (and cached briefly) so the suggestion only proposes models that can run now.
    """
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    if installed_models is None:
        installed = _installed_models()
    else:
        installed = [_normalize(m) for m in installed_models]

    picked = _pick_roster(total_ram_gb, installed)
    return {
        "ram_gb": round(total_ram_gb, 1),
        "tier_name": picked["tier_name"],
        "strategy": picked["strategy"],
        "budget_gb": picked["budget_gb"],
        "reason": picked["reason"],
        "mode": "free-local-open-weights",
        "provider": "ollama",
        "config": picked["config"],
        "recommended_pull": picked["recommended_pull"],
        "from_installed": picked["from_installed"],
    }


def get_default_council_config() -> dict:
    return get_hardware_suggestion()["config"]
