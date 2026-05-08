import ast
import os
import re
from pathlib import Path

import networkx as nx


EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", "venv", ".env", "env"}
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".html", ".css")


def _iter_source_files(repo_root: Path):
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for filename in files:
            path = Path(root) / filename
            if path.suffix in SOURCE_SUFFIXES:
                yield path


def _relative_module_path(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


def build_project_graph(repo_root: str | Path = ".") -> nx.DiGraph:
    root = Path(repo_root).resolve()
    graph = nx.DiGraph()

    source_files = list(_iter_source_files(root))
    rel_paths = {path: str(path.relative_to(root)) for path in source_files}
    known_rel_paths = set(rel_paths.values())

    for path, rel_path in rel_paths.items():
        graph.add_node(rel_path)

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        if path.suffix == ".py":
            try:
                tree = ast.parse(content)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imported = _relative_module_path(name.name)
                        if imported in known_rel_paths:
                            graph.add_edge(rel_path, imported, kind="import")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = _relative_module_path(node.module)
                    if imported in known_rel_paths:
                        graph.add_edge(rel_path, imported, kind="import_from")
        else:
            matches = re.findall(r"""['"]([^'"]+\.(?:py|js|ts|html|css))['"]""", content)
            for match in matches:
                basename = os.path.basename(match)
                for candidate in known_rel_paths:
                    if candidate.endswith(basename):
                        graph.add_edge(rel_path, candidate, kind="asset_ref")

    return graph


def get_project_code_graph(repo_root: str | Path = ".") -> dict:
    graph = build_project_graph(repo_root)
    node_records = [{"id": node, "label": node} for node in sorted(graph.nodes())]
    edge_records = [
        {"from": source, "to": target, "label": data.get("kind", "depends_on")}
        for source, target, data in sorted(graph.edges(data=True))
    ]

    out_degrees = sorted(graph.out_degree(), key=lambda item: (-item[1], item[0]))
    in_degrees = sorted(graph.in_degree(), key=lambda item: (-item[1], item[0]))
    isolated = sorted(node for node in graph.nodes() if graph.degree(node) == 0)

    summary_lines = [
        "PROJECT CODE GRAPH",
        f"- Files: {graph.number_of_nodes()}",
        f"- Dependency edges: {graph.number_of_edges()}",
        "- Most connected dependency hubs:",
    ]
    summary_lines.extend(
        f"  - {node}: imported by {degree} files"
        for node, degree in in_degrees[:5]
        if degree > 0
    )
    summary_lines.append("- Files with the broadest outward dependencies:")
    summary_lines.extend(
        f"  - {node}: imports/references {degree} files"
        for node, degree in out_degrees[:5]
        if degree > 0
    )
    if isolated:
        summary_lines.append("- Isolated files:")
        summary_lines.extend(f"  - {node}" for node in isolated[:10])

    adjacency_lines = ["", "FULL FILE LIST:"]
    adjacency_lines.extend(f"- {node}" for node in sorted(graph.nodes()))
    adjacency_lines.append("")
    adjacency_lines.append("FULL DEPENDENCY EDGES:")
    adjacency_lines.extend(
        f"- {edge['from']} -> {edge['to']} ({edge['label']})"
        for edge in edge_records
    )

    review_prompt = "\n".join(summary_lines + adjacency_lines)
    review_prompt += "\n\nReview this project based on the full code graph above. Focus on architecture, coupling hotspots, dead-end files, missing seams, module boundaries, and how to improve maintainability and local inference ergonomics."

    return {
        "nodes": node_records,
        "edges": edge_records,
        "stats": {
            "files": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "top_inbound": in_degrees[:8],
            "top_outbound": out_degrees[:8],
            "isolated": isolated[:20],
        },
        "summary": review_prompt,
        "review_input": review_prompt,
    }
