import os
import ast
import re
from pathlib import Path
import networkx as nx

def calculate_blast_radius(changed_files: list) -> str:
    if not changed_files:
        return ""

    print("\n[🔌 Native Engine] Calculating Architectural Blast Radius...")
    
    G = nx.DiGraph()
    repo_root = Path.cwd()
    
    # Exclude directories
    excludes = {'.git', '__pycache__', 'node_modules', 'venv', '.env', 'env'}
    
    # 1. Build Dependency Graph
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in excludes]
        
        for file in files:
            file_path = Path(root) / file
            
            # Make path relative to repo root
            rel_path = str(file_path.relative_to(repo_root))
            
            # Python AST parsing
            if file.endswith('.py'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for name in node.names:
                                imported_module = name.name.replace('.', '/') + '.py'
                                G.add_edge(rel_path, imported_module)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imported_module = node.module.replace('.', '/') + '.py'
                                G.add_edge(rel_path, imported_module)
                except Exception:
                    pass
            
            # Fallback Text Parsing for other files (JS, TS, HTML)
            elif file.endswith(('.js', '.ts', '.html', '.css')):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Very simple regex to find filenames in quotes
                    matches = re.findall(r'[\'"]([^\'"]+\.(?:py|js|ts|html|css))[\'"]', content)
                    for match in matches:
                        # Extract just the filename to be safe
                        base_match = os.path.basename(match)
                        for candidate in G.nodes:
                            if candidate.endswith(base_match):
                                G.add_edge(rel_path, candidate)
                except Exception:
                    pass

    # 2. Calculate Blast Radius
    impacted_files = set()
    for changed_file in changed_files:
        if changed_file in G:
            # Find all files that depend on the changed file (Reverse path)
            try:
                # Get ancestors (files that import this file)
                ancestors = nx.ancestors(G, changed_file)
                impacted_files.update(ancestors)
            except nx.NetworkXError:
                pass
                
    if not impacted_files:
        print("[✅ Native Engine] Blast Radius calculated. No major downstream dependencies detected.")
        return ""
        
    print(f"[✅ Native Engine] Blast Radius calculated. Found {len(impacted_files)} impacted files.")
    
    result = "\n--- NATIVE ARCHITECTURAL BLAST RADIUS WARNING ---\n"
    result += f"The following files import or depend on the changed files and may silently break:\n"
    for imp in sorted(list(impacted_files))[:20]: # Limit to 20 to save context window
        result += f"- {imp}\n"
    
    if len(impacted_files) > 20:
        result += f"...and {len(impacted_files) - 20} more files.\n"
        
    return result
