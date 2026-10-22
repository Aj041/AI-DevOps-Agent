from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

IMPORTANT_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "pom.xml", "Dockerfile",
    ".env", ".env.example", "README.md", "go.mod", "Cargo.toml",
}
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".dist", "dist", "build"}


def _walk(root: Path) -> list[str]:
    files: list[str] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(names):
            files.append(str(Path(current, name).relative_to(root)).replace("\\", "/"))
    return files


def _detect(files: list[str], root: Path) -> tuple[str, str]:
    names = {Path(f).name for f in files}
    if "package.json" in names:
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            if "next" in deps: return "JavaScript/TypeScript", "Next.js"
            if "react" in deps: return "JavaScript/TypeScript", "React"
            if "vue" in deps: return "JavaScript/TypeScript", "Vue"
        except (OSError, json.JSONDecodeError):
            pass
        return "JavaScript/TypeScript", "Node.js"
    if "pom.xml" in names: return "Java", "Maven"
    if "requirements.txt" in names or "pyproject.toml" in names:
        return "Python", "Python package"
    if "go.mod" in names: return "Go", "Go modules"
    if "Cargo.toml" in names: return "Rust", "Cargo"
    return "Unknown", "Unknown"


def analyze_repository(path: str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Repository path must be an existing directory")
    files = _walk(root)
    important = {name: any(Path(f).name == name for f in files) for name in IMPORTANT_FILES}
    workflows = [f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
    language, framework = _detect(files, root)
    return {
        "path": str(root), "name": root.name, "file_count": len(files), "files": files[:500],
        "important_files": important, "workflows": workflows, "language": language,
        "framework": framework, "has_git": (root / ".git").is_dir(),
    }
