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
    depends: list[str] = field(default_factory=list)  # issue ids that must be done first
    lane: str | None = None  # chat currently working on this issue (parallel mode)


@dataclass
class Need:
    kind: NeedKind
    target: str


class ChatStatus(StrEnum):
    """A chat window the human relays to. READY = the last reply was applied and the next packet can be copied."""

    QUEUED = "queued"  # issue assigned, first (full) packet not sent yet
    READY = "ready"  # reply applied; next packet is ready to copy
    AWAITING_REPLY = "awaiting_reply"  # packet handed out; the LLM is working
    APPLYING = "applying"  # reply received; chatop is applying and running checks
    NEEDS_INPUT = "needs_input"  # the LLM asked the human questions
    BLOCKED = "blocked"  # attempts exhausted: human decision needed
    DONE = "done"  # issue finished; the chat is free and keeps its context


SENDABLE = (ChatStatus.QUEUED, ChatStatus.READY)


@dataclass
class Chat:
    id: str
    title: str = ""
    issue: str | None = None
    status: ChatStatus = ChatStatus.QUEUED
    turn: int = 0
    seen: dict[str, str] = field(default_factory=dict)  # context key -> content digest this chat already holds
    needs: list[Need] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    evidence: str = ""
    note: str = ""
    decisions_sent: int = 0
    issues_done: list[str] = field(default_factory=list)
    last_summary: str = ""
    last_result: list[str] = field(default_factory=list)
    tokens_sent: int = 0  # what was actually sent to this chat
    tokens_full: int = 0  # what full packets would have cost
    force_full: bool = False  # next packet must carry the full context (new browser tab, lost history)
    packet_kind: str = ""  # kind of the packet currently handed out ("full" | "delta")
    packet_full_tokens: int = 0
    repair: str = ""  # repair prompt for the last rejected reply, until the chat's next successful apply
    updated: str = ""


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
    chats: list[Chat] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    event_seq: int = 0

    def chat(self, chat_id: str | None) -> Chat | None:
        return next((c for c in self.chats if c.id == chat_id), None)

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
            chats=[_chat_from_dict(c) for c in d.get("chats", [])],
            events=list(d.get("events", [])),
            event_seq=int(d.get("event_seq", 0)),
        )


def _chat_from_dict(d: dict[str, Any]) -> Chat:
    d = dict(d)
    d["status"] = ChatStatus(d.get("status", "queued"))
    d["needs"] = [Need(**n) for n in d.get("needs", [])]
    d["questions"] = [Question(**q) for q in d.get("questions", [])]
    return Chat(**d)
