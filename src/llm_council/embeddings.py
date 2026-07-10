from llm_council.logging_utils import get_logger


logger = get_logger(__name__)
_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        logger.info("embedder_loading", extra={"model": "all-MiniLM-L6-v2"})
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder
