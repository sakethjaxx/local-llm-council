import threading

import numpy as np

from logging_utils import get_logger


logger = get_logger(__name__)
_embedder = None
_embedder_lock = threading.Lock()


def get_embedder():
    global _embedder
    if _embedder is None:
        # Double-checked locking: multiple threads (smart_phase via to_thread,
        # startup rebuild_embeddings, skill dedup) can race the first call and
        # would otherwise each load the heavy SentenceTransformer model.
        with _embedder_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer
                logger.info("embedder_loading", extra={"model": "all-MiniLM-L6-v2"})
                _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))
