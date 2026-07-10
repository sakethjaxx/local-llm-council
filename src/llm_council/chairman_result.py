import json
import re
from typing import List

from pydantic import BaseModel


class ChairmanDecision(BaseModel):
    verdict: str
    risk_score: int
    action_items: List[str]
    consensus: List[str] = []
    disputes: List[str] = []


def parse_chairman_response(raw: str) -> dict:
    def normalize(result: dict, tier: str) -> dict:
        consensus = result.get("consensus")
        if isinstance(consensus, str):
            consensus = [consensus] if consensus else []
        elif not isinstance(consensus, list):
            consensus = []
        return {
            "verdict": result.get("verdict", "parse_failed"),
            "risk_score": result.get("risk_score", -1),
            "action_items": result.get("action_items", []),
            "consensus": consensus,
            "disputes": result.get("disputes", []),
            "_parse_tier": result.get("_parse_tier", tier),
        }

    try:
        return normalize(json.loads(raw), "json")
    except Exception:
        pass

    try:
        stripped = re.sub(r"^```(?:json)?\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        return normalize(json.loads(stripped), "fenced_json")
    except Exception:
        pass

    verdict_match = re.search(r'"verdict"\s*:\s*"([^"]+)"', raw)
    risk_match = re.search(r'"risk_score"\s*:\s*(\d+(?:\.\d+)?)', raw)
    if verdict_match or risk_match:
        return {
            "verdict": verdict_match.group(1) if verdict_match else "parse_failed",
            "risk_score": float(risk_match.group(1)) if risk_match else -1,
            "action_items": [],
            "consensus": [],
            "disputes": [],
            "_parse_tier": "regex_extracted",
        }

    return {
        "verdict": "parse_failed",
        "risk_score": -1,
        "action_items": [],
        "consensus": [],
        "disputes": [],
        "_parse_tier": "parse_failed",
    }


def specificity_score(chairman_result: dict, raw_text: str) -> float:
    action_items = chairman_result.get("action_items") or []
    if not action_items:
        return 0.0

    scored_items = 0.0
    for item in action_items:
        text = str(item)
        signals = 0
        if len(text.split()) >= 6:
            signals += 1
        if re.search(r"\b[\w./-]+\.(py|js|ts|html|css|md|json|yml|yaml)(?::\d+)?\b", text):
            signals += 1
        if re.search(
            r"\b(add|remove|replace|validate|test|document|limit|sanitize|retry|measure)\b",
            text,
            re.IGNORECASE,
        ):
            signals += 1
        if re.search(r"\d", text):
            signals += 1
        scored_items += min(signals, 3) / 3

    structure_bonus = 0.1 if any(label in raw_text.lower() for label in ("risk", "action", "because", "owner")) else 0.0
    return round(min(1.0, (scored_items / len(action_items)) + structure_bonus), 3)


# Backward-compatible private name while tests and callers migrate.
_specificity_score = specificity_score
