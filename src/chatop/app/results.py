"""Value objects returned by the Session facade (shared by the serial flow and the lane engine)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chatop.ports import RunResult


class SessionError(Exception):
    pass


@dataclass
class PacketResult:
    turn: int
    text: str
    tokens: int
    notes: list[str]
    path: Path
    copied: bool
    chat: str | None = None  # parallel mode: the chat window this packet is for
    kind: str = "full"  # "full" (bootstrap) or "delta" (continuation: only what changed)
    full_tokens: int = 0  # what a full packet would have cost (0 = same as tokens)


@dataclass
class ApplyResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    checks: list[RunResult] = field(default_factory=list)
    red_ok: bool | None = None
    slice_done: bool = False
    messages: list[str] = field(default_factory=list)
    repair_prompt: str | None = None
    next_packet: PacketResult | None = None
    status: str = ""
    chat: str | None = None  # parallel mode: the chat the reply was routed to
