"""Council trust signals — grounding enforcement and the aggregate confidence score.

Pure functions over already-computed run facts. No LLM calls, no I/O.

Grounding: every chairman consensus/dispute point must name at least one real
member label. Points that don't are stripped before display (never shown as
consensus) and reported honestly.

Council Confidence: one 0-100 signal combining seat diversity, stance agreement,
grounding, and chairman parse quality. Deliberately conservative — clones
agreeing must score lower than diverse models converging after real debate.
"""

from typing import Any, Optional


def _point_is_grounded(point: str, lowered_labels: list[str]) -> bool:
    lowered = str(point).lower()
    return any(label in lowered for label in lowered_labels)


def enforce_grounding(chairman_result: dict, member_labels: list[str], threshold: float = 0.5) -> tuple[dict, dict]:
    """Strip consensus/dispute points that name no real member.

    Returns (enforced_result, report). Stripping only happens when the grounding
    ratio falls below `threshold` — above it, occasional shorthand is tolerated
    but still reported. report = {ratio, removed, kept, enforced}.
    """
    lowered_labels = [label.lower() for label in member_labels if label]
    consensus = [str(p) for p in (chairman_result.get("consensus") or [])]
    disputes = [str(p) for p in (chairman_result.get("disputes") or [])]
    points = consensus + disputes

    if not points or not lowered_labels:
        return chairman_result, {"ratio": None, "removed": 0, "kept": len(points), "enforced": False}

    grounded_count = sum(1 for point in points if _point_is_grounded(point, lowered_labels))
    ratio = round(grounded_count / len(points), 3)

    if ratio >= threshold:
        return chairman_result, {"ratio": ratio, "removed": 0, "kept": len(points), "enforced": False}

    enforced = dict(chairman_result)
    enforced["consensus"] = [p for p in consensus if _point_is_grounded(p, lowered_labels)]
    enforced["disputes"] = [p for p in disputes if _point_is_grounded(p, lowered_labels)]
    removed = len(points) - len(enforced["consensus"]) - len(enforced["disputes"])
    return enforced, {
        "ratio": ratio,
        "removed": removed,
        "kept": len(enforced["consensus"]) + len(enforced["disputes"]),
        "enforced": True,
    }


def agreement_state(
    deliberated: bool,
    stances: dict,
    member_count: int,
    split: bool,
    converged_after_rebuttal: Optional[bool],
) -> str:
    """Classify how the council actually reached its position."""
    if not deliberated:
        return "not_deliberated"
    if len(stances) < member_count:
        return "unknown"
    verdicts = {stance["verdict"] for stance in stances.values()}
    if len(verdicts) == 1 and "MIXED" not in verdicts and not split:
        return "unanimous"
    if split and converged_after_rebuttal:
        return "split_converged"
    if split:
        return "split_unresolved"
    return "unknown"


_AGREEMENT_SCORES = {
    "unanimous": 1.0,
    "split_converged": 0.85,
    "split_unresolved": 0.45,
    "unknown": 0.5,
    "not_deliberated": 0.55,
}

_AGREEMENT_NOTES = {
    "unanimous": "all seats independently agreed",
    "split_converged": "seats split, then converged after rebuttal",
    "split_unresolved": "seats split and did not converge",
    "unknown": "stances could not be fully verified",
    "not_deliberated": "fast mode — independent opinions, no cross-examination",
}

_PARSE_SCORES = {
    "json": 1.0,
    "fenced_json": 0.95,
    "regex_extracted": 0.5,
    "parse_failed": 0.15,
}

CLONE_CONFIDENCE_CAP = 45

_NON_BEHAVIOR_KEYS = {"label", "color", "icon"}


def _freeze(value: Any):
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _seat_behavior_signature(cfg: dict) -> tuple:
    if not isinstance(cfg, dict):
        return (("model", str(cfg or "")),)
    behavioral = {
        str(key): value
        for key, value in cfg.items()
        if key not in _NON_BEHAVIOR_KEYS
    }
    return tuple(sorted((key, _freeze(value)) for key, value in behavioral.items()))


def roster_diversity(member_models: list[str], member_configs: Optional[list[dict]] = None) -> dict:
    seats = max(1, len(member_models))
    distinct_models = len({model for model in member_models if model}) or 1
    behavior_configs = member_configs if member_configs is not None else [{"model": model} for model in member_models]
    distinct_behaviors = len({_seat_behavior_signature(cfg) for cfg in behavior_configs}) or 1
    exact_clones = seats > 1 and distinct_models == 1 and distinct_behaviors == 1
    reused_single_model = seats > 1 and distinct_models == 1 and distinct_behaviors > 1
    return {
        "seats": seats,
        "distinct_models": distinct_models,
        "distinct_behaviors": distinct_behaviors,
        "exact_clones": exact_clones,
        "reused_single_model": reused_single_model,
    }


def council_confidence(
    member_models: list[str],
    agreement: str,
    grounding_ratio: Optional[float],
    parse_tier: Optional[str],
    member_configs: Optional[list[dict]] = None,
) -> dict:
    """Combine run facts into one honest 0-100 confidence signal.

    Components (each 0-1): diversity 30%, agreement 30%, grounding 25%, parse 15%.
    Exact clone councils are capped; single-model councils with distinct
    personas or parameters are discounted, but not capped.
    """
    diversity_info = roster_diversity(member_models, member_configs)
    seats = diversity_info["seats"]
    distinct = diversity_info["distinct_models"]
    distinct_behaviors = diversity_info["distinct_behaviors"]
    if diversity_info["exact_clones"]:
        diversity = 0.2
    elif diversity_info["reused_single_model"]:
        diversity = 0.45
    elif distinct == seats:
        diversity = 1.0
    else:
        behavior_ratio = min(1.0, distinct_behaviors / seats)
        diversity = max(0.6, min(0.85, 0.45 + (0.4 * behavior_ratio)))

    agreement_score = _AGREEMENT_SCORES.get(agreement, 0.5)
    grounding_score = grounding_ratio if grounding_ratio is not None else 0.5
    parse_score = _PARSE_SCORES.get(parse_tier or "", 0.5)

    raw = (
        0.30 * diversity
        + 0.30 * agreement_score
        + 0.25 * grounding_score
        + 0.15 * parse_score
    )
    score = round(raw * 100)

    capped = False
    if diversity_info["exact_clones"] and score > CLONE_CONFIDENCE_CAP:
        score = CLONE_CONFIDENCE_CAP
        capped = True

    notes = [_AGREEMENT_NOTES.get(agreement, "agreement unclear")]
    if capped:
        notes.insert(0, f"capped at {CLONE_CONFIDENCE_CAP}: all seats ran the same model and behavior")
    elif diversity_info["reused_single_model"]:
        notes.append(f"one base model reused across {distinct_behaviors} configured seats")
    elif distinct < seats:
        notes.append(f"{distinct} distinct model{'s' if distinct != 1 else ''} across {seats} seats")
    if grounding_ratio is not None and grounding_ratio < 0.6:
        notes.append(f"only {round(grounding_ratio * 100)}% of verdict points trace to named members")

    return {
        "score": max(0, min(100, score)),
        "components": {
            "diversity": round(diversity, 3),
            "agreement": round(agreement_score, 3),
            "grounding": round(grounding_score, 3),
            "parse": round(parse_score, 3),
        },
        "agreement_state": agreement,
        "clone_capped": capped,
        "diversity": diversity_info,
        "explanation": "; ".join(notes),
    }
