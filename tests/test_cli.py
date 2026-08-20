import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cli


class CLITests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
