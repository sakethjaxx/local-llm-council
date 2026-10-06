import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import ollama_manager


class FakeStdout:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, n):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class FakeProcess:
    def __init__(self, chunks, returncode=0):
        self.stdout = FakeStdout(chunks)
        self._returncode = returncode

    async def wait(self):
        return self._returncode


async def _collect(tag):
    events = []
    async for event in ollama_manager.pull_model_stream(tag):
        events.append(event)
    return events


class PullModelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_progress_lines_and_done_on_success(self):
        chunks = [b"pulling manifest\n", b"pulling abc... 50%\rpulling abc... 100%\n"]
        fake_proc = FakeProcess(chunks, returncode=0)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            events = await _collect("qwen2.5:7b")

        line_events = [e for e in events if e["type"] == "line"]
        self.assertEqual(
            [e["text"] for e in line_events],
            ["pulling manifest", "pulling abc... 50%", "pulling abc... 100%"],
        )
        self.assertEqual(events[-1], {"type": "done", "success": True, "returncode": 0})

    async def test_nonzero_returncode_reports_failure(self):
        fake_proc = FakeProcess([b"error: model not found\n"], returncode=1)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            events = await _collect("bogus:tag")

        self.assertEqual(events[-1], {"type": "done", "success": False, "returncode": 1})

    async def test_missing_ollama_binary_yields_error_then_done(self):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=FileNotFoundError())):
            events = await _collect("qwen2.5:7b")

        self.assertEqual(events[0], {"type": "error", "message": "ollama command not found"})
        self.assertEqual(events[-1], {"type": "done", "success": False, "returncode": 127})


class InstalledModelsTests(unittest.TestCase):
    def test_reads_tags_from_daemon_http_api(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:latest"}]}

        with patch.dict("os.environ", {"OLLAMA_API_BASE": "http://ollama-host:11434/"}), \
                patch("ollama_manager.httpx.get", return_value=FakeResponse()) as fake_get:
            self.assertEqual(ollama_manager.get_installed_models(), ["qwen2.5:7b", "llama3.2:latest"])
        fake_get.assert_called_once_with("http://ollama-host:11434/api/tags", timeout=5.0)

    def test_unreachable_daemon_means_no_models(self):
        with patch("ollama_manager.httpx.get", side_effect=OSError("connection refused")):
            self.assertEqual(ollama_manager.get_installed_models(), [])


if __name__ == "__main__":
    unittest.main()
