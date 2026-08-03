# DEPRECATED: Retained for backward compatibility; active code uses memory_store.SQLiteMemory.
import json
import os
import re
import litellm
from pydantic import BaseModel
from typing import List

from logging_utils import get_logger

logger = get_logger(__name__)


class Triple(BaseModel):
    subject: str
    predicate: str
    object: str


class MemoryExtraction(BaseModel):
    triples: List[Triple]


class MemoryKeywords(BaseModel):
    keywords: List[str]


MEMORY_FILE = "council_memory.json"


def _extract_json_block(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
    return raw


class GraphMemory:
    """Lightweight native graph store replacing legacy NetworkX dependency."""

    def __init__(self):
        self.nodes = set()
        self.edges = []  # list of (u, v, label)
        self._load()

    def _load(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for edge in data.get("links", []):
                        u, v = str(edge.get("source", "")), str(edge.get("target", ""))
                        if u and v:
                            self.edges.append((u, v, str(edge.get("label", "related to"))))
                            self.nodes.update((u, v))
            except Exception as e:
                logger.exception("legacy_memory_load_failed", extra={"error": str(e)})

    def _save(self):
        try:
            links = [{"source": u, "target": v, "label": lbl} for u, v, lbl in self.edges]
            nodes = [{"id": n} for n in sorted(self.nodes)]
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"nodes": nodes, "links": links}, f, indent=2)
        except Exception as e:
            logger.exception("legacy_memory_save_failed", extra={"error": str(e)})

    async def extract_memory(self, topic: str, verdict: str, extraction_model: str):
        prompt = (
            "You are an information extraction engine for an AI council.\n"
            "Given the topic discussed and the final verdict delivered by the Chairman, extract the core knowledge as a list of facts.\n"
            "Use the provided JSON schema to output an array of triples under the 'triples' key.\n"
            "Each triple has a subject, predicate, and object. Keep subjects and objects concise (1-4 words).\n"
            'Examples of predicates: "decided_to_use", "rejected", "identified_risk", "recommended".\n\n'
            f"Topic: {topic[:500]}...\nVerdict: {verdict[:1500]}..."
        )
        try:
            logger.info("legacy_memory_extraction_started", extra={"model": extraction_model})
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format=MemoryExtraction,
            )
            raw_output = resp.choices[0].message.content
            data = MemoryExtraction.model_validate_json(_extract_json_block(raw_output))
            added = 0
            for t in data.triples:
                self.edges.append((t.subject, t.object, t.predicate))
                self.nodes.update((t.subject, t.object))
                added += 1
            logger.info("legacy_memory_extraction_completed", extra={"added": added})
            self._save()
        except Exception as e:
            logger.exception("legacy_memory_extraction_failed", extra={"error": str(e)})

    async def get_context(self, topic: str, extraction_model: str) -> str:
        if not self.nodes:
            return ""

        prompt = (
            "Given the following new topic, identify up to 3 core concepts (1-2 words each) to search our memory graph for.\n"
            f"Topic: {topic[:500]}...\n"
            "Use the provided JSON schema to return an array of strings under the 'keywords' key."
        )
        try:
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                response_format=MemoryKeywords,
            )
            raw = resp.choices[0].message.content
            data = MemoryKeywords.model_validate_json(_extract_json_block(raw))
            keywords = [k.lower() for k in data.keywords]

            relevant_edges = []
            for u, v, lbl in self.edges:
                u_lower, v_lower = u.lower(), v.lower()
                if any(k in u_lower or k in v_lower for k in keywords):
                    relevant_edges.append(f"{u} -> {lbl} -> {v}")

            if relevant_edges:
                unique_edges = list(dict.fromkeys(relevant_edges))[:15]
                context = "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n"
                context += "\n".join(unique_edges)
                logger.info("legacy_memory_context_found", extra={"edge_count": len(unique_edges), "keywords": keywords})
                return context + "\n\n"
            return ""
        except Exception as e:
            logger.exception("legacy_memory_context_failed", extra={"error": str(e)})
            return ""

    def get_graph_data(self):
        nodes = [{"id": n, "label": n} for n in sorted(self.nodes)]
        edges = [{"from": u, "to": v, "label": lbl} for u, v, lbl in self.edges]
        return {"nodes": nodes, "edges": edges}


memory_engine = GraphMemory()
