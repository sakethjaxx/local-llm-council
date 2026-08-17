import os
import re
import numpy as np
import asyncio

from embeddings import get_embedder
from logging_utils import get_logger


logger = get_logger(__name__)

SKIP_THRESHOLD = float(os.getenv("COUNCIL_SMART_PHASE_THRESHOLD", "0.88"))

# MiniLM (all-MiniLM-L6-v2) truncates input at ~256 word-pieces. Council
# analyses run 500-1500 tokens, so encoding the whole string only "sees" the
# intro and misses the RISKS/RECOMMENDATIONS where members actually diverge.
# We split each analysis into windows, embed each, and mean-pool into a single
# document vector that covers the full text.
_CHUNK_WORDS = 180

# High-precision explicit-disagreement phrases. Unlike bare words ("but",
# "risk", "concern" — which appear in the Phase 1 template headers and fire on
# almost every run), these multi-word phrases signal a real stance clash and
# rarely false-positive. Any hit forces the debate regardless of similarity.
DISAGREEMENT_PATTERNS = [
    r"\bi disagree\b",
    r"\bstrongly disagree\b",
    r"\bdo not agree\b",
    r"\bdon't agree\b",
    r"\bthis is (?:incorrect|wrong|false|mistaken)\b",
    r"\bthat is (?:incorrect|wrong|false)\b",
    r"\bcontradicts?\b",
    r"\bfundamentally (?:flawed|wrong)\b",
    r"\bi'd push back\b",
    r"\bi would push back\b",
    r"\bdo not ship\b",
    r"\bcannot ship\b",
    r"\bshould not ship\b",
    r"\bmust not ship\b",
    r"\bunacceptable risk\b",
    r"\bcritical flaw\b",
    r"\bshowstopper\b",
    r"\bblocking issue\b",
    r"\bnot ready for production\b",
    r"\bnot production ready\b",
    r"\bflawed assumption\b",
    r"\binvalid assumption\b",
]
_DISAGREEMENT_RE = re.compile("|".join(DISAGREEMENT_PATTERNS), re.IGNORECASE)
_POSITION_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(SHIP|REVISE|BLOCK|INSUFFICIENT\s+EVIDENCE)\b",
    re.IGNORECASE | re.MULTILINE,
)
_TEMPLATE_HEADERS_RE = re.compile(
    r"^##\s+(STRENGTHS|RISKS|RECOMMENDATIONS|POSITION)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_template_headers(text: str) -> str:
    """Strip repeated markdown template headers so embeddings reflect substantive
    reasoning rather than identical structural boilerplate."""
    cleaned = _TEMPLATE_HEADERS_RE.sub("", text).strip()
    return cleaned if cleaned else text


def _has_explicit_disagreement(analyses: dict) -> bool:
    all_text = " ".join(analyses.values())
    return bool(_DISAGREEMENT_RE.search(all_text))


def _positions(analyses: dict) -> set[str]:
    """Extract the first explicit Phase-1 position from each analysis."""
    positions = set()
    for analysis in analyses.values():
        section = re.split(r"^##\s+POSITION\s*$", analysis, flags=re.IGNORECASE | re.MULTILINE)
        if len(section) < 2:
            continue
        match = _POSITION_RE.search(section[1])
        if match:
            positions.add(" ".join(match.group(1).upper().split()))
    return positions


def _document_vector(model, text: str) -> np.ndarray:
    words = text.split()
    if not words:
        chunks = [""]
    else:
        chunks = [" ".join(words[i:i + _CHUNK_WORDS]) for i in range(0, len(words), _CHUNK_WORDS)]
    embs = model.encode(chunks)
    embs = np.asarray(embs, dtype=np.float64)
    doc = embs.mean(axis=0)
    norm = np.linalg.norm(doc)
    return doc / norm if norm > 0 else doc


async def should_skip(analyses: dict) -> tuple[bool, float]:
    if len(analyses) < 2:
        return False, 0.0

    def compute_similarity():
        model = get_embedder()
        vectors = np.stack([_document_vector(model, _strip_template_headers(t)) for t in analyses.values()])
        sim_matrix = np.dot(vectors, vectors.T)
        n = sim_matrix.shape[0]
        upper_tri = sim_matrix[np.triu_indices(n, k=1)]
        # Gate on the MINIMUM pairwise similarity, not the mean: a single
        # dissenting member (the exact case Phase 2 exists to surface) must be
        # able to block the skip even if every other pair agrees strongly.
        return float(np.min(upper_tri)), float(np.mean(upper_tri))

    try:
        min_sim, mean_sim = await asyncio.to_thread(compute_similarity)
        forced = _has_explicit_disagreement(analyses)
        positions = _positions(analyses)
        position_conflict = len(positions) > 1
        skip = (min_sim > SKIP_THRESHOLD) and not forced and not position_conflict
        logger.info(
            "smart_phase_similarity",
            extra={
                "min_pairwise": round(min_sim, 4),
                "mean_pairwise": round(mean_sim, 4),
                "threshold": SKIP_THRESHOLD,
                "explicit_disagreement": forced,
                "positions": sorted(positions),
                "position_conflict": position_conflict,
                "decision": "skip" if skip else "debate",
            },
        )
        return skip, min_sim
    except Exception as e:
        logger.exception("smart_phase_failed", extra={"error": str(e)})
        return False, 0.0
