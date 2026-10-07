import asyncio
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import tool_repl
from tool_repl import execute_python, is_docker_available

# Stands in for `docker run`: executes the code it receives on stdin, like the sandbox does.
FAKE_DOCKER = [sys.executable, "-c", "import sys; exec(sys.stdin.read())"]


class ToolREPLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.removed = []
        patches = [
            patch("tool_repl.shutil.which", return_value="/usr/bin/docker"),
            patch("tool_repl._sandbox_command", side_effect=lambda name: list(FAKE_DOCKER)),
            patch("tool_repl._remove_container", side_effect=self.removed.append),
            patch("tool_repl.EXEC_TIMEOUT_S", 2),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_runs_code_and_merges_stderr(self):
        self.assertEqual(await execute_python("```python\nprint('Result: 42')\n```"), "Result: 42")
        failed = await execute_python("1 / 0")
        self.assertIn("ZeroDivisionError", failed)
        self.assertEqual(await execute_python("a = 1"), "[Success: Code executed with no output]")
        self.assertEqual(len(self.removed), 3)  # every container is removed, not just failures

    async def test_output_is_bounded(self):
        output = await execute_python("while True:\n    print('x' * 1000)")
        self.assertIn("[output truncated at 64 KiB]", output)
        self.assertLess(len(output), tool_repl.MAX_OUTPUT_BYTES + 200)

    async def test_deadline_kills_the_run_and_removes_the_container(self):
        started = time.monotonic()
        output = await execute_python("import time\ntime.sleep(60)")
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("timed out after 2 seconds", output)
        self.assertTrue(self.removed and self.removed[0].startswith("council-sandbox-"))

    async def test_each_call_gets_a_unique_container_name(self):
        await asyncio.gather(execute_python("pass"), execute_python("pass"))
        self.assertEqual(len(set(self.removed)), 2)

    async def test_cancellation_stops_the_container_promptly(self):
        task = asyncio.create_task(execute_python("import time\ntime.sleep(60)"))
        await asyncio.sleep(0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 1.5
        while not self.removed and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertTrue(self.removed, "container was not removed on cancellation")

    async def test_event_loop_stays_responsive_while_code_runs(self):
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticking = asyncio.create_task(ticker())
        await execute_python("import time\ntime.sleep(0.5)")
        ticking.cancel()
        self.assertGreater(ticks, 20)

    async def test_missing_image_explains_how_to_fix_it(self):
        output = await execute_python("print('Unable to find image python:3.11-slim locally')")
        self.assertIn("docker pull python:3.11-slim", output)

    async def test_missing_docker_cli(self):
        with patch("tool_repl.shutil.which", return_value=None):
            self.assertIn("Docker is not installed", await execute_python("print(1)"))


class SandboxCommandTests(unittest.TestCase):
    def test_container_is_named_offline_and_unprivileged(self):
        command = tool_repl._sandbox_command("council-sandbox-abc")
        joined = " ".join(command)
        for flag in ("--name council-sandbox-abc", "--network none", "--read-only", "--cap-drop ALL",
                     "--pull never", "--user 65534:65534", "--memory 256m", "--pids-limit 128"):
            self.assertIn(flag, joined)
        self.assertNotIn("-v", command)  # code goes over stdin, nothing from the host is mounted


class DockerAvailabilityTests(unittest.TestCase):
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


@unittest.skipUnless(os.getenv("COUNCIL_TEST_DOCKER") == "1" and is_docker_available(),
                     "live Docker check: set COUNCIL_TEST_DOCKER=1 with a running daemon and the sandbox image pulled")
class LiveDockerSandboxTests(unittest.IsolatedAsyncioTestCase):
    def _leftovers(self):
        out = subprocess.run(["docker", "ps", "-a", "--filter", "name=council-sandbox-", "--format", "{{.Names}}"],
                             capture_output=True, text=True, timeout=30).stdout
        return [line for line in out.splitlines() if line.strip()]

    async def test_live_run_timeout_and_cleanup(self):
        self.assertEqual(await execute_python("print(6 * 7)"), "42")
        self.assertIn("Network is unreachable", await execute_python(
            "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), 2)\nexcept OSError as e:\n    print(e)"))
        started = time.monotonic()
        self.assertIn("timed out", await execute_python("import time\ntime.sleep(60)"))
        self.assertLess(time.monotonic() - started, tool_repl.EXEC_TIMEOUT_S + 20)
        self.assertEqual(self._leftovers(), [])


if __name__ == "__main__":
    unittest.main()
