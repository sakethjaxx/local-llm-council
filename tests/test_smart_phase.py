import unittest
from unittest.mock import patch

import numpy as np

import smart_phase


class FakeEmbedder:
    def encode(self, texts):
        return np.array([[1.0, 0.0], [0.9, 0.1]])


class SmartPhaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_skip_returns_bool_and_score(self):
        with patch.object(smart_phase, "get_embedder", return_value=FakeEmbedder()):
            result = await smart_phase.should_skip({"a": "same", "b": "similar"})

        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], float)


if __name__ == "__main__":
    unittest.main()
