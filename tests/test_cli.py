import sys
import unittest
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

        # We mock CouncilOrchestrator.run() to be an async generator
        async def mock_run_generator(*args, **kwargs):
            yield {"type": "phase_start", "label": "Independent Analysis"}
            yield {"type": "token", "text": "Analyzing..."}
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "APPROVE", "risk_score": 2, "action_items": []}'}

        mock_orch.run = mock_run_generator

        # Run the cli main
        with patch("cli.sys.exit") as mock_exit:
            import asyncio
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(0)

    @patch("cli.sys.argv", ["cli.py", "check_diff"])
    @patch("cli.subprocess.run")
    @patch("cli.get_hardware_suggestion")
    @patch("cli.CouncilOrchestrator")
    def test_cli_check_diff_rejected(self, mock_orch_class, mock_hardware_suggest, mock_run, *args):
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
            yield {"type": "member_done", "member": "chairman", "full_text": '{"verdict": "REJECT", "risk_score": 9, "action_items": ["Fix vuln"]}'}

        mock_orch.run = mock_run_generator

        # Run the cli main
        with patch("cli.sys.exit") as mock_exit:
            import asyncio
            asyncio.run(cli.main())
            mock_exit.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
