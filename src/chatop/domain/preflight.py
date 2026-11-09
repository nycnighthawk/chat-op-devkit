"""Preflight: find every syntax problem in every generated file in ONE shot, before anything runs.

Built-in checks are pure (no I/O): Python via ``ast``, JSON, TOML. Project linters (ruff, tsc, gofmt, ...) are
configured per glob in ``[preflight]`` and run by the application layer; their output is parsed here.
"""

from __future__ import annotations

import ast
import json
import re
import shlex
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int | None
    col: int | None
    message: str
    source: str = "syntax"

    def render(self) -> str:
        loc = self.path + (f":{self.line}" if self.line else "") + (f":{self.col}" if self.line and self.col else "")
        return f"{loc}: {self.message}"


def check_syntax(path: str, content: str) -> list[Diagnostic]:
    suffix = PurePosixPath(path).suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(content, filename=path)
        elif suffix == ".json":
            json.loads(content)
        elif suffix == ".toml":
            tomllib.loads(content)
    except SyntaxError as exc:
        return [Diagnostic(path, exc.lineno, exc.offset, f"{type(exc).__name__}: {exc.msg}")]
    except json.JSONDecodeError as exc:
        return [Diagnostic(path, exc.lineno, exc.colno, f"invalid JSON: {exc.msg}")]
    except tomllib.TOMLDecodeError as exc:
        m = re.search(r"line (\d+), column (\d+)", str(exc))
        line, col = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        return [Diagnostic(path, line, col, f"invalid TOML: {exc}")]
    except ValueError as exc:  # e.g. null bytes in source
        return [Diagnostic(path, None, None, f"{type(exc).__name__}: {exc}")]
    return []


def check_all(files: dict[str, str | None]) -> list[Diagnostic]:
    """Every diagnostic for every file (deleted files are None and skipped), sorted by path then line."""
    out: list[Diagnostic] = []
    for path, content in files.items():
        if content is not None:
            out += check_syntax(path, content)
    return sorted(out, key=lambda d: (d.path, d.line or 0))


def select_files(pattern: str, paths: list[str]) -> list[str]:
    return [p for p in paths if fnmatch(p, pattern) or fnmatch(PurePosixPath(p).name, pattern)]


def render_command(template: str, paths: list[str]) -> str:
    quoted = " ".join(shlex.quote(p) for p in paths)
    return template.replace("{files}", quoted) if "{files}" in template else f"{template} {quoted}"


LOC_RE = re.compile(r"^(?P<path>[^\s:][^:]*?):(?P<line>\d+)(?::(?P<col>\d+))?:?\s+(?P<msg>\S.*)$")


def parse_tool_output(output: str, source: str) -> list[Diagnostic]:
    """Parse ``path:line[:col] message`` lines (ruff, gcc, tsc --pretty false, eslint compact, ...)."""
    found = []
    for raw in output.splitlines():
        m = LOC_RE.match(raw.strip())
        if m:
            col = int(m["col"]) if m["col"] else None
            found.append(Diagnostic(m["path"], int(m["line"]), col, m["msg"].strip(), source))
    if found or not output.strip():
        return found
    return [Diagnostic(f"({source})", None, None, " ".join(output.split())[:300], source)]
