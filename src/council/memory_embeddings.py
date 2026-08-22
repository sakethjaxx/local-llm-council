import sys
import numpy as np
from typing import Optional
from embeddings import get_embedder as default_get_embedder, cosine_similarity as _cosine_similarity


def _get_embedder():
    mod = sys.modules.get("memory_store")
    return getattr(mod, "get_embedder", default_get_embedder)()


def _to_vector(value) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.ndim > 1:
        vector = vector[0]
    return vector


def embed_memory_text(text: str) -> np.ndarray:
    return _to_vector(_get_embedder().encode(text))


def serialize_embedding(vector: np.ndarray) -> bytes:
    return vector.astype(np.float32).tobytes()


def deserialize_embedding(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)
