"""Parallel relay: several chat windows ("lanes"), each working one issue at a time.

The human relays between chat windows and chatop. chatop

* turns the plan into issues and hands each ready issue to a chat (reusing a chat that already holds the right files),
* builds a FULL bootstrap packet for a new chat and a small DELTA packet for a continuing one,
* routes every pasted reply to its chat by the ``<<<CHATOP chat=cN turn=N>>>`` header, whatever order they arrive in,
* applies each reply to the lane's own uncommitted *overlay* so one chat's failing code never breaks another chat's
  checks, lints every generated file in one shot, runs the checks, commits when green, and
* records events ("chat c2 is ready") that the UIs show.

All tree-touching work is serialised by the session's ``_apply_lock``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from chatop.app.prompts import PHASE_DOCS, template
from chatop.app.recon import fence, list_files
from chatop.app.results import ApplyResult, PacketResult, SessionError
from chatop.domain.changes import FileChange, plan_changes
from chatop.domain.delta import digest, plan_delta
from chatop.domain.models import SENDABLE, Chat, ChatStatus, Phase, Question, Slice, State, Status, Track
from chatop.domain.packet import Section, assemble, estimate_tokens
from chatop.domain.reply import Reply, envelope_header, parse_reply
from chatop.domain.scheduler import choose_chat, pick_dispatch
from chatop.domain.stage import owner_of, stage_of, summarize
from chatop.domain.tdd import judge_slice

if TYPE_CHECKING:
    from chatop.app.session import Session

MAX_EVENTS = 200
Reader = Callable[[str], str | None]
Overlay = dict[str, dict[str, str | None]]


@dataclass
class Assignment:
    chat: str
    issue: str
    reused: bool


@dataclass
class Route:
    ok: bool
    chat: str | None
    error: str = ""


class LaneEngine:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ------------------------------------------------------------------ small helpers
    @property
    def st(self) -> State:
        return self.s.state

    def _event(self, kind: str, chat: str | None, issue: str | None, text: str) -> None:
        st = self.st
        st.event_seq += 1
        st.events.append(
            {
                "seq": st.event_seq,
                "ts": time.strftime("%H:%M:%S"),
                "kind": kind,
                "chat": chat,
                "issue": issue,
                "text": text,
            }
        )
        del st.events[:-MAX_EVENTS]

    def _view(self, chat: str) -> Reader:
        """What this chat believes the tree looks like: its uncommitted overlay on top of the working tree."""
        overlay = self.s.ws.load_overlay(chat)
        ws = self.s.ws

        def read(path: str) -> str | None:
            return overlay[path]["after"] if path in overlay else ws.read(path)

        return read

    def _save(self) -> None:
        self.s._save(self.st)

    def events_since(self, seq: int) -> list[dict[str, Any]]:
        return [e for e in self.st.events if e["seq"] > seq]

    # ------------------------------------------------------------------ dispatch: issues -> chats
    def dispatch(self) -> list[Assignment]:
        s, st, cfg = self.s, self.st, self.s.config
        if not cfg.auto_commit:
            raise SessionError(
                "parallel chats need auto_commit = true: each finished issue is committed so lanes stay isolated"
            )
        if st.phase != Phase.SLICE:
            raise SessionError(f"dispatch is for the slice phase (current phase: {st.phase})")
        out: list[Assignment] = []
        with s._state_lock:
            cur = st.slice(st.current_slice)
            if cur is not None and cur.status == "active" and cur.lane is None:
                out.append(self._assign(cur))  # a serial issue becomes a lane
            st.current_slice = None
            st.status = Status.READY
            active = [x for x in st.slices if x.status == "active"]
            capacity = max(0, cfg.max_parallel - len(active))
            out += [self._assign(issue) for issue in pick_dispatch(st.slices, active, capacity)]
            if out:
                self._save()
        return out

    def assign(self, issue_id: str, chat_id: str | None = None) -> Assignment:
        """Manual override: give a specific issue to a specific free chat (or a new one)."""
        st = self.st
        issue = st.slice(issue_id)
        if issue is None or issue.status not in ("todo", "blocked"):
            raise SessionError(f"issue {issue_id} cannot be assigned (status: {issue.status if issue else 'unknown'})")
        waiting = [d for d in issue.depends if (st.slice(d) is None or st.slice(d).status != "done")]  # type: ignore[union-attr]
        if waiting:
            raise SessionError(f"issue {issue_id} waits for {', '.join(waiting)}")
        chat = None
        if chat_id is not None:
            chat = st.chat(chat_id)
            if chat is None or chat.status != ChatStatus.DONE:
                raise SessionError(f"chat {chat_id} is not free (only finished chats can take a new issue)")
        with self.s._state_lock:
            result = self._assign(issue, chat)
            self._save()
        return result

    def _assign(self, issue: Slice, chat: Chat | None = None) -> Assignment:
        st, cfg = self.st, self.s.config
        if chat is None and cfg.delta_packets:
            chat = choose_chat(issue, st.chats, cfg.max_issues_per_chat)
        reused = chat is not None
        if chat is None:
            chat = Chat(id=f"c{len(st.chats) + 1}", status=ChatStatus.QUEUED)
            st.chats.append(chat)
        else:
            chat.status = ChatStatus.READY
        chat.issue, chat.title = issue.id, f"{issue.id} · {issue.title}"
        chat.evidence, chat.note, chat.needs, chat.questions = "", "", [], []
        issue.status, issue.lane = "active", chat.id
        how = "continues in the same chat (delta packet)" if reused else "opens a new chat (full packet)"
        self._event("ready", chat.id, issue.id, f"{issue.id} {how}")
        return Assignment(chat.id, issue.id, reused)

    def next_up(self) -> str | None:
        """The chat the human should relay to next: one whose packet is ready to copy."""
        ready = [c for c in self.st.chats if c.status in SENDABLE]
        ready.sort(key=lambda c: (c.status != ChatStatus.READY, c.id))  # warm chats before brand-new ones
        return ready[0].id if ready else None

    # ------------------------------------------------------------------ outbound packets
    def packet(self, chat_id: str | None, copy: bool, full: bool) -> PacketResult:
        s = self.s
        with s._apply_lock:
            st = self.st
            if chat_id is None:
                if s.config.auto_dispatch and st.phase == Phase.SLICE:
                    self.dispatch()
                chat_id = self.next_up() or self._first_status(ChatStatus.AWAITING_REPLY)
                if chat_id is None:
                    raise SessionError(self._idle_reason())
            chat = st.chat(chat_id)
            if chat is None:
                raise SessionError(f"unknown chat {chat_id} (known: {', '.join(c.id for c in st.chats) or 'none'})")
            if chat.status == ChatStatus.NEEDS_INPUT:
                raise SessionError(f"chat {chat.id} has unanswered questions (chatop answer --chat {chat.id} / accept)")
            if chat.status == ChatStatus.BLOCKED:
                raise SessionError(
                    f"chat {chat.id} is blocked after {s.config.max_attempts} failed attempts; "
                    f"decide, then `chatop reset-chat {chat.id}`"
                )
            if chat.status == ChatStatus.APPLYING:
                raise SessionError(f"chat {chat.id} is being applied right now")
            if chat.status == ChatStatus.DONE or chat.issue is None:
                raise SessionError(f"chat {chat.id} is free: no issue assigned (run `chatop dispatch`)")
            with s._state_lock:
                result = self._build(chat, full)
                self._save()
            if copy:
                result.copied = s.clipboard.copy(result.text)
            return result

    def _first_status(self, status: ChatStatus) -> str | None:
        return next((c.id for c in self.st.chats if c.status == status), None)

    def _idle_reason(self) -> str:
        st = self.st
        if not st.chats:
            return "no issue is ready to dispatch (waiting on dependencies, or nothing planned)"
        by = {c.status for c in st.chats}
        if ChatStatus.NEEDS_INPUT in by:
            return "chats are waiting for your answers (chatop answer / accept)"
        if ChatStatus.BLOCKED in by:
            return "blocked chats need a decision (chatop reset-chat <chat>)"
        return "nothing to send: every chat is waiting for its reply, or no issue is ready"

    def _build(self, chat: Chat, full: bool) -> PacketResult:
        s, st, cfg = self.s, self.st, self.s.config
        name = f"{chat.id}-turn-{chat.turn:04d}"
        if chat.status == ChatStatus.AWAITING_REPLY and not full:  # idempotent resend
            saved = s.ws.read_named("packets", name)
            if saved is not None:
                tokens = estimate_tokens(saved)
                return PacketResult(
                    chat.turn,
                    saved,
                    tokens,
                    [],
                    s.ws.dir / "packets" / f"{name}.md",
                    False,
                    chat.id,
                    chat.packet_kind or "full",
                    chat.packet_full_tokens or tokens,
                )
        fresh = chat.status in SENDABLE
        kind = (
            "full"
            if (chat.status == ChatStatus.QUEUED or chat.force_full or full or not cfg.delta_packets)
            else "delta"
        )
        if fresh:
            chat.turn += 1
            chat.status = ChatStatus.AWAITING_REPLY
            chat.sent_at = None
            name = f"{chat.id}-turn-{chat.turn:04d}"
        if s.index.available():
            s.index.ensure_index()
        sections, full_sections, new_seen, notes = self._sections(chat, kind)
        text, cut = assemble(sections, cfg.budget_tokens)
        full_text = text if kind == "full" else assemble(full_sections, cfg.budget_tokens)[0]
        tokens, full_tokens = estimate_tokens(text), estimate_tokens(full_text)
        path = s.ws.save_named("packets", name, text)
        chat.seen = chat.seen | new_seen
        chat.decisions_sent = len(st.decisions)
        chat.force_full = False
        chat.packet_kind, chat.packet_full_tokens = kind, full_tokens
        if fresh:
            chat.tokens_sent += tokens
            chat.tokens_full += full_tokens
        return PacketResult(chat.turn, text, tokens, [*notes, *cut], path, False, chat.id, kind, full_tokens)

    def _sections(self, chat: Chat, kind: str) -> tuple[list[Section], list[Section], dict[str, str], list[str]]:
        """(sections to send, sections of the equivalent full packet, new ``seen`` digests, notes)."""
        s, st, cfg = self.s, self.st, self.s.config
        issue = st.slice(chat.issue)
        assert issue is not None
        read = self._view(chat.id)
        header = f"<<<CHATOP chat={chat.id} turn={chat.turn}>>>"
        checks = ", ".join(f"`{k}`" for k in cfg.checks) or "(none configured yet)"
        common: dict[str, Any] = {
            "project": s.ws.root.name,
            "turn": chat.turn,
            "track": st.track.value,
            "phase": Phase.SLICE.value,
            "checks": checks,
            "protected": ", ".join(f"`{p}`" for p in cfg.protected),
            "max_questions": cfg.max_questions,
            "max_rounds": cfg.max_refine_rounds,
            "round": 1,
            "brief": "PLAN.md",
            "track_notes": "",
            "header": header,
            "slice_id": issue.id,
            "slice_title": issue.title,
            "slice_goal": issue.goal or issue.title,
            "slice_acceptance": ", ".join(issue.acceptance) or "(see PLAN)",
            "attempt": issue.attempts + 1,
            "red_note": "(Characterization tests that pin existing behavior may pass immediately; then add @@advance.)"
            if st.track == Track.AUDIT
            else "",
        }
        task_key = f"task:{issue.id}"
        task_sig = digest(f"{issue.goal}|{issue.title}|{issue.acceptance}|{issue.touches}")
        task_known = chat.seen.get(task_key) == task_sig
        task_body = template("slice").safe_substitute(common)
        short_task = (
            f"Continue issue **{issue.id}** ({issue.title}), attempt {issue.attempts + 1}. Same task as before."
        )

        # keyed context: what a continuing chat may already hold
        keyed: dict[str, tuple[str, str, int]] = {"state": ("State", self._digest(chat), 0)}
        for doc, prio in PHASE_DOCS[Phase.SLICE]:
            body = s.ws.read(doc)
            if body:
                keyed[f"doc:{doc}"] = (f"Doc: {doc}", fence(body, "markdown"), prio)
        code = s._slice_items(issue, read)
        for key, body in code.items():
            keyed[key] = (f"Code: {key.split(':', 1)[1]}", body, 2)
        tree = s.index.files(3) if s.index.available() else ""
        keyed["repomap"] = ("Repo map", fence(tree or "\n".join(list_files(s.ws, s.vcs)[:300])), 6)
        current = {k: v[1] for k, v in keyed.items()}
        delta = plan_delta(chat.seen if kind == "delta" else {}, current)

        decisions_all = st.decisions[-30:]
        decisions_new = st.decisions[chat.decisions_sent :] if kind == "delta" else decisions_all
        always = [
            Section("Evidence (from chatop's last run)", chat.evidence, 1),
            Section("Human input", self._human(chat, kind), 0),
            Section(
                "Requested context (your @@need lines)", s._resolve_needs(chat.needs, read) if chat.needs else "", 1
            ),
        ]

        def build(keys: list[str], is_full: bool) -> list[Section]:
            secs: list[Section] = []
            label = "full" if is_full else "delta"
            title = f"# CHATOP PACKET · project `{s.ws.root.name}` · chat {chat.id} · turn {chat.turn} · {label}"
            if is_full:
                secs.append(
                    Section(
                        "Role and rules",
                        template("system")
                        .safe_substitute(common)
                        .replace(template("system").safe_substitute(common).split("\n", 1)[0], title, 1),
                        0,
                    )
                )
            else:
                secs.append(
                    Section(
                        "Continuation",
                        f"{title}\n\nYou are continuing this chat. Rules and reply format are unchanged. "
                        f"Start your reply with `{header}`.",
                        0,
                    )
                )
            secs.append(Section(f"Your task: {issue.id}", task_body if (is_full or not task_known) else short_task, 0))
            if is_full:
                secs.append(Section("Reply contract", template("contract").safe_substitute(common), 0))
            wanted = [(k, keyed[k]) for k in keys]
            secs += [Section(t, b, p) for k, (t, b, p) in wanted if k == "state"]
            secs.append(
                Section("Decisions", "\n".join(f"- {d}" for d in (decisions_all if is_full else decisions_new)), 0)
            )
            secs += always
            secs += [Section(t, b, p) for k, (t, b, p) in wanted if k.startswith("doc:")]
            code_parts = [(k, b) for k, (_, b, _) in wanted if k.startswith(("file:", "symbol:"))]
            if code_parts:
                head = f"Issue `{issue.id}` touches: {', '.join(issue.touches) or '(unspecified)'}"
                secs.append(
                    Section(f"Code context for {issue.id}", "\n\n".join([head, *[b for _, b in code_parts]]), 2)
                )
            secs += [Section(t, b, p) for k, (t, b, p) in wanted if k == "repomap"]
            if not is_full and delta.unchanged:
                secs.append(
                    Section(
                        "Already in your context",
                        (
                            "Sent earlier in this chat and unchanged, so not repeated: "
                            + ", ".join(f"`{k}`" for k in delta.unchanged)
                            + ". These are already in your context."
                        ),
                        0,
                    )
                )
            return secs

        notes: list[str] = []
        if kind == "delta" and delta.unchanged:
            notes.append(f"delta: {len(delta.unchanged)} unchanged context item(s) not resent")
        sections = build(delta.changed if kind == "delta" else list(keyed), kind == "full")
        full_sections = build(list(keyed), True)
        new_seen = dict(delta.new_seen)
        new_seen[task_key] = task_sig
        return sections, full_sections, new_seen, notes

    def _digest(self, chat: Chat) -> str:
        st = self.st
        done = [x for x in st.slices if x.status == "done"]
        out = [
            f"- track **{st.track.value}**, phase **slice**; you are chat **{chat.id}**; "
            f"issues {len(done)}/{len(st.slices)} done"
        ]
        out += ["", "| id | status | chat | depends | title |", "|---|---|---|---|---|"]
        out += [
            f"| {x.id} | {x.status} | {x.lane or ''} | {', '.join(x.depends)} | {x.title} |"
            for x in st.slices
            if x.status != "done"
        ]
        if done:
            out.append(f"| … | done | | | {len(done)} finished issue(s): {', '.join(x.id for x in done[-12:])} |")
        return "\n".join(out)

    def _human(self, chat: Chat, kind: str) -> str:
        parts: list[str] = []
        answered = [q for q in chat.questions if q.answered]
        if answered:
            parts.append("Answers to your questions:")
            for q in answered:
                ans = ", ".join(q.answer or []) or "(none of the options)"
                extra = f' + other: "{q.other.strip()}"' if q.other.strip() else ""
                parts.append(f"- **{q.id}** {q.text} → {ans}{extra}")
        if chat.note:
            parts.append(chat.note)
        if kind == "full" and self.st.human_note:
            parts.append(self.st.human_note)
        return "\n".join(parts)

    # ------------------------------------------------------------------ inbound replies
    def route(self, text: str) -> Route:
        st = self.st
        head = envelope_header(text)
        if head is None:
            return Route(False, None, "No <<<CHATOP chat=cN turn=N>>> block found in what you pasted.")
        chat_id, turn = head
        if chat_id is not None:
            if st.chat(chat_id) is None:
                known = ", ".join(c.id for c in st.chats) or "none"
                return Route(False, None, f"unknown chat {chat_id} (known chats: {known})")
            return Route(True, chat_id)
        waiting = [c for c in st.chats if c.status == ChatStatus.AWAITING_REPLY]
        if len(waiting) == 1:
            return Route(True, waiting[0].id)
        if not waiting:
            return Route(False, None, "No chat is waiting for a reply. Copy a packet first (`chatop next`).")
        same_turn = [c for c in waiting if turn is not None and c.turn == turn]
        if len(same_turn) == 1:
            return Route(True, same_turn[0].id)
        ids = ", ".join(c.id for c in waiting)
        return Route(False, None, f"The reply has no chat=… in its header and several chats are waiting ({ids}).")

    def apply(self, text: str, force: bool = False) -> ApplyResult:
        s = self.s
        routed = self.route(text)
        if not routed.ok or routed.chat is None:
            return self._unrouted(routed.error)
        with s._apply_lock:
            st = self.st
            chat = st.chat(routed.chat)
            assert chat is not None
            reply = parse_reply(text)
            errors = list(reply.errors)
            if not force and chat.status != ChatStatus.AWAITING_REPLY:
                errors.insert(
                    0, f"chat {chat.id} is not waiting for a reply (status: {chat.status}); build its packet first"
                )
            if not force and reply.turn is not None and reply.turn != chat.turn:
                errors.insert(
                    0, f"reply is for turn {reply.turn} but chat {chat.id} is on turn {chat.turn} (stale paste?)"
                )
            issue = st.slice(chat.issue)
            if issue is None:
                errors.insert(0, f"chat {chat.id} has no open issue")
            if issue is None or (errors and not force):
                return self._reject(chat, text, errors)
            overlay = s.ws.load_overlay(chat.id)
            changes, change_errors = plan_changes(reply, self._view(chat.id), s.config.protected)
            errors += change_errors
            errors += s._syntax_errors(changes)  # every file at once
            errors += self._conflicts(chat, overlay)
            if errors:
                return self._reject(chat, text, errors)
            with s._state_lock:
                chat.status = ChatStatus.APPLYING
                self._save()
            try:
                return self._apply_checked(chat, issue, reply, text, changes, overlay)
            except BaseException:
                with s._state_lock:  # never leave a chat stuck in APPLYING
                    chat.status = ChatStatus.AWAITING_REPLY
                    self._save()
                raise

    def _conflicts(self, chat: Chat, overlay: Overlay) -> list[str]:
        """Files this chat edited earlier that another chat has since committed a change to."""
        ws = self.s.ws
        stale = [p for p, e in overlay.items() if ws.read(p) != e["base"]]
        if not stale:
            return []
        for p in stale:
            del overlay[p]
            chat.seen.pop(f"file:{p}", None)
        ws.save_overlay(chat.id, overlay)
        return [
            f"{p} was changed by another chat after you started editing it; your uncommitted version was dropped. "
            f"Use `@@need file {p}` or resend the whole file."
            for p in stale
        ]

    def _apply_checked(
        self, chat: Chat, issue: Slice, reply: Reply, text: str, changes: list[FileChange], overlay: Overlay
    ) -> ApplyResult:
        s, st, cfg = self.s, self.st, self.s.config
        s.ws.save_named("replies", f"{chat.id}-turn-{chat.turn:04d}", text)
        result = ApplyResult(ok=True, chat=chat.id)
        tests = [c for c in changes if c.role == "test"]
        code = [c for c in changes if c.role == "code"]
        changed = {c.path for c in changes}
        affected = sorted(set(overlay) | changed)
        tree_before = {p: s.ws.read(p) for p in affected}
        new_overlay: Overlay = {k: dict(v) for k, v in overlay.items()}
        for c in changes:
            base = new_overlay[c.path]["base"] if c.path in new_overlay else tree_before[c.path]
            new_overlay[c.path] = {"base": base, "after": c.after}

        def restore() -> None:
            for p in affected:
                s.ws.write(p, tree_before[p])

        for p, e in overlay.items():  # earlier uncommitted work of this chat joins the tree for the checks
            if p not in changed:
                s.ws.write(p, e["after"])
        try:
            stage_errors, result.red_ok = s._stage(changes, {"files": {}}, result, tdd_red=bool(tests and code))
            if stage_errors:
                restore()
                return self._reject(chat, text, stage_errors, applying=True)
            result.checks = s._run_checks(list(cfg.checks))
            touched = bool(tests or code or reply.writes or reply.edits)
            verdict = judge_slice(
                strict=cfg.tdd_strict and st.track != Track.AUDIT,
                red_ok=result.red_ok,
                red_already=issue.red_proven,
                check_codes=[c.code for c in result.checks],
                has_tests=bool(tests),
                has_code=bool(code),
                advance=reply.advance,
                touched=touched,
            )
            sha: str | None = None
            if verdict.done:
                sha = s.vcs.commit_all(f"chatop({issue.id}): {issue.title}\n\n{reply.summary}")
                new_overlay = {}
            else:
                restore()
        except BaseException:
            restore()
            raise
        s.ws.save_overlay(chat.id, new_overlay)
        if changes and verdict.done and s.index.available():
            s.index.ensure_index()
        with s._state_lock:
            self._record(
                chat, issue, reply, changes, result, verdict.done, verdict.notes, verdict.red_proven, touched, sha
            )
            self._save()
        s.ws.journal(
            {
                "event": "apply",
                "chat": chat.id,
                "turn": chat.turn,
                "issue": issue.id,
                "summary": reply.summary,
                "changes": result.changes,
                "checks": {c.name: c.code for c in result.checks},
                "red_ok": result.red_ok,
                "slice_done": result.slice_done,
                "status": chat.status.value,
            }
        )
        result.status = chat.status.value
        if st.proposed_checks:
            result.messages.append(
                "LLM proposed checks (accept with `chatop checks --accept`): "
                + "; ".join(f"{k} = {v}" for k, v in st.proposed_checks.items())
            )
        idle = not any(c.status in (ChatStatus.AWAITING_REPLY, ChatStatus.APPLYING) for c in st.chats)
        if cfg.auto_next and idle and self.next_up() is not None:
            result.next_packet = self.packet(None, True, False)  # nobody else is mid-flight: the clipboard is free
        return result

    def _record(
        self,
        chat: Chat,
        issue: Slice,
        reply: Reply,
        changes: list[FileChange],
        result: ApplyResult,
        done: bool,
        notes: list[str],
        red_proven: bool,
        touched: bool,
        sha: str | None,
    ) -> None:
        s, st, cfg = self.s, self.st, self.s.config
        st.decisions += [d for d in reply.decisions if d not in st.decisions]
        st.proposed_checks |= reply.checks
        st.history.append(f"{chat.id} T{chat.turn} {issue.id}: {reply.summary or '(no summary)'}")
        chat.last_summary = reply.summary
        chat.repair, chat.sent_at = "", None
        chat.questions, chat.needs = reply.questions, reply.needs
        chat.last_result = [*result.changes, *[f"{c.name}: {'PASS' if c.code == 0 else 'FAIL'}" for c in result.checks]]
        self._remember_files(chat, changes)
        issue.red_proven = issue.red_proven or red_proven
        if done:
            result.slice_done = True
            result.messages.append(f"issue {issue.id} complete in {chat.id}" + (f", committed {sha}" if sha else ""))
            issue.status, issue.lane = "done", None
            chat.issues_done.append(issue.id)
            chat.issue, chat.status = None, ChatStatus.DONE
            chat.evidence, chat.questions, chat.needs = "", [], []
            self._event("done", chat.id, issue.id, f"{issue.id} done" + (f" ({sha})" if sha else ""))
            self._after_done()
            return
        if touched:
            issue.attempts += 1
        chat.evidence = "\n\n".join([*notes, s._format_checks(result.checks)])
        if issue.attempts >= cfg.max_attempts and touched:
            chat.status, issue.status = ChatStatus.BLOCKED, "blocked"
            self._event(
                "blocked",
                chat.id,
                issue.id,
                f"{issue.id} failed {issue.attempts} attempts; decide how to proceed, then reset chat {chat.id}",
            )
        elif any(not q.answered for q in chat.questions):
            chat.status = ChatStatus.NEEDS_INPUT
            self._event(
                "question",
                chat.id,
                issue.id,
                f"chat {chat.id} has {len([q for q in chat.questions if not q.answered])} question(s)",
            )
        else:
            chat.status = ChatStatus.READY
            self._event("ready", chat.id, issue.id, f"chat {chat.id} replied: next packet ready")

    def _remember_files(self, chat: Chat, changes: list[FileChange]) -> None:
        """The chat wrote these files itself, so a delta packet must not send them back."""
        s = self.s
        read = self._view(chat.id)
        docs = {d for d, _ in PHASE_DOCS[Phase.SLICE]}
        for c in changes:
            if c.path in docs:
                body = read(c.path)
                if body:
                    chat.seen[f"doc:{c.path}"] = digest(fence(body, "markdown"))
            elif c.after is not None:
                chat.seen[f"file:{c.path}"] = digest(s._file_block(c.path, read=read))

    def _after_done(self) -> None:
        st = self.st
        if all(x.status == "done" for x in st.slices):
            st.phase, st.status, st.current_slice = Phase.DONE, Status.DONE, None
            self._event("finished", None, None, "all issues are done")
            return
        if self.s.config.auto_dispatch:
            self.dispatch()

    def _reject(self, chat: Chat, text: str, errors: list[str], applying: bool = False) -> ApplyResult:
        s = self.s
        name = f"{chat.id}-turn-{chat.turn:04d}"
        s.ws.save_named("replies", name, text)
        bullet = "\n".join(f"- {e}" for e in errors)
        repair = (
            f"chatop could not apply your reply for chat {chat.id}, turn {chat.turn}. Nothing was changed.\n\n"
            f"Problems:\n{bullet}\n\n"
            "Resend the COMPLETE corrected reply as one block starting with "
            f"`<<<CHATOP chat={chat.id} turn={chat.turn}>>>` "
            "and ending with `<<<END>>>`, inside a ````chatop fence. For SEARCH mismatches, use @@file to rewrite the "
            "file, or @@need file <path> to see the current content."
        )
        copied = s.clipboard.copy(repair)
        with s._state_lock:
            chat.repair, chat.sent_at = repair, None  # the repair prompt still has to be pasted
            if applying:
                chat.status = ChatStatus.AWAITING_REPLY
            self._event(
                "rejected",
                chat.id,
                chat.issue,
                f"reply for {chat.id} was rejected ({len(errors)} problem(s)); repair prompt ready",
            )
            self._save()
        s.ws.journal({"event": "reject", "chat": chat.id, "turn": chat.turn, "errors": errors})
        return ApplyResult(
            ok=False,
            errors=errors,
            repair_prompt=repair,
            status=chat.status.value,
            chat=chat.id,
            messages=["repair prompt copied to clipboard" if copied else "repair prompt ready"],
        )

    def _unrouted(self, error: str) -> ApplyResult:
        s, st = self.s, self.st
        waiting = [c for c in st.chats if c.status == ChatStatus.AWAITING_REPLY]
        example = waiting[0] if waiting else None
        ex = f"<<<CHATOP chat={example.id} turn={example.turn}>>>" if example else "<<<CHATOP chat=c1 turn=1>>>"
        repair = (
            f"chatop could not route your reply: {error}\n\n"
            "Resend the COMPLETE reply starting with the header copied from "
            f"the packet, for example `{ex}`, and ending with `<<<END>>>`."
        )
        s.clipboard.copy(repair)
        return ApplyResult(
            ok=False, errors=[error], repair_prompt=repair, messages=["repair prompt copied to clipboard"]
        )

    # ------------------------------------------------------------------ human answers, resets
    def pending_questions(self, chat: str | None = None) -> list[Question]:
        chats = [c for c in self.st.chats if chat is None or c.id == chat]
        return [q for c in chats for q in c.questions if not q.answered]

    def answer(self, qid: str, choices: list[str], other: str, chat: str | None) -> None:
        owners = [c for c in self.st.chats if (chat is None or c.id == chat) and any(q.id == qid for q in c.questions)]
        if len(owners) != 1:
            raise SessionError(
                f"no pending question {qid}" if not owners else f"question {qid} exists in several chats; pass --chat"
            )
        c = owners[0]
        q = next(q for q in c.questions if q.id == qid)
        q.answer, q.other = choices, other
        self._after_answers(c)

    def accept_recommended(self, chat: str | None) -> None:
        chats = [c for c in self.st.chats if (chat is None or c.id == chat) and c.status == ChatStatus.NEEDS_INPUT]
        if chat is not None and self.st.chat(chat) is None:
            raise SessionError(f"unknown chat {chat}")
        for c in chats:
            for q in c.questions:
                if not q.answered:
                    q.answer = list(q.recommended) or q.options[:1]
            self._after_answers(c)

    def _after_answers(self, chat: Chat) -> None:
        with self.s._state_lock:
            if chat.status == ChatStatus.NEEDS_INPUT and all(q.answered for q in chat.questions):
                chat.status = ChatStatus.READY
                self._event("ready", chat.id, chat.issue, f"chat {chat.id}: answers recorded, next packet ready")
            self._save()

    def mark_sent(self, chat_id: str, sent: bool = True) -> None:
        """The human confirms they pasted the packet (or repair prompt) into the chat window, or takes it back."""
        chat = self.st.chat(chat_id)
        if chat is None:
            raise SessionError(f"unknown chat {chat_id}")
        if chat.status != ChatStatus.AWAITING_REPLY:
            raise SessionError(f"chat {chat_id} has no packet out (status: {chat.status}); copy its packet first")
        with self.s._state_lock:
            chat.sent_at = time.time() if sent else None
            self._save()

    def reset_chat(self, chat_id: str) -> None:
        """The human opened a fresh browser tab or decided how to unblock: the next packet carries everything."""
        st = self.st
        chat = st.chat(chat_id)
        if chat is None:
            raise SessionError(f"unknown chat {chat_id}")
        with self.s._state_lock:
            chat.seen, chat.force_full, chat.repair, chat.sent_at = {}, True, "", None
            issue = st.slice(chat.issue)
            if issue is not None and chat.status in (
                ChatStatus.BLOCKED,
                ChatStatus.NEEDS_INPUT,
                ChatStatus.AWAITING_REPLY,
            ):
                issue.status, issue.attempts = "active", 0
                chat.status = ChatStatus.READY
                chat.evidence = chat.evidence or ""
            self._event("ready", chat.id, chat.issue, f"chat {chat.id} reset: next packet is a full one")
            self._save()

    # ------------------------------------------------------------------ the board (what the UIs render)
    def board(self) -> dict[str, Any]:
        s, st, cfg = self.s, self.st, self.s.config
        with s._state_lock:
            chats = [self._chat_view(c) for c in st.chats]
            issues = [
                {
                    "id": x.id,
                    "title": x.title,
                    "status": x.status,
                    "depends": x.depends,
                    "touches": x.touches,
                    "chat": x.lane,
                    "attempts": x.attempts,
                    "waiting_on": [d for d in x.depends if (st.slice(d) is None or st.slice(d).status != "done")],  # type: ignore[union-attr]
                }
                for x in st.slices
            ]
            nxt = self.next_up()
            nxt_chat = st.chat(nxt) if nxt else None
            sent, full = sum(c.tokens_sent for c in st.chats), sum(c.tokens_full for c in st.chats)
            return {
                "mode": "parallel" if (st.chats or cfg.max_parallel > 1) else "serial",
                "phase": st.phase.value,
                "status": st.status.value,
                "max_parallel": cfg.max_parallel,
                "chats": chats,
                "issues": issues,
                "next_up": None
                if nxt_chat is None
                else {
                    "chat": nxt_chat.id,
                    "issue": nxt_chat.issue,
                    "kind": "full" if (nxt_chat.status == ChatStatus.QUEUED or nxt_chat.force_full) else "delta",
                },
                "tokens": {"sent": sent, "full": full, "saved": max(0, full - sent)},
                "summary": summarize(
                    [stage_of(c.status, c.sent_at, c.repair) for c in st.chats],
                    sum(1 for x in st.slices if x.status == "done"),
                    len(st.slices),
                ),
                "event_seq": st.event_seq,
                "events": st.events[-40:],
                "hint": self._hint(nxt_chat),
            }

    def _chat_view(self, c: Chat) -> dict[str, Any]:
        issue = self.st.slice(c.issue)
        stage = stage_of(c.status, c.sent_at, c.repair)
        return {
            "id": c.id,
            "title": c.title,
            "issue": c.issue,
            "status": c.status.value,
            "turn": c.turn,
            "issue_status": issue.status if issue else None,
            "attempts": issue.attempts if issue else 0,
            "can_send": c.status in SENDABLE,
            "kind": "full" if (c.status == ChatStatus.QUEUED or c.force_full) else "delta",
            "tokens_sent": c.tokens_sent,
            "tokens_full": c.tokens_full,
            "issues_done": list(c.issues_done),
            "last_summary": c.last_summary,
            "last_result": list(c.last_result),
            "repair": c.repair,
            "stage": stage.value,
            "owner": owner_of(stage).value,
            "sent_at": c.sent_at,
            "evidence": c.evidence[-1500:],
            "questions": [q.__dict__ for q in c.questions if not q.answered],
        }

    def _hint(self, nxt: Chat | None) -> str:
        st = self.st
        waiting = [c.id for c in st.chats if c.status == ChatStatus.AWAITING_REPLY]
        if nxt is not None:
            tail = f"; replies from {', '.join(waiting)} can be pasted any time" if waiting else ""
            return f"copy the packet for chat {nxt.id}, paste it in that chat{tail}"
        if waiting:
            return f"waiting for {', '.join(waiting)}: paste each reply as it arrives, chatop routes it by header"
        return self._idle_reason() if st.phase == Phase.SLICE else "done"
