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
