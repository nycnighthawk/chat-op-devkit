"""Codegraph adapter: command lines it issues and schema-tolerant parsing of --json output."""

import json
from pathlib import Path

from chatop.adapters.codegraph import CodegraphIndex, normalise_hits


def test_normalise_various_shapes() -> None:
    a = normalise_hits([{"name": "add", "kind": "function", "filePath": "src/c.py", "startLine": 3, "endLine": 5}])
    b = normalise_hits({"results": [{"symbol": "add", "type": "function", "file": "src/c.py", "line": 3}]})
    c = normalise_hits({"callers": [{"node": {"name": "main", "kind": "function", "path": "m.py", "start_line": 9}}]})
    assert (a[0].name, a[0].file, a[0].line, a[0].end_line) == ("add", "src/c.py", 3, 5)
    assert (b[0].name, b[0].kind, b[0].line, b[0].end_line) == ("add", "function", 3, None)
    assert (c[0].name, c[0].file, c[0].line) == ("main", "m.py", 9)
    assert normalise_hits("garbage") == []


class Recorder:
    def __init__(self, out: str, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.out, self.code = out, code

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        return self.code, self.out


def test_query_issues_json_command(tmp_path: Path) -> None:
    rec = Recorder(json.dumps([{"name": "add", "kind": "function", "file": "c.py", "line": 1}]))
    idx = CodegraphIndex(tmp_path, exec_fn=rec)
    hits = idx.query("add", limit=5)
    assert rec.calls[0] == ["codegraph", "query", "add", "--limit", "5", "--json"]
    assert hits[0].name == "add"


def test_ensure_index_init_then_sync(tmp_path: Path) -> None:
    rec = Recorder("ok")
    idx = CodegraphIndex(tmp_path, exec_fn=rec)
    idx.ensure_index()
    (tmp_path / ".codegraph").mkdir()
    idx.ensure_index()
    assert rec.calls[0][:3] == ["codegraph", "init", "-i"]
    assert rec.calls[1][:2] == ["codegraph", "sync"]


def test_affected_quiet_lines(tmp_path: Path) -> None:
    rec = Recorder("tests/test_a.py\ntests/test_b.py\n")
    idx = CodegraphIndex(tmp_path, exec_fn=rec)
    assert idx.affected(["src/a.py"]) == ["tests/test_a.py", "tests/test_b.py"]
    assert rec.calls[0] == ["codegraph", "affected", "src/a.py", "--quiet"]


def test_failure_degrades_gracefully(tmp_path: Path) -> None:
    idx = CodegraphIndex(tmp_path, exec_fn=Recorder("boom", code=2))
    assert idx.query("x") == []
    assert "boom" in idx.impact("x")
