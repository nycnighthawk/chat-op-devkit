"""Parse the LLM's CHATOP reply envelope.

Format (line oriented, so it survives any chat UI and needs no JSON escaping of code):

    <<<CHATOP turn=N>>>
    @@summary one line
    @@file|@@test|@@doc <path>      ... content ...  @@end
    @@edit <path>  (SEARCH/REPLACE blocks)            @@end
    @@delete <path>
    @@ask <id> [single]  question + "- [x] opt" lines  @@end
    @@slices  JSON array                               @@end
    @@need <symbol|file|callers|callees|impact|affected> <target>
    @@decision <text>
    @@run <check-name>
    @@check <name> <command>   (proposal; human accepts)
    @@advance
    <<<END>>>
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import cast

from chatop.domain.models import NEED_KINDS, Need, NeedKind, Question, Role, Slice

START_RE = re.compile(r"^<<<CHATOP(?:\s+turn=(\d+))?\s*>>>\s*$")
END_MARK = "<<<END>>>"
PACKET_MARK = "# CHATOP PACKET"  # first line of every outbound packet; never a reply
BLOCK_DIRECTIVES = {"file", "test", "doc", "edit", "ask", "slices"}
INLINE_DIRECTIVES = {"summary", "delete", "need", "decision", "run", "advance", "check"}
TEST_PATTERNS = (
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.(py|go)$"),
    re.compile(r"\.(test|spec)\.[jt]sx?$"),
    re.compile(r"(^|/)__tests__/"),
    re.compile(r"Test\.(java|kt|cs)$"),
)


def infer_role(path: str) -> Role:
    if path.startswith("docs/") or path.endswith(".md"):
        return "doc"
    return "test" if any(p.search(path) for p in TEST_PATTERNS) else "code"


@dataclass
class Write:
    path: str
    content: str
    role: Role


@dataclass
class Edit:
    path: str
    blocks: list[tuple[str, str]]


@dataclass
class Delete:
    path: str


Op = Write | Edit | Delete


@dataclass
class Reply:
    turn: int | None = None
    summary: str = ""
    ops: list[Op] = field(default_factory=list)  # file operations, in reply order
    questions: list[Question] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)
    slices: list[Slice] | None = None
    decisions: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)  # proposed; human must accept
    advance: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def writes(self) -> list[Write]:
        return [o for o in self.ops if isinstance(o, Write)]

    @property
    def edits(self) -> list[Edit]:
        return [o for o in self.ops if isinstance(o, Edit)]

    @property
    def deletes(self) -> list[str]:
        return [o.path for o in self.ops if isinstance(o, Delete)]


def is_packet(text: str) -> bool:
    return text.lstrip().startswith(PACKET_MARK) or f"\n{PACKET_MARK}" in text[:2000]


def contains_envelope(text: str) -> int | None:
    """Return the turn number if text holds a CHATOP reply envelope (used by clipboard watch)."""
    if is_packet(text):
        return None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = START_RE.match(line.strip())
        if m:
            return int(m.group(1)) if m.group(1) else -1
    return None


def parse_reply(text: str) -> Reply:
    reply = Reply()
    if is_packet(text):
        reply.errors.append("This is a chatop PACKET, not a reply. Paste it into the chat, then paste back the answer.")
        return reply
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if START_RE.match(ln.strip())), None)
    if start is None:
        reply.errors.append("No <<<CHATOP turn=N>>> block found. Paste the whole reply or ask the LLM to re-emit it.")
        return reply
    m = START_RE.match(lines[start].strip())
    assert m is not None
    reply.turn = int(m.group(1)) if m.group(1) else None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == END_MARK), None)
    if end is None:
        reply.errors.append("Reply looks truncated (missing <<<END>>>). Ask the LLM: 'continue the CHATOP block'.")
        end = len(lines)
    i = start + 1
    while i < end:
        line = lines[i]
        if not line.startswith("@@"):
            i += 1  # tolerate prose between directives
            continue
        head, _, arg = line[2:].partition(" ")
        name, arg = head.strip(), arg.strip()
        if name in BLOCK_DIRECTIVES:
            j = next((k for k in range(i + 1, end) if lines[k].rstrip() == "@@end"), None)
            if j is None:
                reply.errors.append(f"@@{name} {arg}: block not closed with @@end")
                break
            _block(reply, name, arg, lines[i + 1 : j])
            i = j + 1
            continue
        if name in INLINE_DIRECTIVES:
            _inline(reply, name, arg)
        elif name != "end":
            reply.errors.append(f"Unknown directive @@{name}")
        i += 1
    return reply


def _block(reply: Reply, name: str, arg: str, body: list[str]) -> None:
    content = "\n".join(body) + "\n" if body else ""
    if name in ("file", "test", "doc"):
        if not arg:
            reply.errors.append(f"@@{name} needs a path")
            return
        role: Role = "test" if name == "test" else "doc" if name == "doc" else infer_role(arg)
        reply.ops.append(Write(arg, content, role))
    elif name == "edit":
        blocks = _parse_edit_blocks(body)
        if blocks is None:
            reply.errors.append(f"@@edit {arg}: malformed SEARCH/REPLACE block")
        else:
            reply.ops.append(Edit(arg, blocks))
    elif name == "ask":
        reply.questions.append(_parse_question(arg, body))
    elif name == "slices":
        try:
            raw = json.loads(content or "null")
            if not isinstance(raw, list):
                raise ValueError("expected a JSON array")
            reply.slices = [
                Slice(
                    id=str(s["id"]),
                    title=str(s.get("title", s["id"])),
                    goal=str(s.get("goal", "")),
                    acceptance=[str(a) for a in s.get("acceptance", [])],
                    touches=[str(t) for t in s.get("touches", [])],
                )
                for s in raw
            ]
        except (ValueError, KeyError, TypeError) as exc:
            reply.errors.append(f"@@slices: invalid JSON ({exc})")


def _inline(reply: Reply, name: str, arg: str) -> None:
    if name == "summary":
        reply.summary = arg
    elif name == "delete":
        reply.ops.append(Delete(arg))
    elif name == "decision":
        reply.decisions.append(arg)
    elif name == "run":
        reply.runs.append(arg)
    elif name == "advance":
        reply.advance = True
    elif name == "check":
        cname, _, cmd = arg.partition(" ")
        if not cname or not cmd.strip():
            reply.errors.append(f"@@check {arg}: expected '@@check <name> <command>'")
        else:
            reply.checks[cname] = cmd.strip()
    elif name == "need":
        kind, _, target = arg.partition(" ")
        if kind not in NEED_KINDS or not target.strip():
            reply.errors.append(f"@@need {arg}: kind must be one of {', '.join(NEED_KINDS)}")
        else:
            reply.needs.append(Need(cast(NeedKind, kind), target.strip()))


def _parse_edit_blocks(body: list[str]) -> list[tuple[str, str]] | None:
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(body):
        if body[i].strip() == "":
            i += 1
            continue
        if not body[i].startswith("<<<<<<< SEARCH"):
            return None
        try:
            mid = next(k for k in range(i + 1, len(body)) if body[k].rstrip() == "=======")
            end = next(k for k in range(mid + 1, len(body)) if body[k].startswith(">>>>>>> REPLACE"))
        except StopIteration:
            return None
        search = "".join(ln + "\n" for ln in body[i + 1 : mid])
        replace = "".join(ln + "\n" for ln in body[mid + 1 : end])
        blocks.append((search, replace))
        i = end + 1
    return blocks or None


OPTION_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+?)\s*$")


def _parse_question(arg: str, body: list[str]) -> Question:
    parts = arg.split()
    qid = parts[0] if parts else "q"
    text_lines: list[str] = []
    options: list[str] = []
    recommended: list[str] = []
    for ln in body:
        m = OPTION_RE.match(ln)
        if m:
            opt = re.sub(r"\s*\((recommended|rec)\)\s*$", "", m.group(2), flags=re.I)
            options.append(opt)
            if m.group(1).lower() == "x":
                recommended.append(opt)
        elif ln.strip():
            text_lines.append(ln.strip())
    return Question(
        id=qid,
        text=" ".join(text_lines),
        options=options,
        recommended=recommended,
        multi="single" not in parts[1:],
    )
