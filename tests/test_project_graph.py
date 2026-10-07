import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_graph import ProjectGraph, build_project_graph, get_project_code_graph


class ProjectGraphTests(unittest.TestCase):
    def test_project_graph_operations(self):
        graph = ProjectGraph()
        graph.add_node("a.py")
        graph.add_node("b.py")
        graph.add_edge("a.py", "b.py", kind="import")

        self.assertIn("a.py", graph)
        self.assertIn("b.py", graph)
        self.assertNotIn("c.py", graph)

        self.assertEqual(graph.number_of_nodes(), 2)
        self.assertEqual(graph.number_of_edges(), 1)

        self.assertEqual(graph.predecessors("b.py"), ["a.py"])
        self.assertEqual(graph.predecessors("a.py"), [])

        self.assertEqual(graph.get_edge_data("a.py", "b.py"), {"kind": "import"})

        self.assertEqual(graph.in_degree("b.py"), 1)
        self.assertEqual(graph.out_degree("a.py"), 1)
        self.assertEqual(graph.degree("a.py"), 1)

    def test_build_project_graph_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "module_a.py").write_text("import module_b\n", encoding="utf-8")
            (root / "module_b.py").write_text("VALUE = 42\n", encoding="utf-8")
            (root / "standalone.py").write_text("print('hello')\n", encoding="utf-8")

            graph = build_project_graph(root)
            self.assertEqual(graph.number_of_nodes(), 3)
            self.assertEqual(graph.number_of_edges(), 1)
            self.assertEqual(graph.predecessors("module_b.py"), ["module_a.py"])

            data = get_project_code_graph(root)
            self.assertEqual(data["stats"]["files"], 3)
            self.assertEqual(data["stats"]["edges"], 1)
            self.assertIn("standalone.py", data["stats"]["isolated"])
            self.assertIn("PROJECT CODE GRAPH", data["summary"])

    def test_build_project_graph_with_nested_subpackages_and_relative_imports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pkg = root / "src" / "council"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "embeddings.py").write_text("def get_embedder(): pass\n", encoding="utf-8")
            (pkg / "main.py").write_text("from .embeddings import get_embedder\nfrom embeddings import get_embedder\n", encoding="utf-8")
            (root / "run.py").write_text("from src.council.main import app\n", encoding="utf-8")

            graph = build_project_graph(root)
            self.assertEqual(graph.number_of_nodes(), 4)
            # Both relative and sibling imports connect main.py to embeddings.py
            self.assertEqual(graph.predecessors("src/council/embeddings.py"), ["src/council/main.py"])
            self.assertEqual(graph.predecessors("src/council/main.py"), ["run.py"])

    def test_build_project_graph_package_init_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pkg = root / "src" / "my_pkg"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("VERSION = '1.0'\n", encoding="utf-8")
            (root / "app.py").write_text("import my_pkg\n", encoding="utf-8")

            graph = build_project_graph(root)
            self.assertEqual(graph.number_of_nodes(), 2)
            self.assertEqual(graph.predecessors("src/my_pkg/__init__.py"), ["app.py"])


class ProjectGraphLimitTests(unittest.TestCase):
    def test_small_repo_reports_no_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.py").write_text("import b\n", encoding="utf-8")
            Path(tmp, "b.py").write_text("X = 1\n", encoding="utf-8")
            truncation = get_project_code_graph(tmp)["stats"]["truncation"]
        self.assertEqual({k: truncation[k] for k in ("files", "input_bytes", "edges", "skipped_large_files")},
                         {"files": False, "input_bytes": False, "edges": False, "skipped_large_files": 0})
        self.assertEqual(truncation["limits"], {"max_files": 4000, "max_file_bytes": 1048576,
                                                "max_input_bytes": 16777216, "max_edges": 20000})

    def test_oversized_file_is_listed_but_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.py").write_text("import big\n", encoding="utf-8")
            Path(tmp, "big.py").write_text("import a\n" + "#" * (1024 * 1024 + 10), encoding="utf-8")
            graph = get_project_code_graph(tmp)
        self.assertIn("big.py", [n["id"] for n in graph["nodes"]])
        self.assertEqual(graph["stats"]["truncation"]["skipped_large_files"], 1)
        self.assertEqual([(e["from"], e["to"]) for e in graph["edges"]], [("a.py", "big.py")])  # none out of big.py
        self.assertIn("partial graph", graph["review_input"])

    def test_file_input_and_edge_limits_stop_work_and_say_so(self):
        import project_graph

        with tempfile.TemporaryDirectory() as tmp:
            for i in range(10):
                Path(tmp, f"m{i}.py").write_text("".join(f"import m{j}\n" for j in range(10) if j != i), encoding="utf-8")
            with patch.object(project_graph, "MAX_GRAPH_FILES", 6), \
                    patch.object(project_graph, "MAX_GRAPH_EDGES", 7), \
                    patch.object(project_graph, "MAX_GRAPH_INPUT_BYTES", 200):
                graph = get_project_code_graph(tmp)
        truncation = graph["stats"]["truncation"]
        self.assertEqual(graph["stats"]["files"], 6)
        self.assertLessEqual(graph["stats"]["edges"], 7)
        self.assertTrue(truncation["files"] and truncation["input_bytes"])
        self.assertIn("partial graph", graph["review_input"])

    def test_edge_limit_alone(self):
        import project_graph

        with tempfile.TemporaryDirectory() as tmp:
            for i in range(8):
                Path(tmp, f"m{i}.py").write_text("".join(f"import m{j}\n" for j in range(8) if j != i), encoding="utf-8")
            with patch.object(project_graph, "MAX_GRAPH_EDGES", 5):
                graph = get_project_code_graph(tmp)
        self.assertEqual(graph["stats"]["edges"], 5)
        self.assertTrue(graph["stats"]["truncation"]["edges"])


if __name__ == "__main__":
    unittest.main()
