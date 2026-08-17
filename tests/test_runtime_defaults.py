import importlib
import os
import unittest
from unittest.mock import patch


class RuntimeDefaultsTests(unittest.TestCase):
    def test_litellm_uses_its_bundled_cost_map_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("runtime_defaults")
            importlib.reload(module)
            self.assertEqual(os.environ["LITELLM_LOCAL_MODEL_COST_MAP"], "True")


if __name__ == "__main__":
    unittest.main()
