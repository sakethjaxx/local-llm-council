import asyncio
import os

import runtime_defaults  # noqa: F401  # configure LiteLLM before import
import litellm
from cloud_keys import litellm_kwargs_for_model
from logging_utils import get_logger

logger = get_logger(__name__)

CHUNK_SIZE_LIMIT = 12000
CHUNK_OVERLAP = 500


def _chunk_text(text: str, limit: int = CHUNK_SIZE_LIMIT, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + limit, n)
        if end < n:
            nl = text.rfind("\n", start + limit - overlap, end)
            if nl > start:
                end = nl
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


async def chunk_and_summarize(text: str, base_model: str) -> str:
    if len(text) < 15000:
        return text

    logger.info("summarizer_chunking_started", extra={"input_chars": len(text)})
    chunks = _chunk_text(text)
    timeout = float(os.getenv("COUNCIL_LLM_TIMEOUT", "180"))

    async def _complete(prompt: str, max_tokens: int) -> str:
        resp = await litellm.acompletion(
            model=base_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            timeout=timeout,
            **litellm_kwargs_for_model(base_model),
        )
        return resp.choices[0].message.content

    sem = asyncio.Semaphore(4)

    async def summarize_chunk(idx: int, chunk: str) -> str:
        async with sem:
            prompt = f"Summarize this segment of a larger document. Retain all technical facts, logic, and structure.\n\n{chunk}"
            try:
                return f"--- Segment {idx+1} Summary ---\n{await _complete(prompt, 600)}\n"
            except Exception as exc:
                logger.exception("summarizer_chunk_failed", extra={"chunk_index": idx, "error": str(exc)})
                return f"--- Segment {idx+1} (Truncated due to error) ---\n{chunk[:1000]}...\n"

    summaries = await asyncio.gather(*[summarize_chunk(i, c) for i, c in enumerate(chunks)])
    mapped = "\n".join(summaries)

    if len(chunks) <= 3:
        return mapped
    try:
        reduce_prompt = (
            "These are ordered summaries of consecutive segments of one document. "
            "Merge them into a single, de-duplicated, coherent summary that preserves "
            "all technical facts and the overall structure.\n\n" + mapped
        )
        return await _complete(reduce_prompt, 1200)
    except Exception as exc:
        logger.exception("summarizer_reduce_failed", extra={"error": str(exc)})
        return mapped
