import litellm
import asyncio
from cloud_keys import litellm_kwargs_for_model

async def chunk_and_summarize(text: str, base_model: str) -> str:
    if len(text) < 15000:
        return text
        
    print(f"\n[📦 Map-Reduce] Text is huge ({len(text)} chars). Chunking & Summarizing...")
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
                **litellm_kwargs_for_model(base_model),
            )
            return f"--- Segment {idx+1} Summary ---\n{resp.choices[0].message.content}\n"
        except Exception:
            return f"--- Segment {idx+1} (Truncated due to error) ---\n{chunk[:1000]}...\n"

    summaries = await asyncio.gather(*[summarize_chunk(i, c) for i, c in enumerate(chunks)])
    return "\n".join(summaries)
