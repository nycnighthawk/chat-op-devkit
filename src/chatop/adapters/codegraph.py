"""Adapter for the @colbymchenry/codegraph CLI (npm). All code search goes through here.

Commands used: init -i, sync, status, query, callers, callees, impact, files, affected.
JSON shapes are not formally documented, so parsing is deliberately schema-tolerant.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chatop.ports import SymbolHit

ExecFn = Callable[[list[str]], tuple[int, str]]

NAME_KEYS = ("name", "symbol", "qualifiedName", "qualified_name", "label")
KIND_KEYS = ("kind", "type", "nodeType")
FILE_KEYS = ("file", "filePath", "file_path", "path", "filepath")
LINE_KEYS = ("line", "startLine", "start_line", "lineStart", "line_start")
END_KEYS = ("endLine", "end_line", "lineEnd", "line_end")


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalise_hits(data: Any) -> list[SymbolHit]:
    """Walk any JSON structure and collect objects that look like symbol locations."""
    out: list[SymbolHit] = []
    seen: set[tuple[str, str, int | None]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            name, file = _first(node, NAME_KEYS), _first(node, FILE_KEYS)
            if isinstance(name, str) and isinstance(file, str):
                hit = SymbolHit(
                    name=name,
                    kind=str(_first(node, KIND_KEYS) or "symbol"),
                    file=file,
                    line=_as_int(_first(node, LINE_KEYS)),
                    end_line=_as_int(_first(node, END_KEYS)),
                )
                key = (hit.name, hit.file, hit.line)
                if key not in seen:
                    seen.add(key)
                    out.append(hit)
                return
            for v in node.values():
                walk(v)

    walk(data)
    return out


class CodegraphIndex:
    def __init__(self, root: Path, binary: str = "codegraph", exec_fn: ExecFn | None = None, timeout: int = 300):
        self.root, self.binary, self.timeout = root, binary, timeout
        self._exec = exec_fn or self._subprocess

    def _subprocess(self, args: list[str]) -> tuple[int, str]:
        try:
            p = subprocess.run(args, cwd=self.root, capture_output=True, text=True, timeout=self.timeout)
            return p.returncode, (p.stdout or "") + (p.stderr if p.returncode else "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)

    def _run(self, *args: str) -> tuple[int, str]:
        return self._exec([self.binary, *args])

    def _json(self, *args: str) -> list[SymbolHit]:
        code, out = self._run(*args, "--json")
        if code != 0:
            return []
        try:
            return normalise_hits(json.loads(out))
        except json.JSONDecodeError:
            return []

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def ensure_index(self) -> str:
        if (self.root / ".codegraph").exists():
            return self._run("sync", str(self.root))[1]
        return self._run("init", "-i", str(self.root))[1]

    def status(self) -> str:
        return self._run("status", str(self.root))[1].strip()

    def query(self, text: str, limit: int = 10) -> list[SymbolHit]:
        return self._json("query", text, "--limit", str(limit))

    def callers(self, symbol: str, limit: int = 20) -> list[SymbolHit]:
        return self._json("callers", symbol, "--limit", str(limit))

    def callees(self, symbol: str, limit: int = 20) -> list[SymbolHit]:
        return self._json("callees", symbol, "--limit", str(limit))

    def impact(self, symbol: str, depth: int = 2) -> str:
        code, out = self._run("impact", symbol, "--depth", str(depth), "--json")
        if code != 0:
            return f"(codegraph impact failed: {out.strip()[:300]})"
        try:
            hits = normalise_hits(json.loads(out))
        except json.JSONDecodeError:
            return out.strip()
        files = sorted({h.file for h in hits})
        lines = [f"{len(hits)} affected symbols in {len(files)} files"]
        lines += [f"- {h.file}:{h.line or '?'} {h.kind} {h.name}" for h in hits[:60]]
        return "\n".join(lines)

    def files(self, max_depth: int = 3) -> str:
        code, out = self._run("files", "--max-depth", str(max_depth))
        return out.strip() if code == 0 else ""

    def affected(self, files: list[str]) -> list[str]:
        if not files:
            return []
        code, out = self._run("affected", *files, "--quiet")
        return [ln.strip() for ln in out.splitlines() if ln.strip()] if code == 0 else []
