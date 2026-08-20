import subprocess
import unittest
from unittest.mock import MagicMock, patch

from tool_repl import execute_python, is_docker_available


class ToolREPLTests(unittest.TestCase):
    @patch("tool_repl.shutil.which", return_value=None)
    def test_is_docker_available_when_not_installed(self, mock_which):
        self.assertFalse(is_docker_available())

    @patch("tool_repl.shutil.which", return_value="/usr/local/bin/docker")
    @patch("tool_repl.subprocess.run")
    def test_is_docker_available_when_daemon_healthy(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(is_docker_available())

    @patch("tool_repl.shutil.which", return_value="/usr/local/bin/docker")
    @patch("tool_repl.subprocess.run")
    def test_is_docker_available_when_daemon_error(self, mock_run, mock_which):
        mock_run.side_effect = subprocess.SubprocessError("Daemon unreachable")
        self.assertFalse(is_docker_available())

    @patch("tool_repl.shutil.which", return_value=None)
    def test_execute_python_missing_docker_error_message(self, mock_which):
        res = execute_python("print('hello')")
        self.assertIn("Docker is not installed", res)

    @patch("tool_repl.shutil.which", return_value="/usr/local/bin/docker")
    @patch("tool_repl.subprocess.run")
    def test_execute_python_successful_execution(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="Result: 42\n", stderr="")
        res = execute_python("```python\nprint('Result: 42')\n```")
        self.assertEqual(res, "Result: 42")

    @patch("tool_repl.shutil.which", return_value="/usr/local/bin/docker")
    @patch("tool_repl.subprocess.run")
    def test_execute_python_timeout(self, mock_run, mock_which):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
        res = execute_python("while True: pass")
        self.assertIn("timed out after 10 seconds", res)

    @patch("tool_repl.shutil.which", return_value="/usr/local/bin/docker")
    @patch("tool_repl.subprocess.run")
    def test_execute_python_stderr_and_no_output(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="Traceback...")
        res = execute_python("1 / 0")
        self.assertIn("[Error]", res)
        self.assertIn("Traceback...", res)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res2 = execute_python("a = 1")
        self.assertIn("Success: Code executed with no output", res2)


if __name__ == "__main__":
    unittest.main()
