import sys
import types
import unittest


class FakeSentenceTransformer:
    def __init__(self, model_name):
        self.model_name = model_name

    def encode(self, texts):
        return texts


class EmbeddingsTests(unittest.TestCase):
    def setUp(self):
        module = types.ModuleType("sentence_transformers")
        module.SentenceTransformer = FakeSentenceTransformer
        sys.modules["sentence_transformers"] = module

        import llm_council.embeddings as embeddings

        embeddings._embedder = None
        self.embeddings = embeddings

    def test_get_embedder_returns_singleton_with_encode(self):
        first = self.embeddings.get_embedder()
        second = self.embeddings.get_embedder()

        self.assertIs(first, second)
        self.assertTrue(hasattr(first, "encode"))


if __name__ == "__main__":
    unittest.main()
