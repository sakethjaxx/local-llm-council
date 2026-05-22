import numpy as np
import asyncio

from embeddings import get_embedder


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
        print(f"\n[🧠 Smart Phase] Average Peer Agreement (Cosine Similarity): {avg_sim:.3f}")
        return avg_sim > 0.88, avg_sim
    except Exception as e:
        print(f"[❌ Smart Phase Failed]: {e}")
        return False, 0.0


async def check_unanimous_consensus(analyses: dict) -> bool:
    skip, _ = await should_skip(analyses)
    return skip
