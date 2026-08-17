"""Knowledge Graph Exporter for Local LLM Council.

Converts council memory triples into a portable knowledge-graph corpus JSON
document (notes + typed links) that other graph tools can ingest.
"""

from typing import Any, Dict, List


def export_to_graph_json(
    triples: List[Dict[str, Any]],
    corpus_name: str = "local-llm-council",
    extracted_by: str = "local-llm-council:memory-engine"
) -> Dict[str, Any]:
    """Converts council memory triples into a portable knowledge-graph corpus."""
    notes_map: Dict[str, Dict[str, Any]] = {}
    links: List[Dict[str, Any]] = []

    for t in triples:
        subj = str(t.get("subject", "")).strip()
        obj = str(t.get("object", "")).strip()
        pred = str(t.get("predicate", "related_to")).strip().lower()
        conf = float(t.get("confidence", 0.9))

        if not subj or not obj:
            continue

        subj_key = subj.lower().replace(" ", "_")
        obj_key = obj.lower().replace(" ", "_")

        # Normalize predicate to the supported edge vocabulary
        valid_types = {
            "supports", "contradicts", "causes", "depends_on", "related_to",
            "example_of", "part_of", "derived_from", "decision_about", "mentions"
        }
        edge_type = pred if pred in valid_types else "related_to"

        if subj_key not in notes_map:
            notes_map[subj_key] = {
                "key": subj_key,
                "title": subj,
                "content": f"Entity derived from local LLM council memory: {subj}",
                "extraction": {
                    "title": subj,
                    "summary": f"Council memory node for {subj}",
                    "tags": ["council-memory", "memory-triples"],
                    "entities": [{"label": subj, "type": "concept", "description": f"Council topic {subj}"}],
                    "tasks": [],
                    "decisions": [f"Decided: {subj} is linked via {edge_type}"],
                    "questions": []
                }
            }

        if obj_key not in notes_map:
            notes_map[obj_key] = {
                "key": obj_key,
                "title": obj,
                "content": f"Entity derived from local LLM council memory: {obj}",
                "extraction": {
                    "title": obj,
                    "summary": f"Council memory node for {obj}",
                    "tags": ["council-memory", "memory-triples"],
                    "entities": [{"label": obj, "type": "concept", "description": f"Council topic {obj}"}],
                    "tasks": [],
                    "decisions": [],
                    "questions": []
                }
            }

        links.append({
            "from": subj_key,
            "to": obj_key,
            "type": edge_type,
            "confidence": min(1.0, max(0.5, conf)),
            "explanation": f"Council memory triple: {subj} --[{edge_type}]--> {obj}"
        })

    return {
        "extracted_by": extracted_by,
        "project": corpus_name,
        "source": "local-llm-council-export",
        "notes": list(notes_map.values()),
        "links": links
    }
