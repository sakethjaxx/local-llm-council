import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import llm_stream

TOOL_MODEL = {"model": "openai/gpt-4o", "label": "Analyst"}  # registry says tool_use=True
LOCAL_MODEL = {"model": "ollama/qwen2.5:3b", "label": "Analyst"}  # no tool support


def call(name="execute_python", arguments=None, code="print(1)"):
    args = json.dumps({"code": code}) if arguments is None else arguments
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": args}}


class ToolAuthorizationTests(unittest.TestCase):
    def authorized(self, cfg=TOOL_MODEL, phase=1, depth=0, tool_call=None, enabled="true"):
        with patch.dict(os.environ, {"COUNCIL_ENABLE_PYTHON_TOOL": enabled}):
            return llm_stream._authorized_python_code(cfg, phase, depth, tool_call or call())

    def test_offered_call_is_allowed(self):
        self.assertEqual(self.authorized(), "print(1)")

    def test_every_missing_condition_refuses(self):
        cases = {
            "tool not enabled": dict(enabled="false"),
            "model without tool support": dict(cfg=LOCAL_MODEL),
            "phase 2": dict(phase=2),
            "phase 3": dict(phase=3),
            "recursion limit": dict(depth=llm_stream.MAX_TOOL_DEPTH),
            "other function": dict(tool_call=call(name="run_shell")),
            "malformed json": dict(tool_call=call(arguments="{not json")),
            "arguments not an object": dict(tool_call=call(arguments='"print(1)"')),
            "code not a string": dict(tool_call=call(arguments='{"code": 5}')),
            "empty code": dict(tool_call=call(code="   ")),
            "oversized code": dict(tool_call=call(code="x" * (llm_stream.MAX_TOOL_CODE_CHARS + 1))),
            "missing function": dict(tool_call={"id": "c", "type": "function"}),
        }
        for name, kwargs in cases.items():
            self.assertIsNone(self.authorized(**kwargs), name)


class ForgedToolCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsolicited_tool_call_never_reaches_the_sandbox(self):
        orchestrator = AsyncMock()
        with patch.dict(os.environ, {"COUNCIL_ENABLE_PYTHON_TOOL": "false"}), \
                patch("tool_repl.execute_python", new=AsyncMock(return_value="ran")) as sandbox:
            text, followed_up = await llm_stream._handle_tool_execution(
                orchestrator, "architect", TOOL_MODEL, 1, [], asyncio.Queue(), "analysis", [call()], None, 0)
        sandbox.assert_not_called()
        orchestrator._stream_llm_to_queue.assert_not_called()
        self.assertEqual((text, followed_up), ("analysis", False))

    async def test_authorized_call_runs_once_and_replies_with_only_that_call(self):
        orchestrator = AsyncMock()
        orchestrator._stream_llm_to_queue.return_value = " follow-up"
        messages = []
        forged = call(name="run_shell")
        with patch.dict(os.environ, {"COUNCIL_ENABLE_PYTHON_TOOL": "true"}), \
                patch("tool_repl.execute_python", new=AsyncMock(return_value="42")) as sandbox:
            text, followed_up = await llm_stream._handle_tool_execution(
                orchestrator, "architect", TOOL_MODEL, 1, messages, asyncio.Queue(), "analysis",
                [forged, call(code="print(6*7)")], None, 0)
        sandbox.assert_awaited_once_with("print(6*7)")
        self.assertTrue(followed_up)
        self.assertEqual([c["function"]["name"] for c in messages[0]["tool_calls"]], ["execute_python"])
        self.assertEqual(orchestrator._stream_llm_to_queue.await_args.kwargs["tool_depth"], 1)


if __name__ == "__main__":
    unittest.main()
