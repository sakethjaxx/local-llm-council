"""Consensus gate — decides whether Phase 2 (cross-review) is worth running.

Agreement is judged on each member's explicit STANCE line (verdict + confidence),
not on text similarity: two analyses can share vocabulary while reaching opposite
conclusions. Embedding similarity is still computed, but only as a divergence
telemetry signal stored on the run.
"""

import asyncio
import re

import litellm
import numpy as np

from llm_council.cloud_keys import litellm_kwargs_for_model
from llm_council.embeddings import get_embedder
from llm_council.logging_utils import get_logger


logger = get_logger(__name__)

# Canonical verdicts plus the synonyms small local models tend to emit instead of
# the exact PROCEED/HOLD/MIXED tokens. Anything not listed here fails safe into
# debate (extract_stance returns None), so widening this map never fabricates
# agreement — it only recovers a skippable verdict the strict token would have lost.
_VERDICT_SYNONYMS = {
    "PROCEED": "PROCEED", "GO": "PROCEED", "SHIP": "PROCEED", "APPROVE": "PROCEED",
    "YES": "PROCEED", "ACCEPT": "PROCEED", "SUPPORT": "PROCEED", "ENDORSE": "PROCEED",
    "HOLD": "HOLD", "STOP": "HOLD", "BLOCK": "HOLD", "WAIT": "HOLD", "NO": "HOLD",
    "REJECT": "HOLD", "OPPOSE": "HOLD", "DEFER": "HOLD",
    "MIXED": "MIXED", "SPLIT": "MIXED", "UNSURE": "MIXED", "NEUTRAL": "MIXED",
    "UNDECIDED": "MIXED",
}

STANCE_RE = re.compile(
    r"^\s*\**\s*STANCE\s*\**\s*:\s*\**\s*([A-Za-z]+)\s*\**"
    r"(?:\s*\|\s*\**\s*CONFIDENCE\s*\**\s*:\s*\**\s*(\d{1,2})\s*\**)?"
    r"(?:\s*\|\s*(.*))?",
    re.IGNORECASE | re.MULTILINE,
)


def extract_stance(text: str) -> dict | None:
    """Pull the last STANCE line from an analysis. None if the member didn't emit
    a line whose verdict maps to a known stance — the fail-safe path into debate."""
    matches = STANCE_RE.findall(text or "")
    if not matches:
        return None
    for raw_verdict, confidence, summary in reversed(matches):
        verdict = _VERDICT_SYNONYMS.get(raw_verdict.upper())
        if verdict is None:
            continue
        return {
            "verdict": verdict,
            "confidence": int(confidence) if confidence else None,
            "summary": summary.strip().strip("*") if summary else "",
        }
    return None


async def classify_stance_fallback(text: str, model: str) -> dict | None:
    """Recover a stance when a member omitted the STANCE line.

    One tiny zero-temperature call to the same model: classify the analysis
    as PROCEED/HOLD/MIXED in a single word. An unmappable answer returns None,
    which keeps the fail-safe (missing stance → debate) intact.
    """
    if not (text or "").strip():
        return None
    prompt = (
        "Below is an analysis a reviewer wrote. Classify the reviewer's overall stance.\n"
        "Answer with exactly ONE word: PROCEED (they endorse the proposal), "
        "HOLD (they oppose it or want it blocked), or MIXED (genuinely split).\n\n"
        f"ANALYSIS:\n{text[:4000]}\n\nONE-WORD ANSWER:"
    )
    try:
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
            **litellm_kwargs_for_model(model),
        )
        raw = (resp.choices[0].message.content or "").strip().upper()
        word = re.sub(r"[^A-Z]", "", raw.split()[0]) if raw.split() else ""
        verdict = _VERDICT_SYNONYMS.get(word)
        if verdict is None:
            logger.info("stance_fallback_unmappable", extra={"model": model, "answer": raw[:40]})
            return None
        return {"verdict": verdict, "confidence": None, "summary": "(stance recovered by fallback classifier)"}
    except Exception as e:
        logger.warning("stance_fallback_failed", extra={"model": model, "error": str(e)})
        return None


