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
    chat: str | None = None


class AcceptIn(BaseModel):
    chat: str | None = None


class PacketIn(BaseModel):
    chat: str | None = None
    full: bool = False


class PasteIn(BaseModel):
    text: str


class ChatIn(BaseModel):
    chat: str


class SentIn(BaseModel):
    chat: str
    sent: bool = True


class AssignIn(BaseModel):
    issue: str
    chat: str | None = None


class ConfigureIn(BaseModel):
    key: str
    value: str


class NoteIn(BaseModel):
    note: str = ""


class FeatureIn(BaseModel):
    text: str
    force: bool = False


class WatchIn(BaseModel):
    last_seen: str | None = None


def _packet(p: PacketResult) -> dict[str, Any]:
    return {
        "turn": p.turn,
        "text": p.text,
        "tokens": p.tokens,
        "notes": p.notes,
        "copied": p.copied,
        "chat": p.chat,
        "kind": p.kind,
        "full_tokens": p.full_tokens or p.tokens,
    }


def _apply(r: ApplyResult) -> dict[str, Any]:
    d = asdict(r)
    d["checks"] = [{"name": c.name, "code": c.code, "seconds": c.seconds} for c in r.checks]
    d["next_packet"] = _packet(r.next_packet) if r.next_packet else None
    return d


def create_app(session_factory: Callable[[], Session]) -> FastAPI:
    app = FastAPI(title="chatop", docs_url="/api/docs")
    session = session_factory()
    lock = threading.Lock()
    jobs: dict[str, dict[str, Any]] = {}  # job id -> {id, chat, status, result, error}
    jobs_lock = threading.Lock()

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
            session.answer(body.qid, body.choices, body.other, body.chat)
            return session.status()

        return call(run)

    @app.post("/api/accept")
    def accept(body: AcceptIn | None = None) -> Any:
        def run() -> Any:
            session.accept_recommended(body.chat if body else None)
            return session.status()

        return call(run)

    # ---- parallel relay: the board is read without the UI lock so it stays live while an apply runs checks
    @app.get("/api/board")
    def board() -> Any:
        try:
            data = session.board()
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        with jobs_lock:
            data["jobs"] = list(jobs.values())[-20:]
        return data

    @app.post("/api/dispatch")
    def dispatch() -> Any:
        return call(lambda: [asdict(a) for a in session.dispatch()])

    @app.post("/api/packet")
    def packet(body: PacketIn) -> Any:
        return call(lambda: _packet(session.build_packet(chat=body.chat, full=body.full)))

    @app.post("/api/paste")
    def paste(body: PasteIn) -> Any:
        """Route a pasted reply to its chat and apply it in the background; poll /api/board (or /api/job/ID)."""
        if not session.in_lane_mode():
            return call(lambda: _apply(session.apply(body.text)))
        routed = session.route(body.text)
        if not routed.ok:
            return call(lambda: {**_apply(session.apply(body.text)), "job": None})
        with jobs_lock:
            job: dict[str, Any] = {
                "id": f"j{len(jobs) + 1}",
                "chat": routed.chat,
                "status": "running",
                "result": None,
                "error": "",
            }
            jobs[job["id"]] = job

        def work() -> None:
            try:
                res = _apply(session.apply(body.text))
                with jobs_lock:
                    job.update(status="done", result=res)
            except Exception as exc:
                with jobs_lock:
                    job.update(status="error", error=str(exc))

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "chat": routed.chat, "job": job["id"]}

    @app.get("/api/job/{job_id}")
    def job(job_id: str) -> Any:
        with jobs_lock:
            if job_id not in jobs:
                raise HTTPException(status_code=404, detail="no such job")
            return jobs[job_id]

    @app.post("/api/chat/reset")
    def chat_reset(body: ChatIn) -> Any:
        def run() -> dict[str, Any]:
            session.reset_chat(body.chat)
            return session.board()

        return call(run)

    @app.post("/api/chat/sent")
    def chat_sent(body: SentIn) -> Any:
        def run() -> dict[str, Any]:
            session.mark_sent(body.chat, body.sent)
            return session.board()

        return call(run)

    @app.post("/api/assign")
    def assign(body: AssignIn) -> Any:
        return call(lambda: asdict(session.assign(body.issue, body.chat)))

    @app.post("/api/configure")
    def configure(body: ConfigureIn) -> Any:
        return call(lambda: session.configure(body.key, body.value))

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
