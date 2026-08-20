import ast
import os
import re
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".env", "env",
    ".venv", "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".idea", ".vscode",
}

# Anything the council can meaningfully read. Kept broad on purpose: a mixed
# TS/Python/Go repo used to lose every file that was not one of five suffixes,
# which made project review look like it ingested nothing.
SOURCE_SUFFIXES = (
    # python / notebooks
    ".py", ".pyi",
    # web + typescript
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".html", ".css", ".scss", ".sass", ".less",
    # other mainstream languages
    ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".scala", ".ex", ".exs",
    # shell + query
    ".sh", ".bash", ".zsh", ".sql",
    # config + docs that carry real architectural signal
    ".md", ".json", ".yaml", ".yml", ".toml",
)

# Suffixes whose intra-file references are resolved with a regex fallback.
_REF_SUFFIX_GROUP = "py|pyi|js|jsx|mjs|cjs|ts|tsx|vue|svelte|html|css|scss|go|rs|java|rb|php|sql|md|json|yaml|yml|toml"


class ProjectGraph:
    """Lightweight native Directed Graph replacing NetworkX dependency."""

    def __init__(self):
        self._nodes = set()
        self._succ = {}
        self._pred = {}

    def add_node(self, node: str):
        self._nodes.add(node)
        self._succ.setdefault(node, {})
        self._pred.setdefault(node, {})

    def add_edge(self, u: str, v: str, **kwargs):
        self.add_node(u)
        self.add_node(v)
        self._succ[u][v] = kwargs
        self._pred[v][u] = kwargs

    def predecessors(self, node: str):
        return list(self._pred.get(node, {}).keys())

    def get_edge_data(self, u: str, v: str, default=None):
        return self._succ.get(u, {}).get(v, default)

    def nodes(self):
        return list(self._nodes)

    def edges(self, data: bool = False):
        if data:
            return [(u, v, d) for u, succs in self._succ.items() for v, d in succs.items()]
        return [(u, v) for u, succs in self._succ.items() for v in succs]

    def in_degree(self, node=None):
        if node is not None:
            return len(self._pred.get(node, {}))
        return [(n, len(self._pred.get(n, {}))) for n in self._nodes]

    def out_degree(self, node=None):
        if node is not None:
            return len(self._succ.get(node, {}))
        return [(n, len(self._succ.get(n, {}))) for n in self._nodes]

    def degree(self, node: str):
        return len(self._pred.get(node, {})) + len(self._succ.get(node, {}))

    def number_of_nodes(self):
        return len(self._nodes)

    def number_of_edges(self):
        return sum(len(s) for s in self._succ.values())

    def __contains__(self, node: str):
        return node in self._nodes


MAX_GRAPH_FILES = 4000


def _iter_source_files(repo_root: Path):
    count = 0
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS and not (d.startswith(".") and d != ".")
        ]
        for filename in files:
            path = Path(root) / filename
            if path.suffix in SOURCE_SUFFIXES:
                yield path
                count += 1
                if count >= MAX_GRAPH_FILES:
                    return


