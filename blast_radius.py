from pathlib import Path

from logging_utils import get_logger
from project_graph import build_project_graph

logger = get_logger(__name__)

VALID_KINDS = {"import", "import_from", "asset_ref", "depends_on"}


def _reverse_dependencies(graph, changed_file: str) -> set[str]:
    impacted = set()
    stack = [changed_file]
    while stack:
        current = stack.pop()
        if current not in graph:
            continue
        for predecessor in graph.predecessors(current):
            kind = graph.get_edge_data(predecessor, current, default={}).get("kind", "depends_on")
            if kind in VALID_KINDS and predecessor not in impacted:
                impacted.add(predecessor)
                stack.append(predecessor)
    return impacted


def calculate_blast_radius(changed_files: list) -> str:
    if not changed_files:
        return ""

    logger.info("blast_radius_started", extra={"changed_files": changed_files})
    graph = build_project_graph(Path.cwd())
    impacted_files = {imp for cf in changed_files for imp in _reverse_dependencies(graph, cf)}

    if not impacted_files:
        logger.info("blast_radius_completed", extra={"impacted_count": 0})
        return ""

    logger.info("blast_radius_completed", extra={"impacted_count": len(impacted_files)})
    sorted_files = sorted(impacted_files)
    lines = ["\n--- NATIVE ARCHITECTURAL BLAST RADIUS WARNING ---",
             "The following files import or depend on the changed files and may silently break:"]
    lines.extend(f"- {imp}" for imp in sorted_files[:20])
    if len(sorted_files) > 20:
        lines.append(f"...and {len(sorted_files) - 20} more files.")

    return "\n".join(lines) + "\n"
