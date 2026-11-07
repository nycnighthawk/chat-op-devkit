"""Per-project configuration: .chatop/config.toml (human-owned; the LLM can only *propose* checks)."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PROTECTED = [".git/**", ".git", ".chatop/**", ".codegraph/**", ".env", ".env.*", "**/*.pem", "**/id_rsa*"]


@dataclass
class Config:
    checks: dict[str, str] = field(default_factory=dict)  # name -> shell command, e.g. test = "pytest -q"
    budget_tokens: int = 80_000
    max_refine_rounds: int = 3
    max_questions: int = 6
    gates: list[str] = field(default_factory=lambda: ["prd", "spec", "delta", "plan", "audit"])
    protected: list[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED))
    tdd_strict: bool = True
    auto_commit: bool = True
    auto_next: bool = True
    codegraph_bin: str = "codegraph"
    check_timeout: int = 900
    max_file_lines: int = 400

    @classmethod
    def from_toml(cls, text: str) -> Config:
        raw: dict[str, Any] = tomllib.loads(text)
        base = cls()
        known = {k: v for k, v in raw.get("chatop", {}).items() if hasattr(base, k)}
        cfg = cls(**{**base.__dict__, **known})
        cfg.checks = {str(k): str(v) for k, v in raw.get("checks", {}).items()}
        return cfg

    def to_toml(self) -> str:
        def val(v: Any) -> str:
            return json.dumps(v)  # JSON scalars/arrays of strings are valid TOML

        lines = ["# chatop configuration (human-owned).", "[chatop]"]
        for k, v in self.__dict__.items():
            if k != "checks":
                lines.append(f"{k} = {val(v).lower() if isinstance(v, bool) else val(v)}")
        lines += ["", "# Commands chatop runs after applying a reply (test, typecheck, lint, ...).", "[checks]"]
        lines += [f"{k} = {val(v)}" for k, v in self.checks.items()]
        return "\n".join(lines) + "\n"
