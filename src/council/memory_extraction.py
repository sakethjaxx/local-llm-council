import json
import os
import re
import time
from typing import List, Optional
import litellm
from pydantic import BaseModel

from cloud_keys import litellm_kwargs_for_model
from embeddings import cosine_similarity as _cosine_similarity
from logging_utils import get_logger
from provider_caps import caps_for

logger = get_logger(__name__)


class Triple(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0


class MemoryExtraction(BaseModel):
    triples: List[Triple]


def _extract_json_block(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return raw[first_brace:last_brace + 1]
    return raw


def _extract_risk_score(raw_output: str) -> Optional[float]:
    try:
        parsed = json.loads(raw_output)
        value = parsed.get("risk_score")
        if value is not None:
            return float(value)
    except Exception:
        pass

    try:
        parsed = json.loads(_extract_json_block(raw_output))
        value = parsed.get("risk_score")
        if value is not None:
            return float(value)
    except Exception:
        pass

    match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw_output)
    if match:
        return float(match.group(1))
    return None


def should_extract_memory(conn, run_id: Optional[str]) -> bool:
    if not run_id:
        return True

    feedback_rows = conn.execute(
        "SELECT rating FROM run_feedback WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    has_thumbs_up = any(str(row["rating"]).lower() in {"up", "thumbs_up"} for row in feedback_rows)
    if has_thumbs_up:
        return True

    chairman_row = conn.execute(
        """
        SELECT output
        FROM phase_outputs
        WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
        """,
        (run_id,),
    ).fetchone()

    if chairman_row is None:
        return True

    risk_score = _extract_risk_score(chairman_row["output"] or "")
    return risk_score is None or risk_score <= 3


def persist_extracted_triples(conn, triples: list, embed_fn, serialize_fn, deserialize_fn) -> tuple[int, int]:
    now = time.time()
    added = 0
    updated = 0

    existing_rows = conn.execute(
        """
        SELECT id, confidence, reinforced, embedding
        FROM memory_triples
        WHERE embedding IS NOT NULL
        """
    ).fetchall()

    existing_vectors = []
    for row in existing_rows:
        vector = deserialize_fn(row["embedding"])
        if vector is not None:
            existing_vectors.append((row, vector))

    for triple in triples:
        triple_text = f"{triple.subject} {triple.predicate} {triple.object}"
        vector = embed_fn(triple_text)

        best_match = None
        best_score = -1.0
        for row, stored_vector in existing_vectors:
            score = _cosine_similarity(vector, stored_vector)
            if score > 0.92 and score > best_score:
                best_match = row
                best_score = score

        if best_match is not None:
            conn.execute(
                """
                UPDATE memory_triples
                SET reinforced = reinforced + 1,
                    last_seen = ?,
                    confidence = MIN(1.0, confidence + 0.1)
                WHERE id = ?
                """,
                (now, best_match["id"]),
            )
            updated += 1
            continue

        conn.execute(
            """
            INSERT INTO memory_triples (
                subject, predicate, object, confidence, reinforced,
                contradicted, last_seen, created_at, embedding
            )
            VALUES (?, ?, ?, 1.0, 1, 0, ?, ?, ?)
            """,
            (triple.subject, triple.predicate, triple.object, now, now, serialize_fn(vector)),
        )
        existing_vectors.append(({"id": conn.execute("SELECT last_insert_rowid()").fetchone()[0]}, vector))
        added += 1

    return added, updated


async def execute_memory_extraction(
    conn,
    topic: str,
    verdict: str,
    extraction_model: str,
    run_id: Optional[str],
    active_litellm,
    embed_fn,
    serialize_fn,
    deserialize_fn,
) -> None:
    if not should_extract_memory(conn, run_id):
        logger.info("memory_extraction_skipped", extra={"run_id": run_id, "reason": "quality_gate"})
        return

    prompt = f"""You are an information extraction engine for an AI council.
Given the topic discussed and the final verdict delivered by the Chairman, extract the core knowledge as a list of facts.
Use the provided JSON schema to output an array of triples under the 'triples' key.
Each triple has a subject, predicate, and object. Keep subjects and objects concise (1-4 words).
Examples of predicates: "decided_to_use", "rejected", "identified_risk", "recommended".

Topic: {topic[:500]}...
Verdict: {verdict[:1500]}..."""
    model = os.getenv("COUNCIL_MEMORY_MODEL", extraction_model)
    use_response_format = caps_for(model)[1].response_format

    if not use_response_format:
        prompt += (
            "\n\nRespond ONLY with valid JSON matching this exact schema:\n"
            '{"triples": [{"subject": "...", "predicate": "...", "object": "..."}]}'
        )

    try:
        logger.info("memory_extraction_started", extra={"model": model, "run_id": run_id})
        completion_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "timeout": float(os.getenv("COUNCIL_LLM_TIMEOUT", "180")),
            **litellm_kwargs_for_model(model),
        }
        if use_response_format:
            completion_kwargs["response_format"] = MemoryExtraction

        resp = await active_litellm.acompletion(**completion_kwargs)
        raw_output = resp.choices[0].message.content
        data = MemoryExtraction.model_validate_json(_extract_json_block(raw_output))

        added, updated = persist_extracted_triples(
            conn, data.triples, embed_fn, serialize_fn, deserialize_fn
        )
        logger.info("memory_extraction_completed", extra={"run_id": run_id, "added": added, "reinforced": updated})
    except Exception as exc:
        logger.exception("memory_extraction_failed", extra={"run_id": run_id, "error": str(exc)})
