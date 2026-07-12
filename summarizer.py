import litellm
import asyncio
import os
from cloud_keys import litellm_kwargs_for_model
from logging_utils import get_logger


logger = get_logger(__name__)

async def chunk_and_summarize(text: str, base_model: str) -> str:
    if len(text) < 15000:
        return text
        
    logger.info("summarizer_chunking_started", extra={"input_chars": len(text)})
    chunk_size_limit = 12000
    chunks = []
    current_chunk = []
    current_length = 0
    
    for line in text.split('\n'):
        line_len = len(line) + 1
        if current_length + line_len > chunk_size_limit and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_length = line_len
        else:
            current_chunk.append(line)
            current_length += line_len
            
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    async def summarize_chunk(idx: int, chunk: str):
        prompt = f"Summarize the following massive chunk of text/code. Retain all technical facts, logic, and structure. Do not omit crucial details.\n\n{chunk}"
        try:
            resp = await litellm.acompletion(
                model=base_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                timeout=float(os.getenv("COUNCIL_LLM_TIMEOUT", "180")),
                **litellm_kwargs_for_model(base_model),
            )
            return f"--- Segment {idx+1} Summary ---\n{resp.choices[0].message.content}\n"
        except Exception as exc:
            logger.exception("summarizer_chunk_failed", extra={"chunk_index": idx, "error": str(exc)})
            return f"--- Segment {idx+1} (Truncated due to error) ---\n{chunk[:1000]}...\n"

    sem = asyncio.Semaphore(4)

    async def bounded_summarize(idx, chunk):
        async with sem:
            return await summarize_chunk(idx, chunk)

    summaries = await asyncio.gather(*[bounded_summarize(i, c) for i, c in enumerate(chunks)])
    return "\n".join(summaries)
