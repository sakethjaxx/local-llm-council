import networkx as nx
import json
import os
import re
import litellm
from pydantic import BaseModel
from typing import List

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
    def __init__(self):
        self.graph = nx.DiGraph()
        self._load()

    def _load(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.graph = nx.node_link_graph(data)
            except Exception as e:
                print(f"[Memory] Failed to load graph: {e}")

    def _save(self):
        try:
            data = nx.node_link_data(self.graph)
            with open(MEMORY_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Memory] Failed to save graph: {e}")

    async def extract_memory(self, topic: str, verdict: str, extraction_model: str):
        prompt = f"""You are an information extraction engine for an AI council.
Given the topic discussed and the final verdict delivered by the Chairman, extract the core knowledge as a list of facts.
Use the provided JSON schema to output an array of triples under the 'triples' key.
Each triple has a subject, predicate, and object. Keep subjects and objects concise (1-4 words).
Examples of predicates: "decided_to_use", "rejected", "identified_risk", "recommended".

Topic: {topic[:500]}...
Verdict: {verdict[:1500]}..."""
        try:
            print(f"\n[🧠 Memory] Extracting triples using {extraction_model}...")
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format=MemoryExtraction
            )
            raw_output = resp.choices[0].message.content

            data = MemoryExtraction.model_validate_json(_extract_json_block(raw_output))
            added = 0
            for t in data.triples:
                self.graph.add_edge(t.subject, t.object, label=t.predicate)
                added += 1
                    
            print(f"[✅ Memory] Successfully added {added} facts to Long-Term Knowledge Graph.")
            self._save()
        except Exception as e:
            print(f"[❌ Memory] Extraction failed: {str(e)}")

    async def get_context(self, topic: str, extraction_model: str) -> str:
        if len(self.graph.nodes) == 0:
            return ""
            
        prompt = f"""Given the following new topic, identify up to 3 core concepts (1-2 words each) to search our memory graph for.
Topic: {topic[:500]}...
Use the provided JSON schema to return an array of strings under the 'keywords' key."""

        try:
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                response_format=MemoryKeywords
            )
            raw = resp.choices[0].message.content

            data = MemoryKeywords.model_validate_json(_extract_json_block(raw))
            keywords = data.keywords
            
            # Simple keyword matching in graph
            relevant_edges = []
            for u, v, data in self.graph.edges(data=True):
                for k in keywords:
                    if k.lower() in str(u).lower() or k.lower() in str(v).lower():
                        relevant_edges.append(f"{u} -> {data.get('label', 'related to')} -> {v}")
                        
            if relevant_edges:
                context = "COUNCIL HISTORICAL MEMORY (Past decisions you must consider):\n"
                context += "\n".join(list(set(relevant_edges))[:15]) # max 15 facts
                print(f"\n[🧠 Memory] Found {len(set(relevant_edges))} historical facts related to: {keywords}")
                return context + "\n\n"
            return ""
        except Exception as e:
            print(f"[⚠️ Memory] Context retrieval failed: {str(e)}")
            return ""

    def get_graph_data(self):
        nodes = [{"id": n, "label": str(n)} for n in self.graph.nodes()]
        edges = [{"from": u, "to": v, "label": str(d.get("label", ""))} for u, v, d in self.graph.edges(data=True)]
        return {"nodes": nodes, "edges": edges}

# Global singleton
memory_engine = GraphMemory()
