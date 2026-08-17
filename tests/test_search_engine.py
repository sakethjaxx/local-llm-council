import os
import unittest
from unittest.mock import AsyncMock, patch

import search_engine


class SearchEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_is_disabled_by_default_without_an_llm_call(self):
        with patch.dict(os.environ, {"COUNCIL_ENABLE_WEB_SEARCH": "false"}), \
             patch("search_engine.litellm.acompletion", new_callable=AsyncMock) as completion:
            result = await search_engine.get_search_context(
                {"reviewer": "Is this claim stable?"}, "ollama/llama3.2:3b"
            )

        self.assertEqual(result, "")
        completion.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
