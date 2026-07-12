import sys
import types
import unittest

if "litellm" not in sys.modules:
    litellm_stub = types.ModuleType("litellm")
    litellm_stub.suppress_debug_info = False
    sys.modules["litellm"] = litellm_stub

from summarizer import _chunk_text, CHUNK_SIZE_LIMIT, CHUNK_OVERLAP


class ChunkTextTests(unittest.TestCase):
    def test_oversized_single_line_is_hard_split(self):
        # One giant line with no newlines must still be capped at the limit.
        text = "x" * (CHUNK_SIZE_LIMIT * 3 + 100)
        chunks = _chunk_text(text)
        self.assertGreaterEqual(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(len(c), CHUNK_SIZE_LIMIT)

    def test_chunks_overlap(self):
        text = "\n".join(f"line-{i} " + "y" * 200 for i in range(300))
        chunks = _chunk_text(text)
        self.assertGreater(len(chunks), 1)
        # The tail of one chunk should reappear at the head of the next.
        tail = chunks[0][-CHUNK_OVERLAP:]
        self.assertTrue(any(fragment and fragment in chunks[1] for fragment in [tail[-50:]]))

    def test_short_input_single_chunk(self):
        self.assertEqual(_chunk_text("small"), ["small"])


if __name__ == "__main__":
    unittest.main()
