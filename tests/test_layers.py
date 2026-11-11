"""The import rules of docs/ARCHITECTURE.md, enforced: a layer may only import what the table allows."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "chatop"

# layer -> chatop packages it may import (stdlib and third-party are always fine, except where noted)
ALLOWED: dict[str, set[str]] = {
    "domain": {"domain"},
    "adapters": {"adapters", "ports"},
    "app": {"app", "domain", "ports"},
    "ui": {"ui", "app", "domain"},
}
EXCEPTIONS = {("app", "adapters"): {"wiring.py"}}  # the composition root may import adapters


def chatop_imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        mods: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module]
        elif isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        for m in mods:
            parts = m.split(".")
            if parts[0] == "chatop":
                out.add(parts[1] if len(parts) > 1 and parts[1] != "ports" else "ports")
                if len(parts) == 2 and parts[1] == "ports":
                    out.add("ports")
    return out


def test_layers_respect_the_import_rule() -> None:
    bad: list[str] = []
    for layer, ok in ALLOWED.items():
        for path in sorted((SRC / layer).glob("*.py")):
            for imp in chatop_imports(path):
                if imp not in ok and path.name not in EXCEPTIONS.get((layer, imp), set()):
                    bad.append(f"{layer}/{path.name} imports chatop.{imp}")
    assert not bad, "\n".join(bad)


def test_ports_import_nothing_from_chatop() -> None:
    assert chatop_imports(SRC / "ports.py") <= {"ports"}
