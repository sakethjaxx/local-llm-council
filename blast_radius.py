from pathlib import Path

from logging_utils import get_logger
from project_graph import build_project_graph


logger = get_logger(__name__)


def _reverse_dependencies(graph, changed_file: str) -> set[str]:
    impacted = set()
    stack = [changed_file]
    while stack:
        current = stack.pop()
        if current not in graph:
            continue
        for predecessor in graph.predecessors(current):
            kind = graph.get_edge_data(predecessor, current, default={}).get("kind", "depends_on")
            if kind in {"import", "import_from", "asset_ref", "depends_on"} and predecessor not in impacted:
                impacted.add(predecessor)
                stack.append(predecessor)
    return impacted


def calculate_blast_radius(changed_files: list) -> str:
    if not changed_files:
        return ""

    logger.info("blast_radius_started", extra={"changed_files": changed_files})

    graph = build_project_graph(Path.cwd())
    impacted_files = set()
    for changed_file in changed_files:
        impacted_files.update(_reverse_dependencies(graph, changed_file))

    if not impacted_files:
        logger.info("blast_radius_completed", extra={"impacted_count": 0})
        return ""

    logger.info("blast_radius_completed", extra={"impacted_count": len(impacted_files)})

    result = "\n--- NATIVE ARCHITECTURAL BLAST RADIUS WARNING ---\n"
    result += "The following files import or depend on the changed files and may silently break:\n"
    for imp in sorted(list(impacted_files))[:20]:
        result += f"- {imp}\n"

    if len(impacted_files) > 20:
        result += f"...and {len(impacted_files) - 20} more files.\n"

    return result
