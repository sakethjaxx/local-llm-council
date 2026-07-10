import asyncio
import os
import types
import unittest
from unittest.mock import patch

from llm_council.llm_streamer import LLMStreamer


class FakeRunStore:
    def __init__(self):
        self.phase_outputs = []

    def record_phase_output(self, *args):
        self.phase_outputs.append(args)


class FakeMetricsStore:
    def __init__(self):
        self.calls = []

    def record_llm_call(self, **kwargs):
        self.calls.append(kwargs)


class FakeDelta:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class FakeChunk:
    def __init__(self, content="", finish_reason=None, tool_calls=None, usage=None):
        self.choices = [FakeChoice(FakeDelta(content, tool_calls), finish_reason)]
        self.usage = usage


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


class LLMStreamerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_stream_records_one_phase_output(self):
        run_store = FakeRunStore()
        metrics_store = FakeMetricsStore()
        streamer = LLMStreamer(run_store, metrics_store)

        async def fake_acompletion(*args, **kwargs):
            return FakeStream([
                FakeChunk("hello ", usage={"prompt_tokens": 3, "completion_tokens": 1}),
                FakeChunk("world", finish_reason="stop"),
            ])

        queue = asyncio.Queue()
        with patch("llm_council.llm_streamer.litellm.acompletion", side_effect=fake_acompletion):
            text = await streamer.stream(
                "architect",
                {"label": "Architect", "model": "ollama/qwen2.5:7b"},
                1,
                [{"role": "user", "content": "hi"}],
                queue,
                100,
                run_id="run-1",
            )

        self.assertEqual(text, "hello world")
        self.assertEqual(len(run_store.phase_outputs), 1)
        self.assertEqual(run_store.phase_outputs[0][0:4], ("run-1", 1, "architect", "hello world"))
        self.assertEqual(run_store.phase_outputs[0][7], "stop")
        self.assertEqual(run_store.phase_outputs[0][8], 1)

    async def test_retry_attempt_number_is_preserved(self):
        run_store = FakeRunStore()
        metrics_store = FakeMetricsStore()
        streamer = LLMStreamer(run_store, metrics_store)
        attempts = {"count": 0}

        async def fake_acompletion(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("timeout")
            return FakeStream([FakeChunk("ok", finish_reason="stop")])

        queue = asyncio.Queue()
        with patch("llm_council.llm_streamer.litellm.acompletion", side_effect=fake_acompletion), \
             patch("llm_council.llm_streamer.asyncio.sleep", return_value=None):
            await streamer.stream(
                "architect",
                {"label": "Architect", "model": "ollama/qwen2.5:7b"},
                1,
                [{"role": "user", "content": "hi"}],
                queue,
                100,
                run_id="run-2",
            )

        self.assertEqual(run_store.phase_outputs[0][8], 2)
        self.assertEqual([call["success"] for call in metrics_store.calls], [False, True])

    async def test_python_tool_followup_does_not_double_write_phase_output(self):
        run_store = FakeRunStore()
        metrics_store = FakeMetricsStore()
        streamer = LLMStreamer(run_store, metrics_store)
        calls = {"count": 0}

        tool_function = types.SimpleNamespace(name="execute_python", arguments='{"code":"print(1)"}')
        tool_call = types.SimpleNamespace(index=0, id="tool-1", function=tool_function)

        async def fake_acompletion(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return FakeStream([FakeChunk("", finish_reason="tool_calls", tool_calls=[tool_call])])
            return FakeStream([FakeChunk("final answer", finish_reason="stop")])

        queue = asyncio.Queue()
        original_flag = os.environ.get("COUNCIL_ENABLE_PYTHON_TOOL")
        os.environ["COUNCIL_ENABLE_PYTHON_TOOL"] = "true"
        try:
            with patch("llm_council.llm_streamer.litellm.acompletion", side_effect=fake_acompletion), \
                 patch("llm_council.tool_repl.execute_python", return_value="1\n"):
                text = await streamer.stream(
                    "architect",
                    {"label": "Architect", "model": "openai/gpt-4o-mini"},
                    1,
                    [{"role": "user", "content": "calculate"}],
                    queue,
                    100,
                    run_id="run-3",
                )
        finally:
            if original_flag is None:
                os.environ.pop("COUNCIL_ENABLE_PYTHON_TOOL", None)
            else:
                os.environ["COUNCIL_ENABLE_PYTHON_TOOL"] = original_flag

        self.assertIn("final answer", text)
        self.assertEqual(calls["count"], 2)
        self.assertEqual(len(run_store.phase_outputs), 1)


if __name__ == "__main__":
    unittest.main()
