import os
import tempfile
import unittest
from pathlib import Path

from llm_council.blast_radius import calculate_blast_radius


class BlastRadiusTests(unittest.TestCase):
    def test_calculate_blast_radius_uses_project_graph_shape(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "feature.py").write_text("import core\nprint(core.VALUE)\n", encoding="utf-8")
            os.chdir(root)
            try:
                result = calculate_blast_radius(["core.py"])
            finally:
                os.chdir(cwd)

        self.assertIn("NATIVE ARCHITECTURAL BLAST RADIUS WARNING", result)
        self.assertIn("The following files import or depend on the changed files and may silently break:", result)
        self.assertIn("- feature.py", result)


if __name__ == "__main__":
    unittest.main()
