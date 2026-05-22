_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        print("\n[embeddings] Loading SentenceTransformer all-MiniLM-L6-v2...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder
