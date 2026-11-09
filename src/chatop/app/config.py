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
    max_parallel: int = 1  # chats worked on at once; 1 = the classic serial flow
    max_attempts: int = 4  # failed attempts before an issue is blocked for a human decision
    max_issues_per_chat: int = 3  # beyond this, open a fresh chat (long chats drift)
    auto_dispatch: bool = True  # hand newly unblocked issues to chats as soon as one finishes
    delta_packets: bool = True  # continuing chats get only what changed
    preflight: dict[str, str] = field(default_factory=dict)  # glob -> linter command ({files}); see domain.preflight

    @classmethod
    def from_toml(cls, text: str) -> Config:
        raw: dict[str, Any] = tomllib.loads(text)
        base = cls()
        known = {k: v for k, v in raw.get("chatop", {}).items() if hasattr(base, k)}
        cfg = cls(**{**base.__dict__, **known})
        cfg.checks = {str(k): str(v) for k, v in raw.get("checks", {}).items()}
        cfg.preflight = {str(k): str(v) for k, v in raw.get("preflight", {}).items()}
        return cfg

    def set_option(self, key: str, value: str) -> None:
        """Set a scalar option from text (CLI / UI). Raises KeyError for unknown keys, ValueError for bad values."""
        current = getattr(self, key, None)
        if key in ("checks", "preflight", "gates", "protected") or not hasattr(self, key):
            raise KeyError(key)
        if isinstance(current, bool):
            new: Any = value.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            new = int(value)
            if new < 1:
                raise ValueError(f"{key} must be >= 1")
        else:
            new = value
        setattr(self, key, new)

    def to_toml(self) -> str:
        def val(v: Any) -> str:
            return json.dumps(v)  # JSON scalars/arrays of strings are valid TOML

        lines = ["# chatop configuration (human-owned).", "[chatop]"]
        for k, v in self.__dict__.items():
            if k not in ("checks", "preflight"):
                lines.append(f"{k} = {val(v).lower() if isinstance(v, bool) else val(v)}")
        lines += ["", "# Commands chatop runs after applying a reply (test, typecheck, lint, ...).", "[checks]"]
        lines += [f"{k} = {val(v)}" for k, v in self.checks.items()]
        if self.preflight:
            lines += [
                "",
                "# Linters run on ALL generated files in one shot before tests ({files} = changed files).",
                "[preflight]",
            ]
            lines += [f"{val(k)} = {val(v)}" for k, v in self.preflight.items()]
        return "\n".join(lines) + "\n"
