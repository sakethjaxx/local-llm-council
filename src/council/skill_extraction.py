import asyncio
import json
import re
import time
from typing import Optional

from cloud_keys import litellm_kwargs_for_model
from embeddings import cosine_similarity as _cosine_similarity
from logging_utils import get_logger

logger = get_logger(__name__)


def _extract_json_block(raw: str) -> str:
    raw = (raw or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return raw[first_brace:last_brace + 1]
    return raw


def _extract_risk_score(raw_output: str) -> Optional[float]:
    for candidate in (raw_output, _extract_json_block(raw_output)):
        try:
            parsed = json.loads(candidate)
            value = parsed.get("risk_score")
            if value is not None:
                return float(value)
        except Exception:
            pass

    match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw_output or "")
    if match:
        return float(match.group(1))
    return None


def should_extract_skill(conn, run_id: str) -> bool:
    feedback_rows = conn.execute(
        "SELECT rating FROM run_feedback WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    has_thumbs_up = any(str(row["rating"]).lower() in {"up", "thumbs_up"} for row in feedback_rows)

    chairman_row = conn.execute(
        """
        SELECT output
        FROM phase_outputs
        WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
        """,
        (run_id,),
    ).fetchone()

    risk_score = None
    if chairman_row is not None:
        risk_score = _extract_risk_score(chairman_row["output"] or "")

    return not (not has_thumbs_up and risk_score is not None and risk_score > 3)


async def request_skill_text(active_litellm, model: str, prompt: str, temperature: float) -> str:
    resp = await active_litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=temperature,
        **litellm_kwargs_for_model(model),
    )
    return resp.choices[0].message.content or ""


def _save_or_reinforce_skill(conn, name: str, body: str, domain: Optional[str], run_id: str, vector, serialized, deserialize_fn, dedup_fn) -> None:
    rows = conn.execute(
        """
        SELECT id, confidence, embedding
        FROM skills
        WHERE embedding IS NOT NULL
        """
    ).fetchall()

    duplicate_id = None
    duplicate_confidence = None
    for row in rows:
        stored = deserialize_fn(row["embedding"])
        if stored is not None and _cosine_similarity(vector, stored) > 0.90:
            duplicate_id = row["id"]
            duplicate_confidence = row["confidence"]
            break

    if duplicate_id is not None:
        conn.execute(
            """
            UPDATE skills
            SET confidence = MIN(1.0, ? + 0.05)
            WHERE id = ?
            """,
            (float(duplicate_confidence), duplicate_id),
        )
        logger.info("skill_duplicate_reinforced", extra={"skill_id": duplicate_id, "run_id": run_id})
        return

    now = time.time()
    conn.execute(
        """
        INSERT INTO skills (
            name, body, domain, source_run, confidence,
            used_count, created_at, embedding
        )
        VALUES (?, ?, ?, ?, 0.5, 0, ?, ?)
        """,
        (name, body, domain, run_id, now, serialized),
    )
    dedup_fn(conn=conn)


async def extract_and_persist_skill(
    conn,
    run_id: str,
    topic: str,
    chairman_model: str,
    active_litellm,
    embed_fn,
    serialize_fn,
    deserialize_fn,
    dedup_fn,
) -> None:
    if not should_extract_skill(conn, run_id):
        logger.info("skill_extraction_skipped", extra={"run_id": run_id, "reason": "quality_gate"})
        return

    chairman_row = conn.execute(
        """
        SELECT output
        FROM phase_outputs
        WHERE run_id = ? AND phase = 3 AND member_id = 'chairman'
        """,
        (run_id,),
    ).fetchone()

    if chairman_row is None:
        return

    verdict = chairman_row["output"] or ""
    temperature = 0.4
    try:
        extract_prompt = (
            "You are a skill extractor for an AI council system.\n"
            "Given the topic and chairman verdict below, extract ONE reusable analysis skill that future councils could apply.\n"
            "A skill is a concrete analytical approach, heuristic, or reasoning pattern — not a conclusion.\n"
            'Respond with JSON: {"name": "short skill name (max 6 words)", "body": "one paragraph describing the skill and when to apply it", "domain": "optional domain tag (e.g. backend, security, architecture, or null)"}\n\n'
            f"Topic: {topic[:400]}\n"
            f"Chairman Verdict: {verdict[:1200]}"
        )
        extracted_raw = await request_skill_text(active_litellm, chairman_model, extract_prompt, temperature)
        skill = json.loads(_extract_json_block(extracted_raw))
        name = str(skill.get("name", "")).strip()
        body = str(skill.get("body", "")).strip()
        domain = skill.get("domain")
        if not name or not body:
            return
        if domain is not None:
            domain = str(domain).strip() or None

        sanity_prompt = (
            "Does the following analysis skill logically follow from this council verdict?\n"
            f"Skill: {body}\n"
            f"Verdict: {verdict[:800]}\n"
            'Answer with only "yes" or "no".'
        )
        sanity = await request_skill_text(active_litellm, chairman_model, sanity_prompt, temperature)
        if not sanity.strip().lower().startswith("yes"):
            return

        vector = await asyncio.to_thread(embed_fn, f"{name} {body}")
        serialized = serialize_fn(vector)
        _save_or_reinforce_skill(conn, name, body, domain, run_id, vector, serialized, deserialize_fn, dedup_fn)
    except Exception as exc:
        logger.exception("skill_extraction_failed", extra={"run_id": run_id, "error": str(exc)})
