"""In-memory test doubles for the narrow ports. Contract: same Protocols as the real adapters."""

from __future__ import annotations

from chatop.ports import SymbolHit


class FakeIndex:
    def __init__(self, hits: dict[str, list[SymbolHit]] | None = None) -> None:
        self.hits = hits or {}
        self.synced = 0

    def available(self) -> bool:
        return True

    def ensure_index(self) -> str:
        self.synced += 1
        return "indexed"

    def status(self) -> str:
        return "fake index: ok"

    def query(self, text: str, limit: int = 10) -> list[SymbolHit]:
        return self.hits.get(text, [])[:limit]

    def callers(self, symbol: str, limit: int = 20) -> list[SymbolHit]:
        return self.hits.get("callers:" + symbol, [])[:limit]

    def callees(self, symbol: str, limit: int = 20) -> list[SymbolHit]:
        return self.hits.get("callees:" + symbol, [])[:limit]

    def impact(self, symbol: str, depth: int = 2) -> str:
        return f"impact of {symbol}: 2 files"

    def files(self, max_depth: int = 3) -> str:
        return "src/\n  calc.py"

    def affected(self, files: list[str]) -> list[str]:
        return ["tests/test_calc.py"] if files else []


class FakeClipboard:
    name = "fake"

    def __init__(self) -> None:
        self.text: str | None = None

    def copy(self, text: str) -> bool:
        self.text = text
        return True

    def paste(self) -> str | None:
        return self.text
