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
]
_DISAGREEMENT_RE = re.compile("|".join(DISAGREEMENT_PATTERNS), re.IGNORECASE)


def _has_explicit_disagreement(analyses: dict) -> bool:
    all_text = " ".join(analyses.values())
    return bool(_DISAGREEMENT_RE.search(all_text))


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
        vectors = np.stack([_document_vector(model, t) for t in analyses.values()])
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
        skip = (min_sim > SKIP_THRESHOLD) and not forced
        logger.info(
            "smart_phase_similarity",
            extra={
                "min_pairwise": round(min_sim, 4),
                "mean_pairwise": round(mean_sim, 4),
                "threshold": SKIP_THRESHOLD,
                "explicit_disagreement": forced,
                "decision": "skip" if skip else "debate",
            },
        )
        return skip, min_sim
    except Exception as e:
        logger.exception("smart_phase_failed", extra={"error": str(e)})
        return False, 0.0


async def check_unanimous_consensus(analyses: dict) -> bool:
    skip, _ = await should_skip(analyses)
    return skip
