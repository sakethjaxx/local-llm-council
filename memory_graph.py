import networkx as nx
import json
import os
import litellm

MEMORY_FILE = "council_memory.json"

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
Format your output STRICTLY as a JSON array of arrays, where each inner array is a triple: ["Subject", "Predicate", "Object"].
Keep subjects and objects concise (1-4 words).
Examples of predicates: "decided_to_use", "rejected", "identified_risk", "recommended".

Topic: {topic[:500]}...
Verdict: {verdict[:1500]}...

Return ONLY the raw JSON array. No markdown code blocks, no explanations."""
        try:
            print(f"\n[🧠 Memory] Extracting triples using {extraction_model}...")
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )
            raw_output = resp.choices[0].message.content.strip()
            if raw_output.startswith("```json"):
                raw_output = raw_output[7:-3]
            elif raw_output.startswith("```"):
                raw_output = raw_output[3:-3]
                
            triples = json.loads(raw_output.strip())
            added = 0
            for t in triples:
                if len(t) == 3:
                    u, rel, v = t
                    self.graph.add_edge(u, v, label=rel)
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
Return ONLY a JSON array of strings, e.g. ["PostgreSQL", "Authentication"]."""

        try:
            resp = await litellm.acompletion(
                model=extraction_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```json"):
                raw = raw[7:-3]
            elif raw.startswith("```"):
                raw = raw[3:-3]
                
            keywords = json.loads(raw.strip())
            
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
