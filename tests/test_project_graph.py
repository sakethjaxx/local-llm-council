import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
