"""Consensus gate — decides whether Phase 2 (cross-review) is worth running.

Agreement is judged on each member's explicit STANCE line (verdict + confidence),
not on text similarity: two analyses can share vocabulary while reaching opposite
conclusions. Embedding similarity is still computed, but only as a divergence
telemetry signal stored on the run.
"""

import asyncio
import re

import numpy as np

from embeddings import get_embedder
from logging_utils import get_logger


logger = get_logger(__name__)

STANCE_RE = re.compile(
    r"^\s*\**\s*STANCE\s*\**\s*:\s*\**\s*(PROCEED|HOLD|MIXED)\s*\**"
    r"(?:\s*\|\s*\**\s*CONFIDENCE\s*\**\s*:\s*\**\s*(\d{1,2})\s*\**)?"
    r"(?:\s*\|\s*(.*))?",
    re.IGNORECASE | re.MULTILINE,
)


def extract_stance(text: str) -> dict | None:
    """Pull the last STANCE line from an analysis. None if the member didn't emit one."""
    matches = STANCE_RE.findall(text or "")
    if not matches:
        return None
    verdict, confidence, summary = matches[-1]
    return {
        "verdict": verdict.upper(),
        "confidence": int(confidence) if confidence else None,
        "summary": summary.strip().strip("*") if summary else "",
    }


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


async def should_skip(analyses: dict) -> tuple[bool, float, dict]:
    """Decide whether to skip Phase 2.

    Returns (skip, similarity_score, info) where info carries:
      reason  — human-readable explanation of the decision
      stances — extracted stance per member (members without one are absent)
      split   — True only when members took explicitly opposing stances
    """
    info: dict = {"reason": "", "stances": {}, "split": False}

    if len(analyses) < 2:
        info["reason"] = "Single member — nothing to debate."
        return False, 0.0, info

    try:
        score = await asyncio.to_thread(_average_similarity, analyses)
    except Exception as e:
        logger.exception("smart_phase_similarity_failed", extra={"error": str(e)})
        score = 0.0

    stances = {member: extract_stance(text) for member, text in analyses.items()}
    info["stances"] = {member: stance for member, stance in stances.items() if stance}

    missing = [member for member, stance in stances.items() if stance is None]
    if missing:
        info["reason"] = (
            f"No STANCE line from {', '.join(missing)} — cannot verify agreement, running cross-review."
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
        info["reason"] = f"All {len(stances)} members independently reached {verdict}{conf_note} — skipping cross-review."
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
