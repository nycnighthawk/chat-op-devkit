"""Which issues may run in parallel chats, and which existing chat should take the next issue (pure)."""

from __future__ import annotations

from chatop.domain.models import SENDABLE, Chat, ChatStatus, Slice


def _norm(t: str) -> str:
    return t.strip().rstrip("/")


def overlaps(a: list[str], b: list[str]) -> bool:
    """True if two issues may touch the same code. Unknown (empty) touches are assumed to overlap with anything."""
    if not a or not b:
        return True
    for x in map(_norm, a):
        for y in map(_norm, b):
            if x == y or y.startswith(x + "/") or x.startswith(y + "/"):
                return True
    return False


def ready_issues(slices: list[Slice]) -> list[Slice]:
    done = {s.id for s in slices if s.status == "done"}
    return [s for s in slices if s.status == "todo" and all(d in done for d in s.depends)]


def pick_dispatch(slices: list[Slice], active: list[Slice], capacity: int) -> list[Slice]:
    """Ready issues, in plan order, that do not collide with running issues or with each other."""
    picked: list[Slice] = []
    running = list(active)
    for issue in ready_issues(slices):
        if len(picked) >= capacity:
            break
        if any(overlaps(issue.touches, other.touches) for other in running):
            continue
        picked.append(issue)
        running.append(issue)
    return picked


def graph_errors(slices: list[Slice]) -> list[str]:
    ids = {s.id for s in slices}
    errors = [f"{s.id} depends on unknown issue {d}" for s in slices for d in s.depends if d not in ids]
    state: dict[str, int] = {}

    def visit(sid: str, trail: list[str]) -> None:
        if state.get(sid) == 2:
            return
        if state.get(sid) == 1:
            errors.append("dependency cycle: " + " -> ".join([*trail[trail.index(sid) :], sid]))
            return
        state[sid] = 1
        issue = next(s for s in slices if s.id == sid)
        for d in issue.depends:
            if d in ids:
                visit(d, [*trail, sid])
        state[sid] = 2

    for s in slices:
        visit(s.id, [])
    return errors


def width(slices: list[Slice]) -> int:
    """How many issues can usefully run at once: the widest dependency level, minus file collisions."""
    level: dict[str, int] = {}
    by_id = {s.id: s for s in slices}

    def depth(sid: str) -> int:
        if sid not in level:
            level[sid] = 0  # cycle guard
            level[sid] = 1 + max((depth(d) for d in by_id[sid].depends if d in by_id), default=-1)
        return level[sid]

    levels: dict[int, list[Slice]] = {}
    for s in slices:
        levels.setdefault(depth(s.id), []).append(s)
    best = 0
    for group in levels.values():
        chosen: list[Slice] = []
        for s in group:
            if not any(overlaps(s.touches, c.touches) for c in chosen):
                chosen.append(s)
        best = max(best, len(chosen))
    return best


def _keys(touches: list[str]) -> set[str]:
    return {f"file:{_norm(t)}" for t in touches} | {f"symbol:{t}" for t in touches}


def choose_chat(issue: Slice, chats: list[Chat], max_issues: int) -> Chat | None:
    """The free chat whose context overlaps the issue most (it holds those files); None = open a new chat."""
    wanted = _keys(issue.touches)
    best: tuple[int, Chat] | None = None
    for chat in chats:
        free = chat.status == ChatStatus.DONE and chat.status not in SENDABLE
        if not free or len(chat.issues_done) >= max_issues:
            continue
        score = len(wanted & set(chat.seen))
        if score and (best is None or score > best[0]):
            best = (score, chat)
    return best[1] if best else None
