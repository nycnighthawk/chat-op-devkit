"""Pure state machine: which phase follows which, gates, and the slice loop."""

from __future__ import annotations

import copy

from chatop.domain.models import Phase, State, Status, Track

TRACKS: dict[Track, list[Phase]] = {
    Track.NEW: [Phase.IDEA, Phase.REFINE, Phase.PRD, Phase.SPEC, Phase.PLAN, Phase.SLICE, Phase.DONE],
    Track.CONTINUE: [Phase.FEATURE, Phase.REFINE, Phase.DELTA, Phase.PLAN, Phase.SLICE, Phase.DONE],
    Track.ADOPT: [Phase.RECON, Phase.DONE],
    Track.AUDIT: [Phase.RECON, Phase.AUDIT, Phase.PLAN, Phase.SLICE, Phase.DONE],
}
# Phases that move on after a single reply, without waiting for @@advance.
AUTO_ADVANCE = {Phase.IDEA, Phase.FEATURE, Phase.RECON}
DEFAULT_GATES = {Phase.PRD, Phase.SPEC, Phase.DELTA, Phase.PLAN, Phase.AUDIT}


class WorkflowError(Exception):
    pass


def next_phase(track: Track, phase: Phase) -> Phase:
    seq = TRACKS[track]
    if phase not in seq:
        raise WorkflowError(f"phase {phase} is not part of track {track}")
    i = seq.index(phase)
    return seq[min(i + 1, len(seq) - 1)]


def _activate_next_slice(s: State) -> State:
    nxt = next((sl for sl in s.slices if sl.status in ("todo", "active")), None)
    if nxt is None:
        s.phase, s.status, s.current_slice = Phase.DONE, Status.DONE, None
        return s
    nxt.status = "active"
    s.current_slice = nxt.id
    s.status = Status.READY
    return s


def advance(state: State) -> State:
    s = copy.deepcopy(state)
    target = next_phase(s.track, s.phase)
    if target == Phase.SLICE:
        if not any(sl.status != "done" for sl in s.slices):
            raise WorkflowError("PLAN produced no open slices; re-run the plan turn")
        s.phase = Phase.SLICE
        return _activate_next_slice(s)
    s.phase = target
    s.refine_round = 0
    s.status = Status.DONE if target == Phase.DONE else Status.READY
    return s


def request_advance(state: State, gates: set[Phase]) -> State:
    """LLM said @@advance. Gated phases wait for the human; others move on."""
    if state.phase in gates:
        s = copy.deepcopy(state)
        s.status = Status.AWAITING_APPROVAL
        return s
    return advance(state)


def complete_slice(state: State) -> State:
    s = copy.deepcopy(state)
    cur = s.slice(s.current_slice)
    if cur is not None:
        cur.status = "done"
    return _activate_next_slice(s)


def start_feature(state: State, text: str) -> State:
    if state.phase != Phase.DONE:
        raise WorkflowError(f"finish the current {state.phase} phase first (or use --force)")
    s = copy.deepcopy(state)
    s.track, s.phase, s.status = Track.CONTINUE, Phase.FEATURE, Status.READY
    s.feature, s.refine_round, s.questions, s.needs = text, 0, [], []
    s.evidence = s.human_note = ""
    return s
