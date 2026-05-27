import hashlib
import json
from collections import Counter
from pathlib import Path


SKIP_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "build"}
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "java",
    ".rb": "ruby",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
}
PYTHON_FRAMEWORKS = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "torch": "pytorch",
    "tensorflow": "tensorflow",
    "transformers": "huggingface",
}
PACKAGE_FRAMEWORKS = {
    "react": "react",
    "vue": "vue",
    "next": "nextjs",
    "express": "express",
    "svelte": "svelte",
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


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            yield path


def _read_text(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit] if limit else text


def _detect_languages(root: Path) -> list[str]:
    counts = Counter()
    for path in _iter_files(root):
        language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
        if language:
            counts[language] += 1
    return [language for language, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]]


def _detect_python_frameworks(root: Path) -> set[str]:
    frameworks = set()
    for filename in ("requirements.txt", "pyproject.toml"):
        content = _read_text(root / filename).lower()
        if not content:
            continue
        for marker, framework in PYTHON_FRAMEWORKS.items():
            if marker in content:
                frameworks.add(framework)
    return frameworks


def _detect_package_frameworks(root: Path) -> set[str]:
    content = _read_text(root / "package.json")
    if not content:
        return set()
    try:
        package = json.loads(content)
    except Exception:
        return set()

    dependencies = {}
    dependencies.update(package.get("dependencies") or {})
    dependencies.update(package.get("devDependencies") or {})
    return {framework for marker, framework in PACKAGE_FRAMEWORKS.items() if marker in dependencies}


def _detect_frameworks(root: Path) -> list[str]:
    frameworks = set()
    frameworks.update(_detect_python_frameworks(root))
    frameworks.update(_detect_package_frameworks(root))

    root_markers = {
        "go.mod": "go_modules",
        "Cargo.toml": "cargo",
        "pom.xml": "maven",
        "build.gradle": "gradle",
    }
    for filename, framework in root_markers.items():
        if (root / filename).is_file():
            frameworks.add(framework)
    return sorted(frameworks)


def _detect_domain(root: Path) -> list[str]:
    chunks = []
    readme = root / "README.md"
    if readme.is_file():
        chunks.append(_read_text(readme, 2000))
    for path in sorted(root.glob("*.md")):
        if path.name == "README.md":
            continue
        chunks.append(_read_text(path, 500))

    text = "\n".join(chunks).lower()
    return [tag for tag, keywords in DOMAIN_KEYWORDS if any(keyword in text for keyword in keywords)]


def fingerprint(root: str = ".") -> dict:
    project_root = Path(root).resolve()
    result = {
        "languages": _detect_languages(project_root),
        "frameworks": _detect_frameworks(project_root),
        "domain": _detect_domain(project_root),
    }
    payload = json.dumps(
        {
            "languages": sorted(result["languages"]),
            "frameworks": sorted(result["frameworks"]),
            "domain": sorted(result["domain"]),
        },
        sort_keys=True,
    )
    result["hash"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return result
