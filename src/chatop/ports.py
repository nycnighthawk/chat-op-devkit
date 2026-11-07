"""Narrow ports: the ONLY ways the core touches the outside world.

Each adapter implements exactly one Protocol. Swapping a tool (another code-graph CLI, another
clipboard, another VCS) means writing one adapter; nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SymbolHit:
    name: str
    kind: str
    file: str
    line: int | None
    end_line: int | None = None


@dataclass(frozen=True)
class RunResult:
    name: str
    cmd: str
    code: int
    output: str
    seconds: float


class CodeIndex(Protocol):
    """Structural code search. Real adapter: the codegraph CLI."""

    def available(self) -> bool: ...
    def ensure_index(self) -> str: ...
    def status(self) -> str: ...
    def query(self, text: str, limit: int = 10) -> list[SymbolHit]: ...
    def callers(self, symbol: str, limit: int = 20) -> list[SymbolHit]: ...
    def callees(self, symbol: str, limit: int = 20) -> list[SymbolHit]: ...
    def impact(self, symbol: str, depth: int = 2) -> str: ...
    def files(self, max_depth: int = 3) -> str: ...
    def affected(self, files: list[str]) -> list[str]: ...


class Clipboard(Protocol):
    name: str

    def copy(self, text: str) -> bool: ...
    def paste(self) -> str | None: ...


class Runner(Protocol):
    """Runs a configured check command (never a command taken from LLM output)."""

    def run(self, name: str, cmd: str, cwd: Path, timeout: int) -> RunResult: ...


class Vcs(Protocol):
    def is_repo(self) -> bool: ...
    def commit_all(self, message: str) -> str | None: ...
    def tracked_files(self) -> list[str]: ...
    def churn(self, limit: int = 15) -> list[tuple[str, int]]: ...
    def log_summary(self, limit: int = 200) -> str: ...
