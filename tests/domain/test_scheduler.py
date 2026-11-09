"""Scheduler: which issues can run in parallel chats, and which existing chat should take the next one."""

from chatop.domain.models import Chat, ChatStatus, Slice
from chatop.domain.scheduler import (
    choose_chat,
    graph_errors,
    overlaps,
    pick_dispatch,
    ready_issues,
    width,
)


def sl(id: str, touches: list[str], depends: list[str] | None = None, status: str = "todo") -> Slice:
    return Slice(id=id, title=id, touches=touches, depends=depends or [], status=status)  # type: ignore[arg-type]


def test_overlaps_paths_dirs_symbols_and_unknown() -> None:
    assert overlaps(["src/a.py"], ["src/a.py"])
    assert overlaps(["src/"], ["src/a.py"]) and overlaps(["src/a.py"], ["src"])
    assert not overlaps(["src/a.py"], ["src/b.py"])
    assert overlaps(["to_markdown"], ["to_markdown"]) and not overlaps(["f"], ["g"])
    assert overlaps([], ["src/a.py"]) and overlaps([], [])  # unknown touches: assume the worst


def test_ready_issues_respect_dependencies_and_blocked() -> None:
    slices = [sl("S1", ["a"], status="done"), sl("S2", ["b"], ["S1"]), sl("S3", ["c"], ["S2"]), sl("S4", ["d"], ["S9"])]
    assert [s.id for s in ready_issues(slices)] == ["S2"]
    slices[1].status = "blocked"
    assert ready_issues(slices) == []


def test_pick_dispatch_avoids_conflicts_and_respects_capacity() -> None:
    slices = [sl("S1", ["src/a.py"]), sl("S2", ["src/b.py"]), sl("S3", ["src/a.py"]), sl("S4", ["src/d.py"])]
    picked = pick_dispatch(slices, active=[], capacity=3)
    assert [s.id for s in picked] == ["S1", "S2", "S4"]  # S3 conflicts with S1
    assert [s.id for s in pick_dispatch(slices, active=[], capacity=1)] == ["S1"]
    active = [sl("S2", ["src/b.py"], status="active")]
    assert [s.id for s in pick_dispatch(slices, active=active, capacity=3)] == ["S1", "S4"]
    assert pick_dispatch(slices, active=active, capacity=0) == []


def test_graph_errors_unknown_dep_and_cycle() -> None:
    assert graph_errors([sl("S1", ["a"]), sl("S2", ["b"], ["S1"])]) == []
    assert any("S9" in e for e in graph_errors([sl("S1", ["a"], ["S9"])]))
    cyc = graph_errors([sl("S1", ["a"], ["S2"]), sl("S2", ["b"], ["S1"])])
    assert any("cycle" in e for e in cyc)


def test_width_counts_parallelisable_issues_per_level() -> None:
    chain = [sl("S1", ["a"]), sl("S2", ["b"], ["S1"]), sl("S3", ["c"], ["S2"])]
    assert width(chain) == 1
    fan = [sl("S1", ["a"]), sl("S2", ["b"]), sl("S3", ["c"]), sl("S4", ["d"], ["S1", "S2", "S3"])]
    assert width(fan) == 3
    clash = [sl("S1", ["a"]), sl("S2", ["a"])]
    assert width(clash) == 1  # same files: cannot run together


def chat(id: str, seen: list[str], status: ChatStatus = ChatStatus.DONE, done: int = 1) -> Chat:
    return Chat(id=id, status=status, seen={k: "h" for k in seen}, issues_done=[f"x{i}" for i in range(done)])


def test_choose_chat_prefers_overlapping_context_and_skips_busy_or_full() -> None:
    issue = sl("S5", ["src/csv2md/convert.py", "to_markdown"])
    chats = [
        chat("c1", ["file:src/cli.py"]),
        chat("c2", ["file:src/csv2md/convert.py", "file:src/other.py"]),
        chat("c3", ["file:src/csv2md/convert.py"], status=ChatStatus.AWAITING_REPLY),
    ]
    assert choose_chat(issue, chats, max_issues=3).id == "c2"  # type: ignore[union-attr]
    assert choose_chat(issue, [chat("c1", ["file:src/cli.py"])], max_issues=3) is None
    assert choose_chat(issue, [chat("c2", ["file:src/csv2md/convert.py"], done=3)], max_issues=3) is None
    sym_chat = chat("c4", ["symbol:to_markdown"])
    assert choose_chat(issue, [sym_chat], max_issues=3).id == "c4"  # type: ignore[union-attr]
