import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from demo_catalog import get_demo_catalog, load_presets
from io_parser import format_attachments_for_prompt, parse_uploaded_file
from orchestrator import CouncilOrchestrator


class DemoScenariosTests(unittest.TestCase):
    def test_load_presets_and_catalog(self):
        catalog = get_demo_catalog()
        self.assertIn("presets", catalog)
        presets = catalog["presets"]
        self.assertGreater(len(presets), 0)

        preset_ids = [p["id"] for p in presets]
        self.assertIn("fast", preset_ids)
        self.assertIn("code", preset_ids)
        self.assertIn("image", preset_ids)

    def test_demo_sample_files_exist_and_parse(self):
        sample_dir = Path(__file__).parent.parent / "src" / "council" / "demo_samples"
        self.assertTrue(sample_dir.exists())

        arch_brief = sample_dir / "architecture_brief.md"
        self.assertTrue(arch_brief.exists())
        parsed_arch = parse_uploaded_file("architecture_brief.md", "text/markdown", arch_brief.read_bytes())
        self.assertEqual(parsed_arch["kind"], "text")

        metrics_json = sample_dir / "demo_metrics.json"
        self.assertTrue(metrics_json.exists())
        parsed_metrics = parse_uploaded_file("demo_metrics.json", "application/json", metrics_json.read_bytes())
        self.assertEqual(parsed_metrics["kind"], "text")

        formatted = format_attachments_for_prompt([parsed_arch, parsed_metrics])
        self.assertIn("architecture_brief.md", formatted)
        self.assertIn("demo_metrics.json", formatted)

    @patch("orchestrator.litellm.acompletion")
    def test_fast_triage_demo_pipeline_run(self, mock_acompletion):
        # Mock LLM responses for Phase 1, Phase 2, Chairman, and async memory/skill extraction
        def mock_llm_response(model, messages, **kwargs):
            mock_resp = MagicMock()
            mock_resp.usage = {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}
            
            mock_choice = MagicMock()
            mock_choice.finish_reason = "stop"
            
            content = kwargs.get("response_format")
            if content and hasattr(content, "__name__") and "ChairmanDecision" in content.__name__:
                mock_choice.message.content = json.dumps({
                    "verdict": "Fast triage completed cleanly. Architecture is sound.",
                    "risk_score": 2,
                    "action_items": ["Proceed to MVP", "Set up monitoring"],
                    "consensus": "All seats agree",
                    "disputes": []
                })
            elif content and hasattr(content, "__name__") and "MemoryExtraction" in content.__name__:
                mock_choice.message.content = json.dumps({
                    "triples": [{"subject": "architecture", "predicate": "is", "object": "sound"}]
                })
            else:
                mock_choice.message.content = json.dumps({
                    "triples": [{"subject": "architecture", "predicate": "is", "object": "sound"}]
                }) if "extract" in str(messages).lower() else "Analysis: Low risk architecture proposed."
                
            mock_resp.choices = [mock_choice]
            return mock_resp

        mock_acompletion.side_effect = mock_llm_response

        presets = load_presets()["presets"]
        fast_triage = next(p for p in presets if p["id"] == "fast")

        async def _run():
            orchestrator = CouncilOrchestrator()
            events = []
            async for event in orchestrator.run(
                topic_text="Evaluate local-first architecture brief",
                attachments=[],
                custom_config=fast_triage["config"],
                deep_debate=False,
            ):
                events.append(event)
            return events

        events = asyncio.run(_run())
        types = [e.get("type") for e in events if isinstance(e, dict)]
        self.assertIn("phase_start", types)
        self.assertIn("member_done", types)
        self.assertIn("done", types)

    def test_eval_assertion_evaluator(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "eval"))
        from run_eval import evaluate_assertions

        topic = {
            "required_concepts": ["sql injection", "parameterized"],
            "forbidden_concepts": ["safe to ship"],
            "expected_risk_range": [7, 10],
        }

        # Perfect match
        res = {"verdict": "Critical SQL injection detected. Use parameterized queries.", "risk_score": 9}
        score, flaws = evaluate_assertions(topic, res, res["verdict"])
        self.assertEqual(score, 1.0)
        self.assertEqual(len(flaws), 0)

        # Flawed match (contains forbidden concept and missing concept)
        bad_res = {"verdict": "This is safe to ship without change.", "risk_score": 2}
        bad_score, bad_flaws = evaluate_assertions(topic, bad_res, bad_res["verdict"])
        self.assertLess(bad_score, 0.5)
        self.assertGreaterEqual(len(bad_flaws), 2)


if __name__ == "__main__":
    unittest.main()
