import unittest
from fable_exporter import export_to_fable_json


class FableExporterTests(unittest.TestCase):
    def test_export_to_fable_json(self):
        triples = [
            {"subject": "FastAPI", "predicate": "supports", "object": "AsyncIO", "confidence": 0.95},
            {"subject": "NetworkX", "predicate": "contradicts", "object": "Ponytail Rules", "confidence": 0.88},
        ]
        result = export_to_fable_json(triples, corpus_name="test-corpus")

        self.assertEqual(result["project"], "test-corpus")
        self.assertEqual(result["extracted_by"], "local-llm-council:fable-engine")
        self.assertEqual(len(result["notes"]), 4)  # FastAPI, AsyncIO, NetworkX, Ponytail Rules
        self.assertEqual(len(result["links"]), 2)

        link1 = result["links"][0]
        self.assertEqual(link1["from"], "fastapi")
        self.assertEqual(link1["to"], "asyncio")
        self.assertEqual(link1["type"], "supports")
        self.assertEqual(link1["confidence"], 0.95)

        link2 = result["links"][1]
        self.assertEqual(link2["from"], "networkx")
        self.assertEqual(link2["to"], "ponytail_rules")
        self.assertEqual(link2["type"], "contradicts")
        self.assertEqual(link2["confidence"], 0.88)


if __name__ == "__main__":
    unittest.main()
