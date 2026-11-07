"""Textual TUI. A thin shell over Session: key bindings call facade methods, panels render status()."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.selection_list import Selection

from chatop.app.session import ApplyResult, Session, SessionError


class ChatopApp(App[None]):
    TITLE = "chatop"
    CSS = """
    #side { width: 38; border-right: solid $primary-background; padding: 0 1; }
    #status { height: auto; margin-bottom: 1; }
    #slices { height: 1fr; }
    TextArea { height: 1fr; }
    .qbox { border: round $primary; padding: 0 1; margin-bottom: 1; height: auto; }
    .qbox SelectionList { height: auto; max-height: 10; }
    #applybar { height: 3; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "next", "Next packet"),
        Binding("a", "apply_clip", "Apply clipboard"),
        Binding("w", "toggle_watch", "Watch"),
        Binding("y", "accept", "Accept recommended"),
        Binding("p", "approve", "Approve"),
        Binding("u", "undo", "Undo"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        super().__init__()
        self.session = session_factory()
        self.watching = False
        self.last_seen: str | None = None
        self._timer: Any = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="side"):
                yield Static(id="status")
                yield Static(id="slices")
            with TabbedContent(id="tabs"):
                with TabPane("Packet", id="tab-packet"):
                    yield TextArea("", read_only=True, id="packet")
                with TabPane("Reply", id="tab-reply"):
                    yield TextArea("", id="reply")
                    with Horizontal(id="applybar"):
                        yield Button("Apply pasted reply", variant="primary", id="btn-apply")
                        yield Button("Apply from clipboard", id="btn-apply-clip")
                with TabPane("Questions", id="tab-questions"):
                    yield VerticalScroll(id="questions")
                    yield Button("Submit answers + next packet", variant="primary", id="btn-answers")
                with TabPane("Evidence", id="tab-evidence"):
                    yield TextArea("", read_only=True, id="evidence")
                with TabPane("Log", id="tab-log"):
                    yield TextArea("", read_only=True, id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    # ---------------------------------------------------------------- helpers
    def _append_log(self, msg: str) -> None:
        log = self.query_one("#log", TextArea)
        log.load_text(log.text + msg.rstrip() + "\n")

    def _guard(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except SessionError as exc:
            self.notify(str(exc), severity="error", timeout=6)
            self._append_log(f"error: {exc}")
            return None

    def _show_packet(self, text: str, turn: int, tokens: int, copied: bool) -> None:
        self.query_one("#packet", TextArea).load_text(text)
        self.notify(f"turn {turn}: ~{tokens:,} tokens " + ("copied to clipboard" if copied else "(copy manually)"))

    def _show_apply(self, r: ApplyResult) -> None:
        if not r.ok:
            self.notify("Rejected; repair prompt copied. Paste it in the same chat.", severity="error", timeout=8)
            self._append_log("REJECTED:\n  " + "\n  ".join(r.errors))
        else:
            lines = [*r.changes]
            if r.red_ok is not None:
                lines.append(f"TDD red: {'proven' if r.red_ok else 'NOT proven'}")
            lines += [f"check {c.name}: {'PASS' if c.code == 0 else 'FAIL'}" for c in r.checks] + r.messages
            self._append_log("applied:\n  " + "\n  ".join(lines))
            if r.next_packet:
                p = r.next_packet
                self._show_packet(p.text, p.turn, p.tokens, p.copied)
        self.action_refresh()

    # ---------------------------------------------------------------- actions
    def action_refresh(self) -> None:
        info = self._guard(self.session.status)
        if info is None:
            self.query_one("#status", Static).update("not initialised: run `chatop init` first")
            return
        cur = info["slice"]
        self.query_one("#status", Static).update(
            f"[b]{info['project']}[/b]\ntrack  {info['track']}\nphase  {info['phase']}\nstatus {info['status']}\n"
            f"turn   {info['turn']}"
            + (f"\nslice  {cur['id']} (try {cur['attempts'] + 1})" if cur else "")
            + f"\nwatch  {'ON' if self.watching else 'off'}\n\n[i]{info['hint']}[/i]"
            + (f"\n\nproposed checks: {info['proposed_checks']}" if info["proposed_checks"] else "")
        )
        marks = {"done": "[green]✔[/green]", "active": "[yellow]▶[/yellow]", "todo": "·", "blocked": "[red]✖[/red]"}
        self.query_one("#slices", Static).update(
            "[b]Slices[/b]\n"
            + ("\n".join(f"{marks[s['status']]} {s['id']} {s['title']}" for s in info["slices"]) or "(none yet)")
        )
        self.query_one("#evidence", TextArea).load_text(info["evidence"] or "(none)")
        self._render_questions()

    def _render_questions(self) -> None:
        box = self.query_one("#questions", VerticalScroll)
        box.remove_children()
        for q in self.session.pending_questions():
            sel = SelectionList[str](
                *[
                    Selection(o + ("  ★ recommended" if o in q.recommended else ""), o, o in q.recommended)
                    for o in q.options
                ],
                id=f"sel-{q.id}",
            )
            box.mount(
                Vertical(
                    Label(f"[b]{q.id}[/b] {q.text} ({'pick any' if q.multi else 'pick one'})"),
                    sel,
                    Input(placeholder="other (free text)", id=f"other-{q.id}"),
                    classes="qbox",
                )
            )

    def action_next(self) -> None:
        p = self._guard(self.session.build_packet)
        if p is not None:
            self._show_packet(p.text, p.turn, p.tokens, p.copied)
            self.query_one("#tabs", TabbedContent).active = "tab-packet"
        self.action_refresh()

    def action_apply_clip(self) -> None:
        text = self.session.clipboard.paste()
        if not text:
            self.notify("clipboard empty", severity="warning")
            return
        r = self._guard(lambda: self.session.apply(text))
        if r is not None:
            self._show_apply(r)

    def action_accept(self) -> None:
        self._guard(self.session.accept_recommended)
        self.action_next()

    def action_approve(self) -> None:
        if self._guard(self.session.approve) is not None:
            self.action_next()

    def action_undo(self) -> None:
        restored = self._guard(self.session.undo)
        if restored is not None:
            self.notify("restored: " + ", ".join(restored))
        self.action_refresh()

    def action_toggle_watch(self) -> None:
        self.watching = not self.watching
        if self.watching:
            self.last_seen = self.session.clipboard.paste()
            self._timer = self.set_interval(1.0, self._tick)
            self.notify("watching clipboard: copy the LLM reply and it is applied automatically")
        elif self._timer is not None:
            self._timer.stop()
        self.action_refresh()

    def _tick(self) -> None:
        try:
            self.last_seen, r = self.session.watch_tick(self.last_seen)
        except SessionError as exc:
            self._append_log(f"watch: {exc}")
            return
        if r is not None:
            self.last_seen = r.next_packet.text if r.next_packet else r.repair_prompt or self.last_seen
            self._show_apply(r)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            text = self.query_one("#reply", TextArea).text
            r = self._guard(lambda: self.session.apply(text))
            if r is not None:
                self.query_one("#reply", TextArea).load_text("")
                self._show_apply(r)
        elif event.button.id == "btn-apply-clip":
            self.action_apply_clip()
        elif event.button.id == "btn-answers":
            for q in self.session.pending_questions():
                choices = list(self.query_one(f"#sel-{q.id}", SelectionList).selected)
                other = self.query_one(f"#other-{q.id}", Input).value
                try:
                    self.session.answer(q.id, choices, other)
                except SessionError as exc:
                    self.notify(str(exc), severity="error")
            self.action_next()
