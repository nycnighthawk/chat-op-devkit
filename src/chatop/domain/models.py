"""Domain value objects. Pure data, no I/O. Serialised to .chatop/state.json."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

Role = Literal["code", "test", "doc"]
SliceStatus = Literal["todo", "active", "done", "blocked"]
NeedKind = Literal["symbol", "file", "callers", "callees", "impact", "affected"]
NEED_KINDS: tuple[str, ...] = ("symbol", "file", "callers", "callees", "impact", "affected")


class Track(StrEnum):
    NEW = "new"  # greenfield: idea -> ... -> slices
    CONTINUE = "continue"  # feature on a chatop-managed project
    ADOPT = "adopt"  # unknown project, assumed sane: reverse-document it
    AUDIT = "audit"  # unknown project, unknown quality: assess + stabilise


class Phase(StrEnum):
    IDEA = "idea"
    REFINE = "refine"
    PRD = "prd"
    SPEC = "spec"
    PLAN = "plan"
    SLICE = "slice"
    DONE = "done"
    FEATURE = "feature"
    DELTA = "delta"
    RECON = "recon"
    AUDIT = "audit"


class Status(StrEnum):
    READY = "ready"  # next packet can be built
    AWAITING_REPLY = "awaiting_reply"  # packet handed out, waiting for the LLM reply
    AWAITING_ANSWERS = "awaiting_answers"  # LLM asked the human questions
    AWAITING_APPROVAL = "awaiting_approval"  # gated phase finished, human must approve
    DONE = "done"


@dataclass
class Question:
    id: str
    text: str
    options: list[str] = field(default_factory=list)
    recommended: list[str] = field(default_factory=list)
    multi: bool = True
    answer: list[str] | None = None
    other: str = ""

    @property
    def answered(self) -> bool:
        return self.answer is not None or bool(self.other.strip())


@dataclass
class Slice:
    id: str
    title: str
    goal: str = ""
    acceptance: list[str] = field(default_factory=list)
    touches: list[str] = field(default_factory=list)
    status: SliceStatus = "todo"
    attempts: int = 0
    red_proven: bool = False  # a failing test for this slice has been observed (TDD red)


@dataclass
class Need:
    kind: NeedKind
    target: str


@dataclass
class State:
    track: Track
    phase: Phase
    status: Status = Status.READY
    turn: int = 0
    slices: list[Slice] = field(default_factory=list)
    current_slice: str | None = None
    questions: list[Question] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)
    evidence: str = ""
    human_note: str = ""
    decisions: list[str] = field(default_factory=list)
    proposed_checks: dict[str, str] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    refine_round: int = 0
    feature: str = ""

    def slice(self, slice_id: str | None) -> Slice | None:
        return next((s for s in self.slices if s.id == slice_id), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> State:
        return cls(
            track=Track(d["track"]),
            phase=Phase(d["phase"]),
            status=Status(d.get("status", "ready")),
            turn=int(d.get("turn", 0)),
            slices=[Slice(**s) for s in d.get("slices", [])],
            current_slice=d.get("current_slice"),
            questions=[Question(**q) for q in d.get("questions", [])],
            needs=[Need(**n) for n in d.get("needs", [])],
            evidence=d.get("evidence", ""),
            human_note=d.get("human_note", ""),
            decisions=list(d.get("decisions", [])),
            proposed_checks=dict(d.get("proposed_checks", {})),
            history=list(d.get("history", [])),
            refine_round=int(d.get("refine_round", 0)),
            feature=d.get("feature", ""),
        )
