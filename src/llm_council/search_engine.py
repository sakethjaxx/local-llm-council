from duckduckgo_search import DDGS
import asyncio
import litellm
from llm_council.cloud_keys import litellm_kwargs_for_model
from llm_council.logging_utils import get_logger


logger = get_logger(__name__)

async def get_search_context(reviews: dict, extraction_model: str) -> str:
    # 1. Ask LLM if there is a factual dispute
    prompt = "You are a dispute detector. Read these peer reviews. If there is a factual dispute or knowledge gap that can be solved by a quick Google search (e.g. 'Is X stable?', 'What is the limit of Y?'), output ONLY a 3-4 word search query. If there is no dispute or it's purely subjective, output EXACTLY the word 'NONE'."
    for reviewer, text in reviews.items():
        prompt += f"\n--- {reviewer} ---\n{text}"
        
    try:
        logger.info("search_dispute_check_started", extra={"model": extraction_model})
        resp = await litellm.acompletion(
            model=extraction_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            **litellm_kwargs_for_model(extraction_model),
        )
        query = resp.choices[0].message.content.strip().replace('"', '')
        if query.upper() == "NONE" or len(query) > 50:
            return ""
            
        logger.info("search_query_started", extra={"query": query})
        
        # 2. Run DDG Search
        def do_search():
            ddgs = DDGS()
            return list(ddgs.text(query, max_results=3))
            
        results = await asyncio.to_thread(do_search)
        if not results:
            return ""
            
        formatted = f"\n--- CHAIRMAN LIVE SEARCH TOOL ('{query}') ---\n"
        for r in results:
            formatted += f"- {r.get('title')}: {r.get('body')}\n"
        return formatted
    except Exception as e:
        logger.exception("search_failed", extra={"error": str(e)})
        return ""
