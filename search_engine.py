from duckduckgo_search import DDGS
import asyncio
import litellm

async def get_search_context(reviews: dict, extraction_model: str) -> str:
    # 1. Ask LLM if there is a factual dispute
    prompt = "You are a dispute detector. Read these peer reviews. If there is a factual dispute or knowledge gap that can be solved by a quick Google search (e.g. 'Is X stable?', 'What is the limit of Y?'), output ONLY a 3-4 word search query. If there is no dispute or it's purely subjective, output EXACTLY the word 'NONE'."
    for reviewer, text in reviews.items():
        prompt += f"\n--- {reviewer} ---\n{text}"
        
    try:
        print("\n[🕵️ Chairman] Checking for factual disputes...")
        resp = await litellm.acompletion(
            model=extraction_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20
        )
        query = resp.choices[0].message.content.strip().replace('"', '')
        if query.upper() == "NONE" or len(query) > 50:
            return ""
            
        print(f"[🌐 Web Search] Disputed fact detected. Querying DuckDuckGo: '{query}'")
        
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
        print(f"[❌ Web Search Failed]: {e}")
        return ""
