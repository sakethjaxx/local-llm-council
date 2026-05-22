from pathlib import Path

from project_graph import build_project_graph


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

    print("\n[🔌 Native Engine] Calculating Architectural Blast Radius...")

    graph = build_project_graph(Path.cwd())
    impacted_files = set()
    for changed_file in changed_files:
        impacted_files.update(_reverse_dependencies(graph, changed_file))

    if not impacted_files:
        print("[✅ Native Engine] Blast Radius calculated. No major downstream dependencies detected.")
        return ""

    print(f"[✅ Native Engine] Blast Radius calculated. Found {len(impacted_files)} impacted files.")

    result = "\n--- NATIVE ARCHITECTURAL BLAST RADIUS WARNING ---\n"
    result += "The following files import or depend on the changed files and may silently break:\n"
    for imp in sorted(list(impacted_files))[:20]:
        result += f"- {imp}\n"

    if len(impacted_files) > 20:
        result += f"...and {len(impacted_files) - 20} more files.\n"

    return result