async def resolve_stances(analyses: dict, member_models: dict | None = None) -> tuple[dict, dict]:
    """Extract each member's stance, falling back to a cheap classification call on miss.

    Returns (stances, sources) — sources maps member → "native" | "fallback";
    members with no recoverable stance are absent from both.
    """
    stances: dict = {}
    sources: dict = {}
    fallback_targets = []
    for member, text in analyses.items():
        stance = extract_stance(text)
        if stance is not None:
            stances[member] = stance
            sources[member] = "native"
        elif member_models and member_models.get(member):
            fallback_targets.append(member)

    if fallback_targets:
        results = await asyncio.gather(
            *(classify_stance_fallback(analyses[member], member_models[member]) for member in fallback_targets),
            return_exceptions=True,
        )
        for member, result in zip(fallback_targets, results):
            if isinstance(result, dict):
                stances[member] = result
                sources[member] = "fallback"
    return stances, sources


def _average_similarity(analyses: dict) -> float:
    texts = list(analyses.values())
    model = get_embedder()
    embeddings = model.encode(texts)
    norm = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized_embs = embeddings / norm
    sim_matrix = np.dot(normalized_embs, normalized_embs.T)
    n = sim_matrix.shape[0]
    upper_tri = sim_matrix[np.triu_indices(n, k=1)]
    return float(np.mean(upper_tri))


async def should_skip(analyses: dict, member_models: dict | None = None) -> tuple[bool, float, dict]:
    """Decide whether to skip Phase 2.

    Returns (skip, similarity_score, info) where info carries:
      reason        — human-readable explanation of the decision
      stances       — stance per member (members without one are absent)
      stance_sources — per member: "native" (STANCE line) or "fallback" (recovered)
      split         — True only when members took explicitly opposing stances

    When member_models is provided, members that omit the STANCE line get one
    cheap zero-temp classification call before we give up on them.
    """
    info: dict = {"reason": "", "stances": {}, "stance_sources": {}, "split": False}

    if len(analyses) < 2:
        info["reason"] = "Single member — nothing to debate."
        return False, 0.0, info

    try:
        score = await asyncio.to_thread(_average_similarity, analyses)
    except Exception as e:
        logger.exception("smart_phase_similarity_failed", extra={"error": str(e)})
        score = 0.0

    stances, sources = await resolve_stances(analyses, member_models)
    info["stances"] = stances
    info["stance_sources"] = sources

    missing = [member for member in analyses if member not in stances]
    if missing:
        info["reason"] = (
            f"No stance recoverable from {', '.join(missing)} — cannot verify agreement, running cross-review."
        )
        logger.info("smart_phase_decision", extra={"skip": False, "reason": "stance_missing", "score": round(score, 4)})
        return False, score, info

    mixed = [member for member, stance in stances.items() if stance["verdict"] == "MIXED"]
    if mixed:
        info["reason"] = f"{', '.join(mixed)} took a MIXED stance — running cross-review to resolve it."
        logger.info("smart_phase_decision", extra={"skip": False, "reason": "mixed_stance", "score": round(score, 4)})
        return False, score, info

    verdicts = {stance["verdict"] for stance in stances.values()}
    if len(verdicts) == 1:
        verdict = next(iter(verdicts))
        confidences = [stance["confidence"] for stance in stances.values() if stance["confidence"] is not None]
        conf_note = f", avg confidence {sum(confidences) / len(confidences):.0f}/10" if confidences else ""
        recovered = sum(1 for source in sources.values() if source == "fallback")
        recovery_note = f" ({recovered} stance{'s' if recovered != 1 else ''} recovered by fallback)" if recovered else ""
        info["reason"] = (
            f"All {len(stances)} members independently reached {verdict}{conf_note}"
            f"{recovery_note} — skipping cross-review."
        )
        logger.info("smart_phase_decision", extra={"skip": True, "reason": "unanimous", "score": round(score, 4)})
        return True, score, info

    info["split"] = True
    positions = ", ".join(f"{member}={stance['verdict']}" for member, stance in stances.items())
    info["reason"] = f"Stances split ({positions}) — running cross-review and rebuttal."
    logger.info("smart_phase_decision", extra={"skip": False, "reason": "split", "score": round(score, 4)})
    return False, score, info


async def check_unanimous_consensus(analyses: dict) -> bool:
    skip, _, _ = await should_skip(analyses)
    return skip
