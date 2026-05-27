import os
import numpy as np
import asyncio

from embeddings import get_embedder
from logging_utils import get_logger


logger = get_logger(__name__)

SKIP_THRESHOLD = float(os.getenv("COUNCIL_SMART_PHASE_THRESHOLD", "0.88"))
DISAGREEMENT_MARKERS = [
    "however",
    "disagree",
    "dispute",
    "contradict",
    "risk",
    "concern",
    "wrong",
    "incorrect",
    "but",
    "unfortunately",
]


def _has_explicit_disagreement(analyses: dict) -> bool:
    all_text = " ".join(analyses.values()).lower()
    return sum(1 for m in DISAGREEMENT_MARKERS if m in all_text) >= 3


async def should_skip(analyses: dict) -> tuple[bool, float]:
    if len(analyses) < 2:
        return False, 0.0
        
    def compute_similarity():
        texts = list(analyses.values())
        model = get_embedder()
        embeddings = model.encode(texts)
        
        # Compute pairwise cosine similarity
        norm = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized_embs = embeddings / norm
        sim_matrix = np.dot(normalized_embs, normalized_embs.T)
        
        # Average upper triangle
        n = sim_matrix.shape[0]
        upper_tri = sim_matrix[np.triu_indices(n, k=1)]
        avg_sim = np.mean(upper_tri)
        return float(avg_sim)
        
    try:
        avg_sim = await asyncio.to_thread(compute_similarity)
        logger.info("smart_phase_similarity", extra={"score": round(avg_sim, 4), "threshold": SKIP_THRESHOLD})
        if _has_explicit_disagreement(analyses):
            logger.info("smart_phase_forced", extra={"reason": "disagreement_markers", "score": round(avg_sim, 4)})
            return False, avg_sim
        return avg_sim > SKIP_THRESHOLD, avg_sim
    except Exception as e:
        logger.exception("smart_phase_failed", extra={"error": str(e)})
        return False, 0.0


async def check_unanimous_consensus(analyses: dict) -> bool:
    skip, _ = await should_skip(analyses)
    return skip
