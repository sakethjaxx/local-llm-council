import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cli


class CLITests(unittest.TestCase):
    def setUp(self):
        # CI has no Ollama daemon; tests that care about preflight patch it themselves.
        patcher = patch("cli.ensure_models_for_config", return_value={"ready": True, "missing": []})
        self.ensure_models = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("cli.sys.argv", ["cli.py", "check_diff"])
    @patch("cli.subprocess.run")
    @patch("cli.get_hardware_suggestion")
    @patch("cli.CouncilOrchestrator")
    def test_cli_check_diff_success(self, mock_orch_class, mock_hardware_suggest, mock_run, *args):
        # 1. Mock subprocess.run for git diff --cached
        mock_diff_result = MagicMock()
        mock_diff_result.stdout = "def test():\n    pass"
        
        mock_files_result = MagicMock()
        mock_files_result.stdout = "test_file.py\n"
        
        mock_run.side_effect = [mock_diff_result, mock_files_result]

        # 2. Mock hardware suggestions
        mock_hardware_suggest.return_value = {
            "config": {
                "security": {"model": "ollama/qwen2.5:7b", "persona": "security analyst"},
                "chairman": {"model": "ollama/qwen2.5:7b", "persona": "chairman"},
            }
        }

        # 3. Mock CouncilOrchestrator and its run generator
        mock_orch = MagicMock()
        mock_orch_class.return_value = mock_orch

        async def mock_run_generator(*args, **kwargs):
            yield {"type": "phase_start", "label": "Independent Analysis"}
            yield {"type": "token", "text": "Analyzing..."}
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 2, "action_items": []}'}

        mock_orch.run = mock_run_generator

        # Run the cli main
        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(0)

    @patch("cli.sys.argv", ["cli.py", "check_diff"])
    @patch("cli.subprocess.run")
    @patch("cli.get_hardware_suggestion")
    @patch("cli.CouncilOrchestrator")
    def test_cli_check_diff_rejected(self, mock_orch_class, mock_hardware_suggest, mock_run, *args):
        mock_diff_result = MagicMock()
        mock_diff_result.stdout = "def test():\n    pass"
        
        mock_files_result = MagicMock()
        mock_files_result.stdout = "test_file.py\n"
        
        mock_run.side_effect = [mock_diff_result, mock_files_result]

        mock_hardware_suggest.return_value = {
            "config": {
                "security": {"model": "ollama/qwen2.5:7b", "persona": "security analyst"},
                "chairman": {"model": "ollama/qwen2.5:7b", "persona": "chairman"},
            }
        }

        mock_orch = MagicMock()
        mock_orch_class.return_value = mock_orch

        async def mock_run_generator(*args, **kwargs):
            yield {"type": "phase_start", "label": "Independent Analysis"}
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "REJECT", "risk_score": 9, "action_items": ["Fix vuln"]}'}

        mock_orch.run = mock_run_generator

        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(1)

    @patch("cli.sys.argv", ["cli.py", "check_diff"])
    @patch("cli.subprocess.run")
    @patch("cli.get_hardware_suggestion")
    @patch("cli.CouncilOrchestrator")
    def test_cli_check_diff_static_backstop_overrides_model_approval(
        self, mock_orch_class, mock_hardware_suggest, mock_run, *args
    ):
        # Model approves at a low risk score, but the diff adds a shell-injection
        # pattern the static backstop must catch regardless (see _static_diff_findings).
        mock_diff_result = MagicMock()
        mock_diff_result.stdout = "+import os\n+os.system(user_input)\n"

        mock_files_result = MagicMock()
        mock_files_result.stdout = "app.py\n"

        mock_run.side_effect = [mock_diff_result, mock_files_result]

        mock_hardware_suggest.return_value = {
            "config": {
                "security": {"model": "ollama/qwen2.5:7b", "persona": "security analyst"},
                "chairman": {"model": "ollama/qwen2.5:7b", "persona": "chairman"},
            }
        }

        mock_orch = MagicMock()
        mock_orch_class.return_value = mock_orch

        async def mock_run_generator(*args, **kwargs):
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 2, "action_items": []}'}

        mock_orch.run = mock_run_generator

        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(1)

    @patch("cli.sys.argv", ["cli.py", "ask", "Should we migrate to SQLite WAL?"])
    @patch("cli.CouncilOrchestrator")
    def test_cli_ask_command(self, mock_orch_class):
        mock_orch = MagicMock()
        mock_orch_class.return_value = mock_orch

        async def mock_run_generator(*args, **kwargs):
            yield {"type": "phase_start", "label": "Analysis"}
            yield {"type": "member_token", "chunk": "SQLite is solid."}
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 1}'}

        mock_orch.run = mock_run_generator

        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(0)

    @patch("cli.sys.argv", ["cli.py", "models"])
    @patch("cli.get_hardware_suggestion")
    def test_cli_models_command(self, mock_hw):
        mock_hw.return_value = {
            "preset": "balanced",
            "total_ram_gb": 16,
            "vram_gb": 16,
            "config": {
                "security": {"model": "ollama/qwen2.5:7b", "persona": "Security lead"},
            }
        }
        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(0)

    @patch("cli.sys.argv", ["cli.py", "history", "--limit", "5"])
    @patch("cli.RunStore")
    def test_cli_history_command(self, mock_store_class):
        mock_store = MagicMock()
        mock_store.list_runs.return_value = [
            {"run_id": "run-1234567890", "status": "completed", "topic": "DB Architecture"}
        ]
        mock_store_class.return_value = mock_store

        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(0)

    @patch("cli.CouncilOrchestrator")
    def test_cli_review_file_command(self, mock_orch_class):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def add(a, b): return a + b\n")
            temp_path = f.name

        try:
            with patch("cli.sys.argv", ["cli.py", "review", temp_path]):
                mock_orch = MagicMock()
                mock_orch_class.return_value = mock_orch

                async def mock_run_generator(*args, **kwargs):
                    yield {"type": "token", "text": "Looks good."}
                    yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 0}'}

                mock_orch.run = mock_run_generator

                with patch("cli.sys.exit") as mock_exit:
                    asyncio.run(cli.main())
                    mock_exit.assert_called_once_with(0)
        finally:
            Path(temp_path).unlink(missing_ok=True)


    def _run_with_signature_check(self, argv):
        """Run the CLI against a fake run() that must bind to the real signature."""
        import inspect
        from orchestrator import CouncilOrchestrator

        real_sig = inspect.signature(CouncilOrchestrator.run)
        seen = {}

        async def checked_run(orch_self, *args, **kwargs):
            seen["args"] = real_sig.bind(orch_self, *args, **kwargs).arguments  # TypeError on drift
            yield {"type": "member_thinking", "member": "architect", "meta": {"label": "Lead Architect"}}
            yield {"type": "member_done", "member": "architect", "full_text": "analysis"}
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 1, "action_items": ["Ship it"]}'}

        with patch("cli.sys.argv", argv), patch.object(CouncilOrchestrator, "run", checked_run), \
                patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
        mock_exit.assert_called_once_with(0)
        return seen["args"]

    def test_cli_ask_matches_real_orchestrator_signature(self):
        args = self._run_with_signature_check(["cli.py", "ask", "Is WAL safe?", "--fast-mode", "--deep-debate"])
        self.assertEqual(args["token_budget_profile"], "economy")
        self.assertTrue(args["deep_debate"])

    def test_cli_review_directory_attaches_source_files(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "app.py").write_text("import util\n\ndef main():\n    return util.VALUE\n", encoding="utf-8")
            Path(root, "util.py").write_text("VALUE = 1\n", encoding="utf-8")
            args = self._run_with_signature_check(["cli.py", "review", root])
        filenames = sorted(a["filename"] for a in args["attachments"])
        self.assertEqual(filenames, ["app.py", "util.py"])

    @patch("cli.sys.argv", ["cli.py", "ask", "Unparseable?", "--json"])
    @patch("cli.CouncilOrchestrator")
    def test_cli_ask_exits_nonzero_when_verdict_unparseable(self, mock_orch_class):
        async def mock_run_generator(*args, **kwargs):
            yield {"type": "member_done", "member": "chairman", "full_text": "[Error connecting to Chairman]"}

        mock_orch_class.return_value.run = mock_run_generator
        with patch("cli.sys.exit") as mock_exit:
            asyncio.run(cli.main())
        mock_exit.assert_called_once_with(1)

    def test_cli_model_flag_puts_every_seat_on_that_model(self):
        args = self._run_with_signature_check(["cli.py", "ask", "Is WAL safe?", "--model", "qwen2.5:3b"])
        self.assertEqual({seat["model"] for seat in args["custom_config"].values()}, {"ollama/qwen2.5:3b"})
        self.assertIn("chairman", args["custom_config"])

    def test_cli_preset_flag_uses_the_preset_roster(self):
        from demo_catalog import load_presets

        feather = next(p for p in load_presets()["presets"] if p["id"] == "feather")
        args = self._run_with_signature_check(["cli.py", "ask", "Is WAL safe?", "--preset", "feather"])
        self.assertEqual(args["custom_config"], feather["config"])
        args = self._run_with_signature_check(["cli.py", "ask", "x", "--preset", "feather", "--model", "gemma2:2b"])
        self.assertEqual({seat["model"] for seat in args["custom_config"].values()}, {"ollama/gemma2:2b"})
        self.assertEqual(feather["config"]["chairman"]["model"], "ollama/qwen2.5:3b")  # preset not mutated

    @patch("cli.CouncilOrchestrator")
    def test_cli_unknown_preset_exits_2(self, mock_orch_class):
        with patch("cli.sys.argv", ["cli.py", "ask", "x", "--preset", "nope"]),                 patch("cli.sys.exit", side_effect=SystemExit) as mock_exit:
            with self.assertRaises(SystemExit):
                asyncio.run(cli.main())
        mock_exit.assert_called_once_with(2)
        mock_orch_class.assert_not_called()

    @patch("cli.CouncilOrchestrator")
    def test_cli_missing_model_stops_before_running_and_says_how_to_pull(self, mock_orch_class):
        self.ensure_models.return_value = {"ready": False, "missing": ["qwen2.5:3b"]}
        stderr = io.StringIO()
        with patch("cli.sys.argv", ["cli.py", "ask", "x", "--model", "qwen2.5:3b"]),                 patch("cli.sys.exit", side_effect=SystemExit) as mock_exit, patch("cli.sys.stderr", stderr):
            with self.assertRaises(SystemExit):
                asyncio.run(cli.main())
        mock_exit.assert_called_once_with(1)
        mock_orch_class.assert_not_called()
        self.assertIn("ollama pull qwen2.5:3b", stderr.getvalue())


