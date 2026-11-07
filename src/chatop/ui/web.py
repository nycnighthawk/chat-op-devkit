"""FastAPI web UI. JSON endpoints map 1:1 onto Session methods; the page is static vanilla JS."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from importlib import resources
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from chatop.app.session import ApplyResult, PacketResult, Session, SessionError
from chatop.domain.models import Track


class InitIn(BaseModel):
    track: str | None = None
    idea: str = ""


class NextIn(BaseModel):
    accept: bool = False
    approve: bool = False


class ApplyIn(BaseModel):
    text: str
    force: bool = False


class AnswerIn(BaseModel):
    qid: str
    choices: list[str]
    other: str = ""


class NoteIn(BaseModel):
    note: str = ""


class FeatureIn(BaseModel):
    text: str
    force: bool = False


class WatchIn(BaseModel):
    last_seen: str | None = None


def _packet(p: PacketResult) -> dict[str, Any]:
    return {"turn": p.turn, "text": p.text, "tokens": p.tokens, "notes": p.notes, "copied": p.copied}


def _apply(r: ApplyResult) -> dict[str, Any]:
    d = asdict(r)
    d["checks"] = [{"name": c.name, "code": c.code, "seconds": c.seconds} for c in r.checks]
    d["next_packet"] = _packet(r.next_packet) if r.next_packet else None
    return d


def create_app(session_factory: Callable[[], Session]) -> FastAPI:
    app = FastAPI(title="chatop", docs_url="/api/docs")
    session = session_factory()
    lock = threading.Lock()

    def call(fn: Callable[[], Any]) -> Any:
        with lock:
            try:
                return fn()
            except SessionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return resources.files("chatop.ui").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/api/status")
    def status() -> Any:
        return call(session.status)

    @app.post("/api/init")
    def init(body: InitIn) -> Any:
        return call(lambda: session.init(Track(body.track) if body.track else None, body.idea).to_dict())

    @app.post("/api/next")
    def next_packet(body: NextIn) -> Any:
        def run() -> dict[str, Any]:
            if body.accept:
                session.accept_recommended()
            if body.approve:
                session.approve()
            return _packet(session.build_packet())

        return call(run)

    @app.post("/api/apply")
    def apply(body: ApplyIn) -> Any:
        return call(lambda: _apply(session.apply(body.text, body.force)))

    @app.post("/api/answer")
    def answer(body: AnswerIn) -> Any:
        def run() -> Any:
            session.answer(body.qid, body.choices, body.other)
            return session.status()

        return call(run)

    @app.post("/api/accept")
    def accept() -> Any:
        def run() -> Any:
            session.accept_recommended()
            return session.status()

        return call(run)

    @app.post("/api/approve")
    def approve(body: NoteIn) -> Any:
        return call(lambda: session.approve(body.note).to_dict())

    @app.post("/api/reject")
    def reject(body: NoteIn) -> Any:
        return call(lambda: session.reject(body.note).to_dict())

    @app.post("/api/feature")
    def feature(body: FeatureIn) -> Any:
        return call(lambda: session.feature(body.text, body.force).to_dict())

    @app.post("/api/checks/accept")
    def checks_accept() -> Any:
        return call(session.accept_checks)

    @app.post("/api/undo")
    def undo() -> Any:
        return call(lambda: {"restored": session.undo()})

    @app.post("/api/watch")
    def watch(body: WatchIn) -> Any:
        def run() -> dict[str, Any]:
            last, res = session.watch_tick(body.last_seen)
            if res is not None:
                last = res.next_packet.text if res.next_packet else res.repair_prompt or last
            return {"last_seen": last, "result": _apply(res) if res else None}

        return call(run)

    @app.get("/api/doctor")
    def doctor() -> Any:
        return [{"name": n, "ok": ok, "detail": d} for n, ok, d in session.doctor()]

    return app
