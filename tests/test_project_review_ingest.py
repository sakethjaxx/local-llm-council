import os
import tempfile
import unittest

import main
from project_graph import get_project_code_graph


def _write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class ProjectGraphSuffixTests(unittest.TestCase):
    def test_graph_includes_non_python_web_sources(self):
        """A TS/React project used to be almost entirely invisible to review."""
        with tempfile.TemporaryDirectory() as root:
            _write(root, "src/App.tsx", "import { api } from './api';")
            _write(root, "src/api.ts", "export const api = 1;")
            _write(root, "src/styles.scss", "body { color: red; }")
            _write(root, "README.md", "# docs")
            _write(root, "go/main.go", "package main")

            graph = get_project_code_graph(root)
            files = {node["id"] for node in graph["nodes"]}

        self.assertIn("src/App.tsx", files)
        self.assertIn("src/api.ts", files)
        self.assertIn("src/styles.scss", files)
        self.assertIn("README.md", files)
        self.assertIn("go/main.go", files)

    def test_relative_import_resolves_to_sibling_file(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "server/index.js", "const db = require('./db');")
            _write(root, "server/db.js", "module.exports = {};")
            _write(root, "client/db.js", "module.exports = {};")

            graph = get_project_code_graph(root)
            edges = {(e["from"], e["to"]) for e in graph["edges"]}

        self.assertIn(("server/index.js", "server/db.js"), edges)
        self.assertNotIn(("server/index.js", "client/db.js"), edges)

    def test_excluded_and_hidden_dirs_are_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "app.py", "x = 1")
            _write(root, "node_modules/dep/index.js", "x")
            _write(root, ".venv/lib/thing.py", "x")

            graph = get_project_code_graph(root)
            files = {node["id"] for node in graph["nodes"]}

        self.assertEqual(files, {"app.py"})


class PickTopFilesTests(unittest.TestCase):
    def test_fills_budget_from_all_nodes_not_just_hubs(self):
        graph_data = {
            "nodes": [{"id": f"f{i}.py"} for i in range(30)],
            "stats": {
                "top_inbound": [["f0.py", 3]],
                "top_outbound": [["f1.py", 2]],
                "isolated": [],
            },
        }
        picked = main._pick_top_files(graph_data, 25)

        self.assertEqual(len(picked), 25)
        self.assertEqual(picked[0], "f0.py")
        self.assertEqual(picked[1], "f1.py")
        self.assertEqual(len(set(picked)), 25)

    def test_respects_budget_smaller_than_available(self):
        graph_data = {
            "nodes": [{"id": f"f{i}.py"} for i in range(30)],
            "stats": {"top_inbound": [], "top_outbound": [], "isolated": []},
        }
        self.assertEqual(len(main._pick_top_files(graph_data, 5)), 5)

    def test_empty_graph_yields_no_files(self):
        self.assertEqual(main._pick_top_files({"nodes": [], "stats": {}}, 25), [])


class ReadAttachmentsTests(unittest.TestCase):
    def test_per_file_cap_scales_with_file_count(self):
        with tempfile.TemporaryDirectory() as root:
            body = "x" * 200_000
            for i in range(40):
                _write(root, f"f{i}.py", body)
            rel_paths = [f"f{i}.py" for i in range(40)]

            attachments = main._read_files_as_attachments(root, rel_paths)

        self.assertEqual(len(attachments), 40)
        total = sum(len(a["text"]) for a in attachments)
        # Budget is split across files rather than 12k per file unconditionally.
        self.assertLessEqual(total, main.REVIEW_CHAR_BUDGET + 40)

    def test_unreadable_paths_are_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "real.py", "print(1)")
            attachments = main._read_files_as_attachments(root, ["real.py", "missing.py"])

        self.assertEqual([a["filename"] for a in attachments], ["real.py"])


if __name__ == "__main__":
    unittest.main()