class StaticDiffFindingsTests(unittest.TestCase):
    def test_flags_os_system(self):
        findings = cli._static_diff_findings("+os.system(cmd)\n")
        self.assertEqual(len(findings), 1)
        self.assertIn("os.system", findings[0])

    def test_flags_subprocess_shell_true(self):
        findings = cli._static_diff_findings("+subprocess.run(cmd, shell=True)\n")
        self.assertTrue(any("shell=True" in f for f in findings))

    def test_flags_subprocess_shell_true_wrapped_across_lines(self):
        diff = "+subprocess.run(\n+    cmd,\n+    shell=True,\n+)\n"
        findings = cli._static_diff_findings(diff)
        self.assertTrue(any("shell=True" in f for f in findings))

    def test_flags_eval_exec_pickle_yaml_dynamic_import(self):
        diff = (
            "+eval(x)\n"
            "+exec(x)\n"
            "+pickle.loads(data)\n"
            "+yaml.load(data)\n"
            "+__import__(name)\n"
        )
        findings = cli._static_diff_findings(diff)
        self.assertEqual(len(findings), 5)

    def test_yaml_safe_loader_not_flagged(self):
        findings = cli._static_diff_findings("+yaml.load(data, Loader=yaml.SafeLoader)\n")
        self.assertEqual(findings, [])

    def test_ignores_removed_and_context_lines(self):
        diff = (
            "-os.system(cmd)\n"
            " os.system(cmd)\n"
            "+++ b/file.py\n"
        )
        self.assertEqual(cli._static_diff_findings(diff), [])

    def test_clean_diff_has_no_findings(self):
        findings = cli._static_diff_findings("+def add(a, b):\n+    return a + b\n")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
