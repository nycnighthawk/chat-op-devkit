"""Composition root: the only place that knows which concrete adapters exist."""

from __future__ import annotations

from pathlib import Path

from chatop.adapters.clipboard import detect_clipboard
from chatop.adapters.codegraph import CodegraphIndex
from chatop.adapters.git import GitVcs
from chatop.adapters.runner import ShellRunner
from chatop.app.session import Session
from chatop.app.workspace import Workspace


def build_session(root: Path | str = ".") -> Session:
    ws = Workspace(Path(root))
    cfg = ws.load_config()
    return Session(
        ws,
        CodegraphIndex(ws.root, binary=cfg.codegraph_bin),
        detect_clipboard(ws.dir),
        ShellRunner(),
        GitVcs(ws.root),
    )
