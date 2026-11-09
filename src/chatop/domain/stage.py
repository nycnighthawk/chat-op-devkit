"""Relay stages: for each chat, who has to act next. Pure and shared by the CLI, TUI, web page and the mock."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from chatop.domain.models import ChatStatus


class Stage(StrEnum):
    SEND = "send"  # chatop has the next packet; the human must copy it
    PASTE = "paste"  # packet copied; the human must paste it into the chat, then flag it as pasted
    FIX = "fix"  # the last reply was rejected; the human must send the repair prompt
    ANSWER = "answer"  # the LLM asked questions
    BLOCKED = "blocked"  # attempts exhausted: a human decision
    WAITING = "waiting"  # flagged as pasted: the LLM is writing
    APPLYING = "applying"  # chatop is applying the reply and running checks
    CLOSED = "closed"  # the issue is done; the chat is free (and keeps its context)


class Owner(StrEnum):
    YOU = "you"
    LLM = "llm"
    CHATOP = "chatop"
    NOBODY = "nobody"


def stage_of(status: ChatStatus, sent_at: float | None, repair: str) -> Stage:
    if status in (ChatStatus.QUEUED, ChatStatus.READY):
        return Stage.SEND
    if status == ChatStatus.AWAITING_REPLY:
        if sent_at is not None:
            return Stage.WAITING
        return Stage.FIX if repair else Stage.PASTE
    return {
        ChatStatus.APPLYING: Stage.APPLYING,
        ChatStatus.NEEDS_INPUT: Stage.ANSWER,
        ChatStatus.BLOCKED: Stage.BLOCKED,
        ChatStatus.DONE: Stage.CLOSED,
    }[status]


_OWNER = {
    Stage.SEND: Owner.YOU,
    Stage.PASTE: Owner.YOU,
    Stage.FIX: Owner.YOU,
    Stage.ANSWER: Owner.YOU,
    Stage.BLOCKED: Owner.YOU,
    Stage.WAITING: Owner.LLM,
    Stage.APPLYING: Owner.CHATOP,
    Stage.CLOSED: Owner.NOBODY,
}


def owner_of(stage: Stage) -> Owner:
    return _OWNER[stage]


def summarize(stages: Sequence[Stage], issues_done: int, issues_total: int) -> dict[str, int]:
    """Counts a project card or header needs at a glance."""
    mine = sum(1 for s in stages if owner_of(s) == Owner.YOU)
    return {
        "your_move": mine,
        "waiting": sum(1 for s in stages if s == Stage.WAITING),
        "applying": sum(1 for s in stages if s == Stage.APPLYING),
        "closed": sum(1 for s in stages if s == Stage.CLOSED),
        "issues_done": issues_done,
        "issues_total": issues_total,
        "percent": round(100 * issues_done / issues_total) if issues_total else 0,
    }
