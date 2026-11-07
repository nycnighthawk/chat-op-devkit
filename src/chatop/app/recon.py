"""Local, LLM-free reconnaissance of an unknown repository (cheap facts first, tokens later)."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from chatop.app.workspace import Workspace
from chatop.domain.reply import infer_role
from chatop.ports import CodeIndex, Vcs

AGENT_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".github/copilot-instructions.md",
    "CONVENTIONS.md",
    ".aider.conf.yml",
    "README.md",
]
AGENT_DIRS = [".cursor/rules", ".claude/commands", ".github/instructions", ".kiro/steering", ".clinerules"]
AGENT_MARKERS = {
    "claude": r"co-authored-by: claude|claude code|anthropic",
    "aider": r"\baider\b",
    "cursor": r"\bcursor\b",
    "copilot": r"copilot",
    "codex": r"\bcodex\b",
    "devin": r"\bdevin\b",
    "gemini": r"\bgemini\b",
    "openhands": r"openhands",
    "chatgpt": r"chatgpt|gpt-\d",
}
MANIFESTS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "package.json": "node",
    "tsconfig.json": "typescript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "jvm",
    "build.gradle.kts": "kotlin",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Makefile": "make",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".chatop",
    ".codegraph",
    "target",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".next",
    "coverage",
}
SOURCE_EXT = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".scala",
    ".dart",
    ".vue",
    ".svelte",
    ".lua",
}


def list_files(ws: Workspace, vcs: Vcs) -> list[str]:
    files = vcs.tracked_files() if vcs.is_repo() else []
    if files:
        return [f for f in files if not any(part in SKIP_DIRS for part in Path(f).parts)]
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ws.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(ws.root)
        out += [str(rel / f) if str(rel) != "." else f for f in filenames]
    return sorted(out)


def source_files(files: list[str]) -> list[str]:
    return [f for f in files if Path(f).suffix in SOURCE_EXT]


def detect_checks(ws: Workspace, files: list[str]) -> dict[str, str]:
    checks: dict[str, str] = {}
    names = set(files)
    has_tests = any(infer_role(f) == "test" for f in files)
    if {"pyproject.toml", "setup.py", "requirements.txt"} & names:
        py = ws.read("pyproject.toml") or ""
        if has_tests or "pytest" in py:
            checks["test"] = "python -m pytest -q"
        if "mypy" in py:
            checks["typecheck"] = "python -m mypy ."
        if "ruff" in py:
            checks["lint"] = "ruff check ."
    if "package.json" in names:
        try:
            scripts = json.loads(ws.read("package.json") or "{}").get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        if "test" in scripts:
            checks.setdefault("test", "npm test --silent")
        if "typecheck" in scripts:
            checks.setdefault("typecheck", "npm run -s typecheck")
        elif "tsconfig.json" in names:
            checks.setdefault("typecheck", "npx tsc --noEmit")
        if "lint" in scripts:
            checks.setdefault("lint", "npm run -s lint")
    if "go.mod" in names:
        checks.setdefault("test", "go test ./...")
        checks.setdefault("lint", "go vet ./...")
    if "Cargo.toml" in names:
        checks.setdefault("test", "cargo test -q")
        checks.setdefault("lint", "cargo clippy -q")
    return checks


def line_count(ws: Workspace, rel: str) -> int:
    try:
        with ws.path(rel).open("rb") as fh:
            return sum(1 for _ in fh)
    except (OSError, ValueError):
        return 0


def build_recon(ws: Workspace, vcs: Vcs, index: CodeIndex) -> tuple[str, str]:
    """Return (report_markdown, agent_instruction_files_markdown)."""
    files = list_files(ws, vcs)
    src = source_files(files)
    tests = [f for f in src if infer_role(f) == "test"]
    exts = Counter(Path(f).suffix for f in src)
    manifests = sorted({f for f in files if Path(f).name in MANIFESTS and f.count("/") <= 1})
    sizes = sorted(((line_count(ws, f), f) for f in src[:3000]), reverse=True)
    size_of = {f: n for n, f in sizes}
    churn = vcs.churn(40) if vcs.is_repo() else []
    hotspots = sorted(((c * max(size_of.get(f, 0), 1), f, c) for f, c in churn if f in size_of), reverse=True)[:15]
    log = vcs.log_summary(400) if vcs.is_repo() else ""
    markers = {k: len(re.findall(p, log, re.I)) for k, p in AGENT_MARKERS.items()}
    commits = len(re.findall(r"^[0-9a-f]{7,} \d{4}-", log, re.M))

    r = [
        "### Inventory",
        f"- files: {len(files)}, source files: {len(src)}, test files: {len(tests)} "
        f"(test/source ratio {len(tests) / max(len(src) - len(tests), 1):.2f})",
        "- languages (by extension): " + ", ".join(f"{e or '?'}={n}" for e, n in exts.most_common(8)),
        "- manifests: " + (", ".join(f"{m} ({MANIFESTS[Path(m).name]})" for m in manifests) or "none"),
        f"- detected checks: {json.dumps(detect_checks(ws, files))}",
        "",
        "### Git history",
        f"- commits scanned: {commits}",
        "- agent fingerprints in commit messages: "
        + (", ".join(f"{k}={v}" for k, v in markers.items() if v) or "none found"),
        "",
        "### Largest source files (lines)",
    ]
    r += [f"- {f}: {n}" for n, f in sizes[:10]]
    r += ["", "### Hotspots (churn x size; test coverage of these matters most)"]
    r += [f"- {f}: {c} commits x {size_of.get(f, 0)} lines" for _, f, c in hotspots] or ["- (no git history)"]
    found_dirs = [d for d in AGENT_DIRS if (ws.root / d).is_dir()]
    r += ["", "### Agent instruction locations", "- dirs: " + (", ".join(found_dirs) or "none")]
    r += ["", "### Code graph", f"- codegraph: {index.status() if index.available() else 'NOT AVAILABLE'}"]
    tree = index.files(3) if index.available() else ""
    r += ["", "### Repo map (codegraph files)", "```", tree or "\n".join(files[:200]), "```"]

    agent_md: list[str] = []
    for name in AGENT_FILES:
        text = ws.read(name)
        if text:
            agent_md.append(f"#### {name}\n{fence(text[:12000])}")
    for d in found_dirs:
        for p in sorted((ws.root / d).glob("*"))[:10]:
            if p.is_file():
                rel = str(p.relative_to(ws.root))
                agent_md.append(f"#### {rel}\n{fence((ws.read(rel) or '')[:6000])}")
    return "\n".join(r), "\n\n".join(agent_md)


def fence(text: str, lang: str = "") -> str:
    longest = max((len(m) for m in re.findall(r"`{3,}", text)), default=2)
    f = "`" * max(3, longest + 1)
    return f"{f}{lang}\n{text.rstrip()}\n{f}"