def _relative_module_path(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


_EXPLICIT_REF_RE = re.compile(rf"""['"]([^'"\n]+\.(?:{_REF_SUFFIX_GROUP}))['"]""")
# `import x from './lib/foo'`, `require('../db')`, `from "@/lib/bar"` — extensionless.
_MODULE_REF_RE = re.compile(r"""(?:from|require|import)\s*\(?\s*['"]([./@][^'"\n]+)['"]""")

# Extensions tried, in order, when a JS/TS import omits one.
_IMPLICIT_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")


def _iter_text_references(content: str):
    for match in _EXPLICIT_REF_RE.findall(content):
        yield match
    for match in _MODULE_REF_RE.findall(content):
        yield match


def _resolve_reference(ref: str, from_rel: str, known_rel_paths: set[str]):
    """Map a raw import/asset string onto real files in the graph.

    Relative specifiers resolve against the importing file's directory so that
    `./db` in `server/index.js` hits `server/db.js` and not some unrelated
    `db.js` elsewhere in the tree. Bare or aliased specifiers fall back to a
    basename match, which is looser but still better than dropping the edge.
    """
    ref = ref.strip()
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return

    if ref.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(from_rel), ref))
        candidates = [base] + [base + ext for ext in _IMPLICIT_EXTS]
        candidates += [os.path.join(base, "index" + ext) for ext in _IMPLICIT_EXTS]
        for candidate in candidates:
            normalized = candidate.replace(os.sep, "/")
            if normalized in known_rel_paths and normalized != from_rel:
                yield normalized
                return
        return

    basename = os.path.basename(ref)
    if not basename:
        return
    stems = [basename] if "." in basename else [basename + ext for ext in _IMPLICIT_EXTS]
    for candidate in known_rel_paths:
        if candidate == from_rel:
            continue
        if any(candidate.endswith("/" + stem) or candidate == stem for stem in stems):
            yield candidate


def _resolve_python_import(module_name: str | None, from_rel: str, known_rel_paths: set[str], level: int = 0) -> str | None:
    if not module_name and level == 0:
        return None

    rel_mod = _relative_module_path(module_name) if module_name else ""
    from_dir = os.path.dirname(from_rel)

    # 1. Relative import resolution (level > 0, e.g. "from .foo import ...")
    if level > 0:
        target_dir = from_dir
        for _ in range(level - 1):
            target_dir = os.path.dirname(target_dir)
        if rel_mod:
            candidate = os.path.normpath(os.path.join(target_dir, rel_mod)).replace(os.sep, "/")
            if candidate in known_rel_paths:
                return candidate
        else:
            candidate = os.path.normpath(os.path.join(target_dir, "__init__.py")).replace(os.sep, "/")
            if candidate in known_rel_paths:
                return candidate

    # 2. Direct root match (e.g. "council/orchestrator.py")
    if rel_mod and rel_mod in known_rel_paths:
        return rel_mod

    # 3. Package __init__.py match (e.g. "council" -> "council/__init__.py")
    if module_name:
        init_candidate = module_name.replace(".", "/") + "/__init__.py"
        if init_candidate in known_rel_paths:
            return init_candidate

    # 4. Sibling/same-package match (e.g. "from orchestrator import ..." inside src/council/)
    if from_dir and rel_mod:
        candidate = os.path.normpath(os.path.join(from_dir, rel_mod)).replace(os.sep, "/")
        if candidate in known_rel_paths:
            return candidate

    # 5. Suffix-match fallback across known paths (e.g. "src/council/orchestrator.py" matches "council/orchestrator.py" or "orchestrator.py")
    if rel_mod:
        for known in known_rel_paths:
            if known == rel_mod or known.endswith("/" + rel_mod):
                return known

    if module_name:
        init_candidate = module_name.replace(".", "/") + "/__init__.py"
        for known in known_rel_paths:
            if known == init_candidate or known.endswith("/" + init_candidate):
                return known

    return None


def build_project_graph(repo_root: str | Path = ".") -> ProjectGraph:
    root = Path(repo_root).resolve()
    graph = ProjectGraph()

    source_files = list(_iter_source_files(root))
    rel_paths = {path: str(path.relative_to(root)).replace(os.sep, "/") for path in source_files}
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
                        target = _resolve_python_import(name.name, rel_path, known_rel_paths, level=0)
                        if target and target != rel_path:
                            graph.add_edge(rel_path, target, kind="import")
                elif isinstance(node, ast.ImportFrom):
                    target = _resolve_python_import(node.module, rel_path, known_rel_paths, level=getattr(node, "level", 0))
                    if target and target != rel_path:
                        graph.add_edge(rel_path, target, kind="import_from")
        else:
            for ref in _iter_text_references(content):
                for candidate in _resolve_reference(ref, rel_path, known_rel_paths):
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
