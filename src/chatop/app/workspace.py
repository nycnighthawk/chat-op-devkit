"""Root-confined file access + the .chatop/ project memory layout."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from chatop.app.config import Config
from chatop.domain.models import State

GITIGNORE = "packets/\nreplies/\nundo/\noutbox.md\ninbox.md\nrecon.md\n"


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.dir = self.root / ".chatop"

    # ---- project files (paths already validated by domain.changes.safe_path)
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"path escapes root: {rel}")
        return p

    def read(self, rel: str) -> str | None:
        try:
            p = self.path(rel)
            return p.read_text(encoding="utf-8") if p.is_file() else None
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def write(self, rel: str, content: str | None) -> None:
        p = self.path(rel)
        if content is None:
            if p.exists():
                p.unlink()
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # ---- .chatop memory
    @property
    def initialised(self) -> bool:
        return (self.dir / "state.json").exists()

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        gi = self.dir / ".gitignore"
        if not gi.exists():
            gi.write_text(GITIGNORE)

    def load_state(self) -> State | None:
        p = self.dir / "state.json"
        return State.from_dict(json.loads(p.read_text())) if p.exists() else None

    def save_state(self, state: State) -> None:
        self.ensure_dir()
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(state.to_dict(), indent=2))
        tmp.replace(self.dir / "state.json")

    def load_config(self) -> Config:
        p = self.dir / "config.toml"
        return Config.from_toml(p.read_text()) if p.exists() else Config()

    def save_config(self, cfg: Config) -> None:
        self.ensure_dir()
        (self.dir / "config.toml").write_text(cfg.to_toml())

    def save_turn_file(self, kind: str, turn: int, text: str) -> Path:
        d = self.dir / kind
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"turn-{turn:04d}.md"
        p.write_text(text, encoding="utf-8")
        return p

    def journal(self, entry: dict[str, Any]) -> None:
        self.ensure_dir()
        with (self.dir / "journal.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}) + "\n")

    def push_undo(self, turn: int, data: dict[str, Any]) -> None:
        d = self.dir / "undo"
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.json")))
        (d / f"{n:05d}-turn-{turn:04d}.json").write_text(json.dumps(data))

    def pop_undo(self) -> dict[str, Any] | None:
        d = self.dir / "undo"
        files = sorted(d.glob("*.json")) if d.exists() else []
        if not files:
            return None
        data: dict[str, Any] = json.loads(files[-1].read_text())
        files[-1].unlink()
        return data
