import hashlib
import json
import os
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "build"}
LANGUAGE_EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "java", ".rb": "ruby", ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".h": "cpp",
}
PYTHON_FRAMEWORKS = {
    "fastapi": "fastapi", "django": "django", "flask": "flask",
    "torch": "pytorch", "tensorflow": "tensorflow", "transformers": "huggingface",
}
PACKAGE_FRAMEWORKS = {
    "react": "react", "vue": "vue", "next": "nextjs", "express": "express", "svelte": "svelte",
}
DOMAIN_KEYWORDS = [
    ("api", ("api", "endpoint", "rest", "graphql")),
    ("ml", ("machine learning", "ml", "model", "train", "inference")),
    ("security", ("security", "auth", "vulnerability", "pentest")),
    ("frontend", ("frontend", "ui", "component", "css")),
    ("database", ("database", "sql", "migration", "schema")),
    ("infra", ("infra", "deploy", "kubernetes", "docker", "ci/cd")),
    ("ai_agents", ("council", "llm", "agent", "orchestrat")),
]


def _read_text(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:limit] if limit else text
    except Exception:
        return ""


def _detect_languages(root: Path) -> list[str]:
    counts = Counter()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if lang := LANGUAGE_EXTENSIONS.get(ext):
                counts[lang] += 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]]


def _detect_frameworks(root: Path) -> list[str]:
    frameworks = set()
    for filename in ("requirements.txt", "pyproject.toml"):
        if content := _read_text(root / filename).lower():
            frameworks.update(fw for marker, fw in PYTHON_FRAMEWORKS.items() if marker in content)

    if pkg_text := _read_text(root / "package.json"):
        try:
            pkg = json.loads(pkg_text)
            deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
            frameworks.update(fw for marker, fw in PACKAGE_FRAMEWORKS.items() if marker in deps)
        except Exception:
            pass

    for fname, fw in [("go.mod", "go_modules"), ("Cargo.toml", "cargo"), ("pom.xml", "maven"), ("build.gradle", "gradle")]:
        if (root / fname).is_file():
            frameworks.add(fw)
    return sorted(frameworks)


def _detect_domain(root: Path) -> list[str]:
    chunks = []
    if readme := root / "README.md":
        if readme.is_file():
            chunks.append(_read_text(readme, 2000))
    for path in sorted(root.glob("*.md")):
        if path.name != "README.md":
            chunks.append(_read_text(path, 500))

    text = "\n".join(chunks).lower()
    return [tag for tag, keywords in DOMAIN_KEYWORDS if any(kw in text for kw in keywords)]


def fingerprint(root: str = ".") -> dict:
    project_root = Path(root).resolve()
    result = {
        "languages": _detect_languages(project_root),
        "frameworks": _detect_frameworks(project_root),
        "domain": _detect_domain(project_root),
    }
    payload = json.dumps(
        {"languages": sorted(result["languages"]), "frameworks": sorted(result["frameworks"]), "domain": sorted(result["domain"])},
        sort_keys=True,
    )
    result["hash"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return result
