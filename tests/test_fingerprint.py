import re
import tempfile
import unittest
from pathlib import Path

from project_fingerprint import fingerprint


class FingerprintTests(unittest.TestCase):
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fingerprint(temp_dir)

        self.assertEqual(result["languages"], [])
        self.assertEqual(result["frameworks"], [])
        self.assertEqual(result["domain"], [])
        self.assertRegex(result["hash"], r"^[0-9a-f]{16}$")

    def test_python_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "app.py").write_text("print('hi')\n", encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertIn("python", result["languages"])

    def test_mixed_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("", encoding="utf-8")
            (root / "api.py").write_text("", encoding="utf-8")
            (root / "ui.ts").write_text("", encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertEqual(result["languages"][:2], ["python", "typescript"])

    def test_fastapi_framework(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertIn("fastapi", result["frameworks"])

    def test_package_json_react(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "package.json").write_text('{"dependencies":{"react":"latest"}}', encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertIn("react", result["frameworks"])

    def test_domain_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "README.md").write_text("This service exposes an endpoint.", encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertIn("api", result["domain"])

    def test_hash_determinism(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "app.py").write_text("", encoding="utf-8")

            first = fingerprint(temp_dir)
            second = fingerprint(temp_dir)

        self.assertEqual(first["hash"], second["hash"])

    def test_hash_changes_on_language_add(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = fingerprint(temp_dir)
            (root / "app.py").write_text("", encoding="utf-8")
            second = fingerprint(temp_dir)

        self.assertNotEqual(first["hash"], second["hash"])

    def test_skips_venv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "venv").mkdir()
            (root / "venv" / "ignored.py").write_text("", encoding="utf-8")
            result = fingerprint(temp_dir)

        self.assertNotIn("python", result["languages"])

    def test_hash_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = fingerprint(temp_dir)

        self.assertIsNotNone(re.match(r"^[0-9a-f]{16}$", result["hash"]))


if __name__ == "__main__":
    unittest.main()
