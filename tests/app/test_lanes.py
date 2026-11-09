"""Parallel relay: several chats, issues dispatched to them, replies routed by header, context sent as deltas."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.conftest import PYTEST

from chatop.app.session import Session, SessionError
from chatop.domain.models import ChatStatus, Phase, Slice, Status, Track


def reply(chat: str | None, turn: int, body: str) -> str:
    head = f"chat={chat} turn={turn}" if chat else f"turn={turn}"
    return f"<<<CHATOP {head}>>>\n{body}\n<<<END>>>\n"


GOOD = {
    "S1": "@@test test_a.py\nfrom a import f\n\ndef test_f():\n    assert f() == 1\n@@end\n"
    "@@file a.py\ndef f():\n    return 1\n@@end",
    "S2": "@@test test_b.py\nfrom b import g\n\ndef test_g():\n    assert g() == 1\n@@end\n"
    "@@file b.py\ndef g():\n    return 1\n@@end",
    "S3": "@@test test_c.py\nfrom c import h\n\ndef test_h():\n    assert h() == 3\n@@end\n"
    "@@file c.py\nfrom a import f\nfrom b import g\n\n\ndef h():\n    return f() + g() + 1\n@@end",
    "S4": "@@test test_a2.py\nfrom a import f2\n\ndef test_f2():\n    assert f2() == 5\n@@end\n"
    "@@edit a.py\n<<<<<<< SEARCH\ndef f():\n    return 1\n=======\ndef f():\n    return 1\n\n\ndef f2():\n"
    "    return 5\n>>>>>>> REPLACE\n@@end",
}
BAD_S1 = (
    "@@test test_a.py\nfrom a import f\n\ndef test_f():\n    assert f() == 2\n@@end\n"
    "@@file a.py\ndef f():\n    return 1\n@@end"
)
FIX_S1 = "@@edit a.py\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n@@end"


@pytest.fixture
def lanes(make_session, tmp_path: Path):  # type: ignore[no-untyped-def]
    s, clip, index = make_session()
    s.init(track=Track.NEW, idea="x")
    s.set_check("test", PYTEST)
    s.config.max_parallel = 3
    s.config.auto_next = False  # tests build packets explicitly; the auto-copy policy has its own test
    s.ws.save_config(s.config)
    s.ws.write("docs/SPEC.md", "# SPEC\n" + "the big specification text. " * 40)
    st = s.state
    st.phase, st.status = Phase.SLICE, Status.READY
    st.slices = [
        Slice(id="S1", title="reader", touches=["a.py"], acceptance=["AC-1"]),
        Slice(id="S2", title="writer", touches=["b.py"]),
        Slice(id="S3", title="cli", touches=["c.py"], depends=["S1", "S2"]),
        Slice(id="S4", title="reader options", touches=["a.py"], depends=["S1"]),
    ]
    s._save(st)
    return s, clip, index


def complete(s: Session, chat_id: str) -> None:
    s.build_packet(chat=chat_id)
    c = s.state.chat(chat_id)
    assert c is not None and c.issue is not None
    r = s.apply(reply(chat_id, c.turn, GOOD[c.issue]))
    assert r.ok and r.slice_done, (r.errors, s.state.chat(chat_id).evidence)  # type: ignore[union-attr]


def test_dispatch_opens_one_chat_per_independent_issue(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    out = s.dispatch()
    assert [(a.chat, a.issue, a.reused) for a in out] == [("c1", "S1", False), ("c2", "S2", False)]
    st = s.state
    assert [c.status for c in st.chats] == [ChatStatus.QUEUED, ChatStatus.QUEUED]
    assert st.slice("S1").status == "active" and st.slice("S1").lane == "c1"  # type: ignore[union-attr]
    assert st.slice("S3").status == "todo"  # waits for S1 and S2
    assert s.dispatch() == []  # nothing new, capacity and dependencies unchanged


def test_dispatch_respects_max_parallel_and_needs_commits(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.config.max_parallel = 1
    assert [a.issue for a in s.dispatch()] == ["S1"]
    s.config.auto_commit = False
    with pytest.raises(SessionError, match="auto_commit"):
        s.dispatch()


def test_bootstrap_packet_is_full_and_names_its_chat(lanes) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = lanes
    s.dispatch()
    p = s.build_packet(chat="c1")
    assert (p.chat, p.kind, p.turn) == ("c1", "full", 1)
    assert "<<<CHATOP chat=c1 turn=1>>>" in p.text and "S1" in p.text and "big specification" in p.text
    assert clip.text == p.text
    assert s.state.chat("c1").status == ChatStatus.AWAITING_REPLY  # type: ignore[union-attr]
    assert s.build_packet(chat="c1").text == p.text  # idempotent until the reply arrives


def test_build_packet_without_chat_picks_next_up(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    assert s.next_up() is None  # nothing dispatched yet
    p = s.build_packet()  # auto-dispatches, then serves the first sendable chat
    assert p.chat == "c1"
    assert s.next_up() == "c2"  # c1 is waiting for its LLM, so the human's next move is c2
    assert s.build_packet().chat == "c2"


def test_replies_route_by_header_in_any_order(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    text = reply("c2", 1, GOOD["S2"])
    assert s.route(text).chat == "c2" and s.route(text).ok
    r = s.apply(text)  # c2 answers first
    assert r.ok and r.chat == "c2" and r.slice_done
    st = s.state
    assert st.chat("c1").status == ChatStatus.AWAITING_REPLY  # type: ignore[union-attr]
    assert st.slice("S2").status == "done" and st.slice("S1").status == "active"  # type: ignore[union-attr]


def test_unknown_chat_and_ambiguous_replies_are_rejected_with_guidance(lanes) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    r = s.apply(reply("c9", 1, "@@summary hi"))
    assert not r.ok and "unknown chat c9" in r.errors[0]
    r = s.apply(reply(None, 1, "@@summary hi"))
    assert not r.ok and "c1" in r.errors[0] and "c2" in r.errors[0]
    assert clip.text is not None and "<<<CHATOP chat=" in clip.text  # repair prompt shows the header to use


def test_headerless_reply_routes_when_exactly_one_chat_is_waiting(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    r = s.apply(reply(None, 1, GOOD["S1"]))
    assert r.ok and r.chat == "c1" and r.slice_done


def test_stale_turn_for_a_chat_is_rejected(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    r = s.apply(reply("c1", 7, GOOD["S1"]))
    assert not r.ok and "turn 7" in r.errors[0]
    assert s.state.chat("c1").status == ChatStatus.AWAITING_REPLY  # type: ignore[union-attr]


def test_a_failing_chat_never_pollutes_the_checks_of_another(lanes, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    r1 = s.apply(reply("c1", 1, BAD_S1))
    assert r1.ok and not r1.slice_done and r1.red_ok is True
    assert not (tmp_path / "a.py").exists() and not (tmp_path / "test_a.py").exists()  # held back by chatop
    r2 = s.apply(reply("c2", 1, GOOD["S2"]))
    assert r2.slice_done  # c1's failing test was not in the tree
    shown = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.split()
    assert "b.py" in shown and "a.py" not in shown and "test_a.py" not in shown
    # c1 retries with a code-only edit against the code it wrote earlier
    p = s.build_packet(chat="c1")
    assert "assert 1 == 2" in p.text or "AssertionError" in p.text  # failure evidence travels in the delta packet
    r3 = s.apply(reply("c1", 2, FIX_S1))
    assert r3.ok and r3.slice_done, s.state.chat("c1").evidence  # type: ignore[union-attr]
    assert (tmp_path / "a.py").exists()


def test_ready_events_and_chat_states_for_the_ui(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    b0 = s.board()
    assert b0["mode"] == "parallel" and b0["next_up"]["chat"] == "c2"  # c1 is waiting on its LLM
    seq0 = b0["event_seq"]
    s.apply(reply("c1", 1, BAD_S1))
    b1 = s.board()
    c1 = next(c for c in b1["chats"] if c["id"] == "c1")
    assert c1["status"] == "ready" and c1["last_result"]
    new = [e for e in b1["events"] if e["seq"] > seq0]
    assert any(e["kind"] == "ready" and e["chat"] == "c1" for e in new)
    assert [e["seq"] for e in new] == sorted(e["seq"] for e in new)
    assert s.events_since(seq0) == new


def test_finishing_an_issue_unblocks_dependents_and_reuses_the_chat_with_the_context(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    complete(s, "c1")  # S1 done in c1 (c1 wrote a.py, so it holds that context)
    st = s.state
    c1 = st.chat("c1")
    assert c1 is not None and c1.issue == "S4" and c1.status == ChatStatus.READY  # affinity: same file
    assert st.slice("S3").status == "todo"  # still waits for S2
    complete(s, "c2")
    assert s.state.chat("c3") is not None and s.state.chat("c3").issue == "S3"  # type: ignore[union-attr]
    assert s.state.chat("c2").status == ChatStatus.DONE  # type: ignore[union-attr]  # free, keeps its context


def test_continuation_packet_is_a_delta(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    first = s.build_packet(chat="c1")
    c1 = s.state.chat("c1")
    assert c1 is not None
    s.apply(reply("c1", 1, GOOD["S1"]))
    nxt = s.build_packet(chat="c1")
    assert nxt.kind == "delta" and nxt.turn == 2
    assert nxt.tokens < first.tokens // 2 and nxt.full_tokens > nxt.tokens
    assert "S4" in nxt.text and "<<<CHATOP chat=c1 turn=2>>>" in nxt.text
    assert "big specification" not in nxt.text  # unchanged SPEC is not resent
    assert "already in your context" in nxt.text
    full = s.build_packet(chat="c1", full=True)
    assert full.kind == "full" and "big specification" in full.text and full.turn == 2


def test_changed_documents_are_resent_to_a_continuing_chat(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.apply(reply("c1", 1, GOOD["S1"]))
    s.ws.write("docs/SPEC.md", "# SPEC\nrevised: use a different parser")
    nxt = s.build_packet(chat="c1")
    assert "revised: use a different parser" in nxt.text and nxt.kind == "delta"


def test_attempts_exhausted_blocks_the_chat_and_the_issue(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.config.max_attempts = 2
    s.dispatch()
    for turn in (1, 2):
        s.build_packet(chat="c1")
        s.apply(reply("c1", turn, BAD_S1 if turn == 1 else BAD_S1.replace("return 1", "return 3")))
    st = s.state
    assert st.chat("c1").status == ChatStatus.BLOCKED and st.slice("S1").status == "blocked"  # type: ignore[union-attr]
    assert any(e["kind"] == "blocked" for e in st.events)
    with pytest.raises(SessionError, match="blocked"):
        s.build_packet(chat="c1")
    s.reset_chat("c1")
    assert st.chat("c1").status == ChatStatus.READY and st.chat("c1").force_full  # type: ignore[union-attr]
    assert s.build_packet(chat="c1").kind == "full"


def test_questions_pause_only_their_own_chat(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    r = s.apply(reply("c1", 1, "@@ask q1 single\nWhich format?\n- [x] csv\n- [ ] tsv\n@@end"))
    assert r.ok and s.state.chat("c1").status == ChatStatus.NEEDS_INPUT  # type: ignore[union-attr]
    assert [q.id for q in s.pending_questions(chat="c1")] == ["q1"] and s.pending_questions(chat="c2") == []
    with pytest.raises(SessionError, match="questions"):
        s.build_packet(chat="c1")
    assert s.apply(reply("c2", 1, GOOD["S2"])).slice_done  # c2 carries on
    s.accept_recommended(chat="c1")
    assert s.state.chat("c1").status == ChatStatus.READY  # type: ignore[union-attr]
    assert "Which format?" in s.build_packet(chat="c1").text


def test_syntax_errors_in_a_lane_reply_are_rejected_in_one_shot(lanes, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    r = s.apply(reply("c1", 1, "@@file a.py\ndef f(:\n@@end\n@@test test_a.py\nclass X(\n@@end"))
    assert not r.ok and len(r.errors) == 2 and not (tmp_path / "a.py").exists()
    assert s.state.chat("c1").status == ChatStatus.AWAITING_REPLY  # type: ignore[union-attr]


def test_all_issues_done_finishes_the_phase(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    complete(s, "c1")
    complete(s, "c2")
    complete(s, "c3")  # S3
    complete(s, "c1")  # S4 (affinity)
    st = s.state
    assert st.phase == Phase.DONE and st.status == Status.DONE
    assert all(sl.status == "done" for sl in st.slices)
    assert any(e["kind"] == "finished" for e in st.events)


def test_clipboard_watch_routes_a_pasted_reply_to_its_chat(lanes) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    last, res = s.watch_tick(None)
    assert res is None  # the clipboard holds a packet
    clip.text = reply("c2", 1, GOOD["S2"])
    last, res = s.watch_tick(last)
    assert res is not None and res.chat == "c2" and res.slice_done
    assert s.watch_tick(clip.text)[1] is None  # the same text is never applied twice


def test_auto_copy_of_the_next_packet_only_when_no_other_chat_is_waiting(lanes) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = lanes
    s.config.auto_next = True
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    r = s.apply(reply("c1", 1, BAD_S1))
    assert r.next_packet is None  # c2 is mid-flight: do not clobber the clipboard
    r = s.apply(reply("c2", 1, GOOD["S2"]))
    assert r.next_packet is not None  # nobody else is waiting: the next packet is ready on the clipboard
    assert clip.text == r.next_packet.text


def test_plan_validation_rejects_cycles_and_hints_at_parallelism(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    st = s.state
    st.phase, st.status = Phase.PLAN, Status.READY
    s._save(st)
    s.build_packet()
    cyc = (
        '[{"id":"A","title":"a","touches":["a"],"depends":["B"]},'
        '{"id":"B","title":"b","touches":["b"],"depends":["A"]}]'
    )
    r = s.apply(f"<<<CHATOP turn=1>>>\n@@slices\n{cyc}\n@@end\n<<<END>>>")
    assert r.ok and any("cycle" in m for m in r.messages) and s.state.slices == []
    s.build_packet()
    fan = (
        '[{"id":"A","title":"a","touches":["a"]},{"id":"B","title":"b","touches":["b"]},'
        '{"id":"C","title":"c","touches":["c"]}]'
    )
    r = s.apply(f"<<<CHATOP turn={s.state.turn}>>>\n@@slices\n{fan}\n@@end\n<<<END>>>")
    assert any("in parallel" in m and "max_parallel" in m for m in r.messages)


def test_approving_the_plan_dispatches_chats_in_parallel_mode(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.config.max_parallel = 2
    st = s.state
    st.phase, st.status = Phase.PLAN, Status.AWAITING_APPROVAL
    st.slices = [Slice(id="A", title="a", touches=["a"]), Slice(id="B", title="b", touches=["b"])]
    s._save(st)
    nxt = s.approve()
    assert nxt.phase == Phase.SLICE and nxt.current_slice is None
    assert [c.issue for c in nxt.chats] == ["A", "B"]


def test_configure_changes_parallelism_and_adopts_a_running_serial_issue(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    st = s.state
    st.phase, st.status = Phase.SLICE, Status.READY
    st.slices = [Slice(id="A", title="a", touches=["a"], status="active"), Slice(id="B", title="b", touches=["b"])]
    st.current_slice = "A"
    s._save(st)
    s.configure("max_parallel", "2")
    out = s.dispatch()
    assert [(a.chat, a.issue) for a in out] == [("c1", "A"), ("c2", "B")]
    assert s.state.current_slice is None


def test_rejected_reply_leaves_a_repair_prompt_on_the_chat_until_the_next_good_apply(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    r = s.apply(reply("c1", 1, "@@file a.py\ndef f(:\n@@end"))
    assert not r.ok
    view = next(c for c in s.board()["chats"] if c["id"] == "c1")
    assert "chat=c1 turn=1" in view["repair"]
    assert any(e["kind"] == "rejected" for e in s.board()["events"])
    assert s.apply(reply("c1", 1, GOOD["S1"])).slice_done
    assert s.state.chat("c1").repair == ""  # type: ignore[union-attr]


def stage_of_chat(s: Session, chat: str) -> tuple[str, str]:
    v = next(c for c in s.board()["chats"] if c["id"] == chat)
    return v["stage"], v["owner"]


def test_stages_walk_send_paste_waiting_and_back_to_closed(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    assert stage_of_chat(s, "c1") == ("send", "you")
    s.build_packet(chat="c1")
    assert stage_of_chat(s, "c1") == ("paste", "you")  # copied, not yet confirmed pasted
    s.mark_sent("c1")
    assert stage_of_chat(s, "c1") == ("waiting", "llm")
    v = next(c for c in s.board()["chats"] if c["id"] == "c1")
    assert v["sent_at"] is not None
    s.mark_sent("c1", sent=False)  # "I did not paste it after all"
    assert stage_of_chat(s, "c1") == ("paste", "you")
    s.mark_sent("c1")
    assert s.apply(reply("c1", 1, GOOD["S1"])).slice_done
    assert s.state.chat("c1").sent_at is None  # type: ignore[union-attr]
    assert stage_of_chat(s, "c1") == ("send", "you")  # S4 touches a.py: the same chat is reused, delta packet next
    s.build_packet(chat="c2")
    s.mark_sent("c2")
    assert s.apply(reply("c2", 1, GOOD["S2"])).slice_done
    assert stage_of_chat(s, "c2") == ("closed", "nobody")  # nothing else is ready for it yet


def test_mark_sent_needs_a_packet_that_is_out(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    with pytest.raises(SessionError, match="copy its packet first"):
        s.mark_sent("c1")
    with pytest.raises(SessionError, match="unknown chat"):
        s.mark_sent("c9")


def test_a_rejected_reply_sends_the_chat_back_to_fix_until_the_repair_prompt_is_pasted(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.mark_sent("c1")
    assert not s.apply(reply("c1", 1, "@@file a.py\ndef f(:\n@@end")).ok
    assert stage_of_chat(s, "c1") == ("fix", "you")
    s.mark_sent("c1")  # repair prompt pasted into the chat
    assert stage_of_chat(s, "c1") == ("waiting", "llm")


def test_board_summary_counts_what_needs_the_human(lanes) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = lanes
    s.dispatch()
    s.build_packet(chat="c1")
    s.build_packet(chat="c2")
    s.mark_sent("c2")
    sm = s.board()["summary"]
    assert (sm["your_move"], sm["waiting"], sm["closed"]) == (1, 1, 0)
    assert (sm["issues_done"], sm["issues_total"], sm["percent"]) == (0, 4, 0)
    assert s.apply(reply("c2", 1, GOOD["S2"])).slice_done
    assert s.board()["summary"]["percent"] == 25
