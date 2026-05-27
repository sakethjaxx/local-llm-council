# ML Pipeline Architecture Review

Review this training + serving pipeline design for a recommendation system going to production.

## System Overview

Recommend products to 3M daily active users on an e-commerce platform.

## Training Pipeline (current)

```
Raw clickstream (Kafka) 
  → Spark job (daily, 4AM UTC) 
  → Feature store (Redis, 30-day window)
  → Model training (PyTorch, single GPU, ~6 hours)
  → Model registry (MLflow)
  → Serving layer
```

## Serving Layer

```python
# Called on every product page load
def get_recommendations(user_id, product_id, n=10):
    user_vector = redis.get(f"user:{user_id}:embedding")  # 512-dim
    if not user_vector:
        return cold_start_fallback(product_id, n)
    
    # brute-force cosine search over 500K product embeddings
    scores = cosine_similarity([user_vector], all_product_embeddings)
    top_n = np.argsort(scores[0])[-n:][::-1]
    return [product_catalog[i] for i in top_n]

all_product_embeddings = load_all_embeddings()  # 500K × 512 float32 = ~1GB loaded at startup
```

## Observed Problems

- P99 latency: 840ms (target: <100ms)
- Daily retraining misses new products added same day
- 18% of users get cold start (no embedding)
- Redis OOM events 2x last month

## Questions

1. What causes the latency spike?
2. Fix cold start rate?
3. Should we move to approximate nearest neighbor search?
4. Retrain more frequently or use online learning?
