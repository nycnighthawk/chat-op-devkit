"""UI shells: each must be a thin translation layer over Session (tested against real Session + fakes)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chatop.app.session import Session
from chatop.ui.cli import main
from chatop.ui.web import create_app


def env(turn: int, body: str) -> str:
    return f"<<<CHATOP turn={turn}>>>\n{body}\n<<<END>>>\n"


@pytest.fixture
def session(make_session) -> Session:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    return s  # type: ignore[no-any-return]


def run(session: Session, *argv: str) -> int:
    return main(list(argv), session_factory=lambda _root: session)


def test_cli_full_cycle(session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(session, "init", "--track", "new", "--idea", "todo app") == 0
    assert run(session, "next") == 0
    out = capsys.readouterr().out
    assert "turn 1" in out and "clipboard" in out
    reply = tmp_path / "reply.md"
    body = "@@doc docs/REFINEMENT.md\n# R\n@@end\n@@ask q1 single\nDB?\n- [x] sqlite\n- [ ] pg\n@@end"
    reply.write_text(env(1, body))
    assert run(session, "apply", str(reply)) == 0
    assert "q1" in capsys.readouterr().out
    assert run(session, "answer", "q1", "pg", "--other", "managed") == 0
    assert run(session, "status", "--json") == 0
    assert '"phase": "refine"' in capsys.readouterr().out
    assert run(session, "next") == 0
    assert "managed" in (session.ws.dir / "packets/turn-0002.md").read_text()


def test_cli_errors_are_friendly(session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(session, "next") == 2
    assert "chatop init" in capsys.readouterr().err


def test_cli_bad_reply_exit_code(session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(session, "init", "--track", "new", "--idea", "x")
    run(session, "next")
    bad = tmp_path / "bad.md"
    bad.write_text("no envelope here")
    assert run(session, "apply", str(bad)) == 1
    assert "repair prompt" in capsys.readouterr().out


def test_web_api_cycle(session: Session) -> None:
    client = TestClient(create_app(lambda: session))
    assert client.get("/api/status").status_code == 409
    assert client.post("/api/init", json={"track": "new", "idea": "notes app"}).status_code == 200
    r = client.post("/api/next", json={})
    assert r.status_code == 200 and "notes app" in r.json()["text"]
    r = client.post("/api/apply", json={"text": env(1, "@@ask q1\nPick\n- [x] a\n- [ ] b\n@@end")})
    assert r.json()["ok"] is True and client.get("/api/status").json()["status"] == "awaiting_answers"
    assert client.post("/api/answer", json={"qid": "q1", "choices": ["b"], "other": ""}).status_code == 200
    assert client.get("/api/status").json()["status"] == "ready"
    assert client.get("/").status_code == 200 and "chatop" in client.get("/").text


async def test_tui_boots_and_builds_packet(session: Session) -> None:
    from chatop.ui.tui import ChatopApp

    session.init(idea="tui test")
    app = ChatopApp(lambda: session)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        assert session.state.turn == 1
        assert "turn 1" in app.query_one("#packet").text  # type: ignore[attr-defined]


# ---------------------------------------------------------------- parallel relay through the shells
def lane_session(make_session, tmp_path: Path) -> Session:  # type: ignore[no-untyped-def]
    from tests.conftest import PYTEST

    from chatop.domain.models import Phase, Slice, Status, Track

    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.set_check("test", PYTEST)
    s.config.max_parallel = 2
    s.config.auto_next = False
    s.ws.save_config(s.config)
    st = s.state
    st.phase, st.status = Phase.SLICE, Status.READY
    st.slices = [Slice(id="A", title="alpha", touches=["a.py"]), Slice(id="B", title="beta", touches=["b.py"])]
    s._save(st)
    return s  # type: ignore[no-any-return]


GOOD_A = (
    "@@test test_a.py\nfrom a import f\n\ndef test_f():\n    assert f() == 1\n@@end\n"
    "@@file a.py\ndef f():\n    return 1\n@@end"
)


def test_cli_parallel_flow(make_session, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    s = lane_session(make_session, tmp_path)
    assert run(s, "dispatch") == 0
    out = capsys.readouterr().out
    assert "issue A -> chat c1" in out and "issue B -> chat c2" in out
    assert run(s, "next", "c1") == 0
    out = capsys.readouterr().out
    assert "packet for chat c1, turn 1, full" in out
    assert run(s, "board") == 0
    assert "c1  PASTE IT" in capsys.readouterr().out
    assert run(s, "sent", "c1") == 0
    assert "waiting for the LLM" in capsys.readouterr().out
    assert run(s, "board") == 0
    out = capsys.readouterr().out
    assert "c1  waiting" in out and "your move: 1" in out
    reply = tmp_path / "r.md"
    reply.write_text(f"<<<CHATOP chat=c1 turn=1>>>\n{GOOD_A}\n<<<END>>>")
    assert run(s, "apply", str(reply)) == 0
    out = capsys.readouterr().out
    assert "routed to chat c1" in out
    assert run(s, "config", "--set", "max_attempts", "3") == 0
    assert s.config.max_attempts == 3
    assert run(s, "reset-chat", "c2") == 0
    assert run(s, "status", "--json") == 0
    assert '"chats"' in capsys.readouterr().out


def test_cli_init_parallel(session: Session) -> None:
    assert run(session, "init", "--track", "new", "--idea", "x", "--parallel", "3") == 0
    assert session.config.max_parallel == 3


def test_web_parallel_paste_runs_in_background(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import time

    s = lane_session(make_session, tmp_path)
    client = TestClient(create_app(lambda: s))
    assert len(client.post("/api/dispatch").json()) == 2
    p = client.post("/api/packet", json={"chat": "c1"}).json()
    assert p["chat"] == "c1" and p["kind"] == "full"
    client.post("/api/packet", json={"chat": "c2"})
    seq = client.get("/api/board").json()["event_seq"]
    r = client.post("/api/paste", json={"text": f"<<<CHATOP chat=c1 turn=1>>>\n{GOOD_A}\n<<<END>>>"}).json()
    assert r["ok"] and r["chat"] == "c1" and r["job"]
    for _ in range(100):
        job = client.get(f"/api/job/{r['job']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "done" and job["result"]["slice_done"] is True
    board = client.get("/api/board").json()
    assert any(e["kind"] == "done" and e["seq"] > seq for e in board["events"])
    assert board["jobs"][-1]["chat"] == "c1"
    bad = client.post("/api/paste", json={"text": "<<<CHATOP chat=c9 turn=1>>>\n<<<END>>>"}).json()
    assert bad["ok"] is False and "unknown chat c9" in bad["errors"][0]
    assert client.post("/api/configure", json={"key": "max_parallel", "value": "3"}).json() == {"max_parallel": 3}
    assert client.post("/api/configure", json={"key": "nope", "value": "1"}).status_code == 409
    assert client.post("/api/chat/reset", json={"chat": "c2"}).json()["chats"][1]["status"] == "ready"


async def test_tui_board_tab_and_ready_toasts(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from chatop.ui.tui import ChatopApp

    s = lane_session(make_session, tmp_path)
    app = ChatopApp(lambda: s)
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert [c.issue for c in s.state.chats] == ["A", "B"]
        board = app.query_one("#board").render()
        assert "c1" in str(board) and "alpha" in str(board)
        await pilot.press("n")
        await pilot.pause()
        assert s.state.chat("c1").status.value == "awaiting_reply"  # type: ignore[union-attr]
        s.apply(f"<<<CHATOP chat=c1 turn=1>>>\n{GOOD_A}\n<<<END>>>")
        app._poll_events()
        assert app._seen_seq == s.state.event_seq


def test_web_can_flag_a_packet_as_pasted(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s = lane_session(make_session, tmp_path)
    client = TestClient(create_app(lambda: s))
    client.post("/api/dispatch")
    client.post("/api/packet", json={"chat": "c1"})
    chat = client.get("/api/board").json()["chats"][0]
    assert chat["stage"] == "paste"
    board = client.post("/api/chat/sent", json={"chat": "c1"}).json()
    assert board["chats"][0]["stage"] == "waiting" and board["summary"]["waiting"] == 1
    assert client.post("/api/chat/sent", json={"chat": "c1", "sent": False}).json()["chats"][0]["stage"] == "paste"
    assert client.post("/api/chat/sent", json={"chat": "c7"}).status_code >= 400
