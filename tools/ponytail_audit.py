import os
import ast

MAX_LINES_THRESHOLD = 500
COMPLEXITY_THRESHOLD = 15

def get_cyclomatic_complexity(node):
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp, ast.For, ast.While, ast.And, ast.Or, ast.ExceptHandler)):
            complexity += 1
    return complexity

def audit_file(filepath):
    issues = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            content = f.read()
        except UnicodeDecodeError:
            return issues
            
    lines = content.splitlines()
    if len(lines) > MAX_LINES_THRESHOLD:
        issues.append(f"BLOAT: File has {len(lines)} lines (Threshold: {MAX_LINES_THRESHOLD})")
        
    if filepath.endswith('.py'):
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    c = get_cyclomatic_complexity(node)
                    if c > COMPLEXITY_THRESHOLD:
                        issues.append(f"COMPLEXITY: {node.name} has cyclomatic complexity of {c} (Threshold: {COMPLEXITY_THRESHOLD})")
        except SyntaxError:
            pass
            
    return issues

def main():
    print("🐴 Starting Ponytail Engineering Audit...")
    print(f"Max Lines: {MAX_LINES_THRESHOLD} | Max Complexity: {COMPLEXITY_THRESHOLD}\n")
    
    total_issues = 0
    for root, dirs, files in os.walk('.'):
        if any(ignore in root for ignore in ['.git', 'venv', '__pycache__', 'node_modules', '.agents', '.gemini']):
            continue
            
        for file in files:
            if not file.endswith(('.py', '.js', '.html', '.css')):
                continue
                
            filepath = os.path.join(root, file)
            issues = audit_file(filepath)
            
            if issues:
                print(f"--- {filepath} ---")
                for issue in issues:
                    print(f"  [!] {issue}")
                    total_issues += 1
                    
    print("\nAudit Complete.")
    if total_issues == 0:
        print("✅ The codebase adheres to the Ponytail Engineering standard! Zero bloat detected.")
    else:
        print(f"❌ Found {total_issues} violations of the Ponytail Engineering standard. Consider refactoring.")

if __name__ == '__main__':
    main()
