"""Who owns a chat's next action: the human, the LLM or chatop. One pure rule shared by every UI."""

from __future__ import annotations

import pytest

from chatop.domain.models import ChatStatus
from chatop.domain.stage import Owner, Stage, owner_of, stage_of, summarize


@pytest.mark.parametrize(
    ("status", "sent_at", "repair", "stage"),
    [
        (ChatStatus.QUEUED, None, "", Stage.SEND),
        (ChatStatus.READY, None, "", Stage.SEND),
        (ChatStatus.AWAITING_REPLY, None, "", Stage.PASTE),  # packet copied, not yet confirmed pasted
        (ChatStatus.AWAITING_REPLY, 100.0, "", Stage.WAITING),  # the human flagged it as pasted
        (ChatStatus.AWAITING_REPLY, None, "fix it", Stage.FIX),  # rejected: repair prompt to paste
        (ChatStatus.AWAITING_REPLY, 100.0, "fix it", Stage.WAITING),  # repair prompt pasted
        (ChatStatus.APPLYING, 100.0, "", Stage.APPLYING),
        (ChatStatus.NEEDS_INPUT, None, "", Stage.ANSWER),
        (ChatStatus.BLOCKED, None, "", Stage.BLOCKED),
        (ChatStatus.DONE, None, "", Stage.CLOSED),
    ],
)
def test_stage_follows_status_the_pasted_flag_and_the_repair_prompt(
    status: ChatStatus, sent_at: float | None, repair: str, stage: Stage
) -> None:
    assert stage_of(status, sent_at, repair) is stage


def test_owner_tells_whose_move_it_is() -> None:
    assert {s: owner_of(s) for s in Stage} == {
        Stage.SEND: Owner.YOU,
        Stage.PASTE: Owner.YOU,
        Stage.FIX: Owner.YOU,
        Stage.ANSWER: Owner.YOU,
        Stage.BLOCKED: Owner.YOU,
        Stage.WAITING: Owner.LLM,
        Stage.APPLYING: Owner.CHATOP,
        Stage.CLOSED: Owner.NOBODY,
    }


def test_summary_counts_and_orders_the_human_actions() -> None:
    chats = [Stage.CLOSED, Stage.WAITING, Stage.SEND, Stage.PASTE, Stage.ANSWER, Stage.APPLYING]
    s = summarize(chats, issues_done=2, issues_total=5)
    assert (s["your_move"], s["waiting"], s["applying"], s["closed"]) == (3 + 0, 1, 1, 1)
    assert s["issues_done"] == 2 and s["issues_total"] == 5 and s["percent"] == 40
    assert summarize([], 0, 0)["percent"] == 0
