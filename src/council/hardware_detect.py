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

The optional `mixed` strategy intentionally uses small models for concurrent
Phase 1 analysis, then loads the strongest single model that fits for chairman
synthesis. It favors final-answer quality on constrained hardware, at the cost
of one model reload between phases.
"""

import os
import platform
import shutil
import subprocess
import sys
import time
from functools import lru_cache

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

# Candidate models best -> worst when the machine already has them installed.
# Fit is a separate constraint; this list only decides preference among models
# that can actually run now.
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

# Bootstrap order for fresh installs or environments where `ollama list` cannot
# be queried. Keep this in the practical 7B/8B/9B tier so first run setup does
# not recommend a large model simply because RAM math says it might fit.
_BOOTSTRAP_PREF = [
    "ollama/qwen2.5:7b",
    "ollama/llama3.1:8b",
    "ollama/gemma2:9b",
    "ollama/qwen2.5:3b",
    "ollama/llama3.2:3b",
    "ollama/gemma2:2b",
    "ollama/qwen2.5:14b",
    "ollama/deepseek-r1:14b",
    "ollama/qwen2.5:32b",
    "ollama/deepseek-r1:32b",
    "ollama/llama3.1:70b",
]

# Concurrency pad: weights * EFF approximates real memory under active inference
# (KV cache + activations). Tuned so 16GB -> single 7B, 32GB -> three 7-9B.
_EFF = 1.4

# A model must be at least this big (GB) to count toward *diversity*. Prevents
# padding a "diverse" roster with weak 3B models that add noise, not signal.
_STRONG_GB = 4.0

# Cache the installed-model probe — get_default_council_config() is called on
# many code paths, and each probe is an HTTP round trip to the Ollama daemon.
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


@lru_cache(maxsize=1)
def _gpu_vram_gb() -> float | None:
    """Best-effort GPU memory Ollama can use; None means inference runs on the CPU.

    COUNCIL_GPU_VRAM_GB overrides detection (0 forces CPU mode) for GPUs this
    cannot see, such as AMD/ROCm or Intel.
    """
    override = os.getenv("COUNCIL_GPU_VRAM_GB", "").strip()
    if override:
        try:
            value = float(override)
            return value if value > 0 else None
        except ValueError:
            pass
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return psutil.virtual_memory().total / (1024 ** 3)  # unified memory, Metal
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            mib = [float(v) for v in out.split()]
            if mib:
                return max(mib) / 1024
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return None


def _cpu_bound(vram_gb: float | None) -> bool:
    """True when no GPU can hold a 7B-class model, so it would run on the CPU."""
    return vram_gb is None or vram_gb < _STRONG_GB


_PERSONAS = {
    "architect": (
        "Lead Architect", "#4D6BFE", "🐋",
        "You are the Lead Architect. Focus on SOLID principles, design patterns, "
        "maintainability, and code structure. Favor pragmatic, local-first "
        "solutions and call out unnecessary complexity.",
        0.25, 0.90,
    ),
    "security": (
        "Security Auditor", "#FF4444", "🛡️",
        "You are the Senior Security Auditor. Focus strictly on OWASP "
        "vulnerabilities, injection flaws, unsafe defaults, and exposure risk. "
        "Prefer defenses that work in local self-hosted deployments.",
        0.15, 0.85,
    ),
    "perf": (
        "Performance Eng", "#00FF00", "⚡",
        "You are the Performance Engineer. Focus on algorithmic cost, memory "
        "pressure, context bloat, and latency. Optimize for hardware-constrained "
        "local inference.",
        0.35, 0.95,
    ),
    "chairman": (
        "Chairman", "#F5C842", "👑",
        "You are the Chairman. Synthesize the council and make a final verdict. "
        "Prefer recommendations that preserve free, open-weight, local execution.",
        0.10, 0.80,
    ),
}


def _seat(role: str, model: str) -> dict:
    meta = _PERSONAS[role]
    seat_data = {
        "label": meta[0],
        "model": model,
        "color": meta[1],
        "icon": meta[2],
        "persona": meta[3],
    }
    if len(meta) >= 6:
        seat_data["temperature"] = meta[4]
        seat_data["top_p"] = meta[5]
    return seat_data


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


def _pick_mixed_roster(pool: list[str], budget: float) -> tuple[list[str], str] | None:
    """Return small concurrent analysts plus the best per-phase chairman.

    Phase 1 and the chairman phase run sequentially, so the chairman need only
    fit by itself. This is deliberately different from the default strategy,
    which minimizes model swapping by keeping the whole roster resident.
    """
    small = [m for m in pool if _get_model_gb(m) < _STRONG_GB]
    analysts: list[str] = []
    weights = 0.0
    for model in small:
        if len(analysts) == 3:
            break
        weight = _get_model_gb(model)
        if _fits(weights + weight, budget):
            analysts.append(model)
            weights += weight
    if not analysts:
        return None

    chairman = next((m for m in pool if _fits(_get_model_gb(m), budget)), None)
    if chairman is None:
        return None

    while len(analysts) < 3:
        analysts.append(analysts[-1])  # reuse a resident analyst model
    return analysts, chairman


def _pick_diverse_roster(pool: list[str], budget: float) -> tuple[list[str], str, list[str], str] | None:
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

    if len(diverse) < 2:
        return None

    seats = list(diverse)
    while len(seats) < 3:
        seats.append(seats[-1])
    chairman = diverse[0]
    roster_models = list(dict.fromkeys(diverse + [chairman]))
    reason = (
        f"{len(diverse)} distinct models fit the ~{budget:.0f}GB concurrent "
        f"budget — running a genuinely diverse council."
    )
    return seats, chairman, roster_models, reason


def _pick_shared_roster(pool: list[str], budget: float) -> tuple[list[str], str, list[str], str]:
    best = next((m for m in pool if _fits(_get_model_gb(m), budget)), None)
    if best is None:
        best = pool[-1]
    seats = [best, best, best]
    chairman = best
    roster_models = [best]
    reason = (
        f"A diverse roster would exceed the ~{budget:.0f}GB concurrent memory "
        f"budget and thrash, so all seats share {best.split('/')[-1]} — it "
        f"stays resident for fast, reliable runs."
    )
    return seats, chairman, roster_models, reason


def _pick_roster(
    total_ram_gb: float,
    installed: list[str] | None,
    requested_strategy: str = "auto",
    cpu_only: bool = False,
) -> dict:
    """Choose the best-fitting roster for the concurrent memory budget."""
    reserve = _reserve_gb(total_ram_gb)
    budget = total_ram_gb - reserve

    inst = set(installed or [])
    available = [m for m in _PREF if m in inst] if inst else []
    from_installed = bool(available)
    pool = available if from_installed else list(_BOOTSTRAP_PREF)

    if requested_strategy not in {"auto", "shared", "diverse", "mixed"}:
        requested_strategy = "auto"

    strategy = "shared"
    seats, chairman, roster_models, reason = None, None, None, None

    # On CPU a 7B model manages only a few tokens/s, so a council run takes the
    # better part of an hour. Auto keeps one small model loaded for every seat.
    small = [m for m in pool if _get_model_gb(m) < _STRONG_GB]
    if requested_strategy == "auto" and cpu_only and small:
        seats, chairman, roster_models, _ = _pick_shared_roster(small, budget)
        reason = (
            f"No GPU that can hold a 7B model was found, so models run on the CPU. "
            f"All seats share {chairman.split('/')[-1]}, a small model that stays loaded "
            f"for runs of minutes, not an hour. Set COUNCIL_GPU_VRAM_GB if a GPU was missed."
        )

    if requested_strategy == "mixed":
        mixed = _pick_mixed_roster(pool, budget)
        if mixed:
            seats, chairman = mixed
            strategy = "mixed"
            roster_models = list(dict.fromkeys(seats + [chairman]))
            analyst_peak = sum(_get_model_gb(m) for m in dict.fromkeys(seats)) * _EFF
            reason = (
                f"Small analyst models use about {analyst_peak:.1f}GB in Phase 1; "
                f"{chairman.split('/')[-1]} is the strongest model that fits the "
                f"~{budget:.0f}GB chairman phase. It reloads before synthesis."
            )

    if seats is None and requested_strategy in {"auto", "diverse"}:
        diverse_res = _pick_diverse_roster(pool, budget)
        if diverse_res is not None:
            seats, chairman, roster_models, reason = diverse_res
            strategy = "diverse"

    if seats is None:
        seats, chairman, roster_models, reason = _pick_shared_roster(pool, budget)
        strategy = "shared"

    if cpu_only and not small:
        reason += " No GPU was found and no small model is installed: `ollama pull qwen2.5:3b` makes runs much faster."

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
        "requires_phase_model_swap": strategy == "mixed",
    }


def get_hardware_suggestion(
    installed_models: list[str] | None = None,
    strategy: str = "auto",
) -> dict:
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

    vram_gb = _gpu_vram_gb()
    cpu_only = _cpu_bound(vram_gb)
    picked = _pick_roster(total_ram_gb, installed, strategy, cpu_only=cpu_only)
    return {
        "ram_gb": round(total_ram_gb, 1),
        "vram_gb": round(vram_gb, 1) if vram_gb else None,
        "compute": "cpu" if cpu_only else "gpu",
        "tier_name": picked["tier_name"],
        "strategy": picked["strategy"],
        "budget_gb": picked["budget_gb"],
        "reason": picked["reason"],
        "mode": "free-local-open-weights",
        "provider": "ollama",
        "config": picked["config"],
        "recommended_pull": picked["recommended_pull"],
        "from_installed": picked["from_installed"],
        "requires_phase_model_swap": picked["requires_phase_model_swap"],
    }


def get_default_council_config() -> dict:
    return get_hardware_suggestion()["config"]


def _tier_for_size(size_gb: float) -> str:
    if size_gb < 3.0:
        return "light"
    if size_gb < 6.0:
        return "medium"
    if size_gb < 10.0:
        return "heavy"
    return "very_heavy"


def get_model_catalog() -> dict:
    """Curated list of open-weight Ollama models with per-device compute guidance.

    Sizes come from `_MODEL_GB` (the same table the roster picker uses), so the
    "recommended" flag here always matches what `get_hardware_suggestion()` would
    actually pick for this machine — no second source of truth to drift out of sync.
    """
    from provider_caps import MODELS as PROVIDER_MODELS

    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    reserve = _reserve_gb(total_ram_gb)
    budget = total_ram_gb - reserve

    installed = set(_installed_models())
    suggestion = get_hardware_suggestion()
    recommended_models = {seat["model"] for seat in suggestion["config"].values()}

    entries = []
    for model_id, caps in PROVIDER_MODELS.items():
        if caps.provider != "ollama":
            continue
        tag = model_id.split("/", 1)[1]
        size_gb = _get_model_gb(model_id)
        entries.append({
            "tag": tag,
            "model_id": model_id,
            "size_gb": round(size_gb, 1),
            "min_ram_gb": round(size_gb * _EFF + 3.0, 1),
            "installed": model_id in installed,
            "fits_now": _fits(size_gb, budget),
            "recommended": model_id in recommended_models,
            "tier": _tier_for_size(size_gb),
            "notes": caps.notes,
            "strengths": caps.strengths,
        })
    # Tags pulled outside the curated registry (e.g. `ollama pull llama3.2` installs
    # llama3.2:latest) must still show as installed and selectable.
    uncurated = sorted(installed - set(PROVIDER_MODELS))
    if uncurated:
        from ollama_manager import installed_model_sizes_gb

        sizes = installed_model_sizes_gb()
        for model_id in uncurated:
            tag = model_id.split("/", 1)[1]
            size_gb = sizes.get(tag) or _get_model_gb(model_id)
            entries.append({
                "tag": tag,
                "model_id": model_id,
                "size_gb": round(size_gb, 1),
                "min_ram_gb": round(size_gb * _EFF + 3.0, 1),
                "installed": True,
                "fits_now": _fits(size_gb, budget),
                "recommended": model_id in recommended_models,
                "tier": _tier_for_size(size_gb),
                "notes": "Installed locally; not in the curated catalog.",
                "strengths": [],
            })
    entries.sort(key=lambda e: e["size_gb"])

    return {
        "ram_gb": round(total_ram_gb, 1),
        "budget_gb": round(budget, 1),
        "reserve_gb": round(reserve, 1),
        "concurrency_factor": _EFF,
        "recommended_tags": sorted(m.split("/", 1)[1] for m in recommended_models),
        "recommendation_reason": suggestion["reason"],
        "models": entries,
    }
