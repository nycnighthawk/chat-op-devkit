"""Workflow state machine: tracks, phases, gates, slice loop."""

import pytest

from chatop.domain.models import Phase, Slice, State, Status, Track
from chatop.domain.workflow import (
    WorkflowError,
    advance,
    complete_slice,
    request_advance,
    start_feature,
)


def test_new_track_order() -> None:
    s = State(track=Track.NEW, phase=Phase.IDEA)
    phases = [s.phase]
    for _ in range(4):
        s = advance(s)
        phases.append(s.phase)
    assert phases == [Phase.IDEA, Phase.REFINE, Phase.PRD, Phase.SPEC, Phase.PLAN]


def test_gate_requires_approval() -> None:
    s = State(track=Track.NEW, phase=Phase.PRD)
    s = request_advance(s, gates={Phase.PRD})
    assert s.phase == Phase.PRD and s.status == Status.AWAITING_APPROVAL
    s2 = request_advance(State(track=Track.NEW, phase=Phase.REFINE), gates={Phase.PRD})
    assert s2.phase == Phase.PRD and s2.status == Status.READY


def test_entering_slice_selects_first_todo() -> None:
    s = State(
        track=Track.NEW,
        phase=Phase.PLAN,
        slices=[Slice(id="S1", title="a", status="done"), Slice(id="S2", title="b")],
    )
    s = advance(s)
    assert s.phase == Phase.SLICE and s.current_slice == "S2"
    assert s.slices[1].status == "active"


def test_entering_slice_without_slices_fails() -> None:
    with pytest.raises(WorkflowError):
        advance(State(track=Track.NEW, phase=Phase.PLAN))


def test_complete_slice_moves_on_then_done() -> None:
    s = State(
        track=Track.NEW,
        phase=Phase.SLICE,
        current_slice="S1",
        slices=[Slice(id="S1", title="a", status="active"), Slice(id="S2", title="b")],
    )
    s = complete_slice(s)
    assert s.current_slice == "S2" and s.slices[0].status == "done"
    s = complete_slice(s)
    assert s.phase == Phase.DONE and s.status == Status.DONE and s.current_slice is None


def test_feature_only_from_done() -> None:
    with pytest.raises(WorkflowError):
        start_feature(State(track=Track.NEW, phase=Phase.SPEC), "x")
    s = start_feature(State(track=Track.ADOPT, phase=Phase.DONE, status=Status.DONE), "Add export")
    assert (s.track, s.phase, s.feature, s.status) == (Track.CONTINUE, Phase.FEATURE, "Add export", Status.READY)


def test_audit_and_adopt_tracks() -> None:
    a = advance(State(track=Track.AUDIT, phase=Phase.RECON))
    assert a.phase == Phase.AUDIT
    d = advance(State(track=Track.ADOPT, phase=Phase.RECON))
    assert d.phase == Phase.DONE and d.status == Status.DONE


def test_state_roundtrip() -> None:
    s = State(track=Track.NEW, phase=Phase.SLICE, slices=[Slice(id="S1", title="t", touches=["a.py"])])
    assert State.from_dict(s.to_dict()) == s


def test_advance_into_slice_without_activation_for_parallel_dispatch() -> None:
    s = State(track=Track.NEW, phase=Phase.PLAN, slices=[Slice(id="S1", title="a"), Slice(id="S2", title="b")])
    s = advance(s, activate=False)
    assert s.phase == Phase.SLICE and s.current_slice is None and s.status == Status.READY
    assert [x.status for x in s.slices] == ["todo", "todo"]


def test_state_roundtrip_with_chats_and_events() -> None:
    from chatop.domain.models import Chat, ChatStatus

    s = State(track=Track.NEW, phase=Phase.SLICE)
    s.chats = [Chat(id="c1", issue="S1", status=ChatStatus.READY, turn=2, seen={"file:a.py": "h"})]
    s.events = [{"seq": 1, "kind": "ready", "chat": "c1", "msg": "c1 ready"}]
    s.event_seq = 1
    assert State.from_dict(s.to_dict()) == s
