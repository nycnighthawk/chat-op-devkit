"""Application facade. CLI, TUI and Web UI call ONLY this class (one narrow surface).

One human turn = build_packet() -> [human pastes to chat, copies reply] -> apply(reply_text).
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chatop.app.config import Config
from chatop.app.lanes import Assignment, LaneEngine, Route
from chatop.app.prompts import PHASE_DOCS, TRACK_NOTES, template
from chatop.app.recon import build_recon, detect_checks, fence, list_files, source_files
from chatop.app.results import ApplyResult as ApplyResult
from chatop.app.results import PacketResult as PacketResult
from chatop.app.results import SessionError as SessionError
from chatop.app.workspace import Workspace
from chatop.domain.changes import FileChange, plan_changes
from chatop.domain.models import Need, Phase, Question, Slice, State, Status, Track
from chatop.domain.packet import Section, assemble, estimate_tokens
from chatop.domain.preflight import Diagnostic, check_all, parse_tool_output, render_command, select_files
from chatop.domain.reply import Reply, contains_envelope, infer_role, parse_reply
from chatop.domain.scheduler import graph_errors, width
from chatop.domain.tdd import judge_slice
from chatop.domain.workflow import (
    AUTO_ADVANCE,
    WorkflowError,
    advance,
    complete_slice,
    request_advance,
    start_feature,
)
from chatop.ports import Clipboard, CodeIndex, RunResult, SymbolHit, Vcs
from chatop.ports import Runner as RunnerPort


class Session:
    def __init__(self, ws: Workspace, index: CodeIndex, clipboard: Clipboard, runner: RunnerPort, vcs: Vcs) -> None:
        self.ws, self.index, self.clipboard, self.runner, self.vcs = ws, index, clipboard, runner, vcs
        self._state: State | None = None
        self._config: Config | None = None
        # _apply_lock serialises everything that touches the working tree (apply, packet building);
        # _state_lock guards short state mutations so the UI can poll the board while an apply runs checks.
        self._apply_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self.lanes = LaneEngine(self)

    # ------------------------------------------------------------------ state helpers
    @property
    def state(self) -> State:
        if self._state is None:
            self._state = self.ws.load_state()
            if self._state is None:
                raise SessionError("not initialised: run `chatop init` in the project root")
        return self._state

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = self.ws.load_config()
        return self._config

    def _save(self, state: State) -> None:
        self._state = state
        self.ws.save_state(state)

    def set_check(self, name: str, cmd: str | None) -> None:
        cfg = self.config
        if cmd:
            cfg.checks[name] = cmd
        else:
            cfg.checks.pop(name, None)
        self.ws.save_config(cfg)

    def vcs_log(self) -> str:
        return self.vcs.log_summary(20)

    # ------------------------------------------------------------------ init / detect
    def detect_track(self) -> Track:
        if self.ws.initialised:
            return Track.CONTINUE
        files = list_files(self.ws, self.vcs)
        src = source_files(files)
        if not src:
            return Track.NEW
        has_tests = any(infer_role(f) == "test" for f in src)
        return Track.ADOPT if has_tests and detect_checks(self.ws, files).get("test") else Track.AUDIT

    def init(self, track: Track | None = None, idea: str = "") -> State:
        if self.ws.initialised:
            raise SessionError('already initialised; use `chatop feature "..."` to start new work')
        track = track or self.detect_track()
        if track == Track.CONTINUE:
            raise SessionError("track 'continue' needs an initialised project; choose new, adopt or audit")
        self.ws.ensure_dir()
        cfg = Config(codegraph_bin=self.config.codegraph_bin)
        files = list_files(self.ws, self.vcs)
        cfg.checks = detect_checks(self.ws, files)
        self.ws.save_config(cfg)
        self._config = cfg
        if track == Track.NEW:
            body = idea.strip() or "(describe the idea here, then run chatop next)"
            self.ws.write("docs/IDEA.md", f"# Idea\n\n{body}\n")
            phase = Phase.IDEA
        else:
            phase = Phase.RECON
            if self.index.available():
                self.index.ensure_index()
        state = State(track=track, phase=phase)
        self._save(state)
        self.ws.journal({"event": "init", "track": track.value})
        return state

    # ------------------------------------------------------------------ human inputs
    def answer(self, qid: str, choices: list[str], other: str = "", chat: str | None = None) -> None:
        if chat is not None or self.in_lane_mode():
            self.lanes.answer(qid, choices, other, chat)
            return
        st = self.state
        q = next((q for q in st.questions if q.id == qid), None)
        if q is None:
            raise SessionError(f"no pending question {qid}")
        q.answer, q.other = choices, other
        self._after_answers(st)

    def accept_recommended(self, chat: str | None = None) -> None:
        if chat is not None or self.in_lane_mode():
            self.lanes.accept_recommended(chat)
            return
        st = self.state
        for q in st.questions:
            if not q.answered:
                q.answer = list(q.recommended) or q.options[:1]
        self._after_answers(st)

    def _after_answers(self, st: State) -> None:
        if all(q.answered for q in st.questions) and st.status == Status.AWAITING_ANSWERS:
            st.status = Status.READY
        self._save(st)

    def approve(self, note: str = "") -> State:
        st = self.state
        if st.status != Status.AWAITING_APPROVAL:
            raise SessionError(f"nothing to approve (status: {st.status})")
        self.accept_checks()
        try:
            nxt = advance(st, activate=not self.parallel_enabled())
        except WorkflowError as exc:
            raise SessionError(str(exc)) from exc
        nxt.human_note = note
        self._save(nxt)
        self.ws.journal({"event": "approve", "phase": st.phase.value, "note": note})
        if self._needs_dispatch(nxt):
            self.dispatch()
        return self.state

    def reject(self, note: str) -> State:
        st = self.state
        if st.status != Status.AWAITING_APPROVAL:
            raise SessionError(f"nothing to reject (status: {st.status})")
        st.status, st.human_note = Status.READY, f"Human requested changes before approval: {note}"
        self._save(st)
        return st

    def accept_checks(self) -> dict[str, str]:
        st = self.state
        accepted = dict(st.proposed_checks)
        for name, cmd in accepted.items():
            self.set_check(name, cmd)
        st.proposed_checks = {}
        if accepted and st.phase == Phase.AUDIT and st.status == Status.AWAITING_REPLY:
            st.evidence = self._format_checks(self._run_checks(list(self.config.checks)))  # packet is rebuilt
        self._save(st)
        return accepted

    def feature(self, text: str, force: bool = False) -> State:
        st = self.state
        if force and st.phase != Phase.DONE:
            st = copy.deepcopy(st)
            st.phase = Phase.DONE
        try:
            nxt = start_feature(st, text)
        except WorkflowError as exc:
            raise SessionError(str(exc)) from exc
        self._save(nxt)
        return nxt

    # ------------------------------------------------------------------ outbound packet
    def build_packet(self, copy_to_clipboard: bool = True, chat: str | None = None, full: bool = False) -> PacketResult:
        if chat is not None or self.in_lane_mode():
            return self.lanes.packet(chat, copy_to_clipboard, full)
        st = self.state
        if st.status == Status.AWAITING_ANSWERS:
            raise SessionError("answer the pending questions first (chatop answer / chatop accept)")
        if st.status == Status.AWAITING_APPROVAL:
            raise SessionError(f'{st.phase} is waiting for approval (chatop approve / chatop reject "why")')
        if st.status == Status.DONE:
            raise SessionError('track complete. Start new work with: chatop feature "..."')
        if st.status == Status.READY:
            st.turn += 1
            st.status = Status.AWAITING_REPLY
            if st.phase == Phase.AUDIT or (st.phase == Phase.RECON and self.config.checks):
                st.evidence = self._format_checks(self._run_checks(list(self.config.checks)))
            self._save(st)
        if self.index.available() and st.phase in (Phase.SLICE, Phase.FEATURE, Phase.AUDIT, Phase.RECON):
            self.index.ensure_index()
        text, notes = assemble(self._sections(st), self.config.budget_tokens)
        path = self.ws.save_turn_file("packets", st.turn, text)
        copied = self.clipboard.copy(text) if copy_to_clipboard else False
        return PacketResult(st.turn, text, estimate_tokens(text), notes, path, copied)

    def _sections(self, st: State) -> list[Section]:
        cfg = self.config
        checks = ", ".join(f"`{k}`" for k in cfg.checks) or "(none configured yet)"
        common = {
            "project": self.ws.root.name,
            "turn": st.turn,
            "track": st.track.value,
            "phase": st.phase.value,
            "checks": checks,
            "protected": ", ".join(f"`{p}`" for p in cfg.protected),
            "max_questions": cfg.max_questions,
            "max_rounds": cfg.max_refine_rounds,
            "round": st.refine_round + 1,
            "brief": "FEATURE.md" if st.track == Track.CONTINUE else "REFINEMENT.md",
            "track_notes": TRACK_NOTES.get((st.track, st.phase), ""),
            "header": f"<<<CHATOP turn={st.turn}>>>",
        }
        cur = st.slice(st.current_slice)
        if cur is not None:
            common |= {
                "slice_id": cur.id,
                "slice_title": cur.title,
                "slice_goal": cur.goal or cur.title,
                "slice_acceptance": ", ".join(cur.acceptance) or "(see PLAN)",
                "attempt": cur.attempts + 1,
                "red_note": "(Characterization tests that pin existing behavior may pass immediately; then add "
                "@@advance.)"
                if st.track == Track.AUDIT
                else "",
            }
        secs = [
            Section("Role and rules", template("system").safe_substitute(common), 0),
            Section(f"Your task: {st.phase.value.upper()}", template(st.phase.value).safe_substitute(common), 0),
            Section("Reply contract", template("contract").safe_substitute(common), 0),
            Section("State", self._state_digest(st), 0),
            Section("Human input", self._human_input(st), 0),
            Section("Evidence (from chatop's last run)", st.evidence, 1),
        ]
        if st.phase in (Phase.RECON, Phase.AUDIT):
            report, agents = build_recon(self.ws, self.vcs, self.index)
            secs.append(Section("Recon report (local, deterministic)", report, 1))
            secs.append(Section("Agent instruction files and README", agents, 2))
        for doc, prio in PHASE_DOCS.get(st.phase, []):
            text = self.ws.read(doc)
            if text:
                secs.append(Section(f"Doc: {doc}", fence(text, "markdown"), prio))
        if st.needs:
            secs.append(Section("Requested context (your @@need lines)", self._resolve_needs(st.needs), 1))
        if st.phase == Phase.SLICE and cur is not None:
            secs.append(Section(f"Code context for {cur.id}", self._slice_context(cur), 2))
        if st.phase in (Phase.FEATURE, Phase.PLAN, Phase.SPEC, Phase.DELTA, Phase.SLICE):
            tree = self.index.files(3) if self.index.available() else ""
            secs.append(Section("Repo map", fence(tree or "\n".join(list_files(self.ws, self.vcs)[:300])), 6))
        return secs

    def _state_digest(self, st: State) -> str:
        out = [f"- track **{st.track.value}**, phase **{st.phase.value}**, turn {st.turn}"]
        if st.slices:
            done = [s for s in st.slices if s.status == "done"]
            out.append(f"- slices: {len(done)}/{len(st.slices)} done")
            out += ["", "| id | status | title | acceptance |", "|---|---|---|---|"]
            open_or_recent = [s for s in st.slices if s.status != "done"] + done[-10:]
            if len(done) > 10:
                out.append(f"| … | done | {len(done) - 10} older slices | |")
            out += [f"| {s.id} | {s.status} | {s.title} | {', '.join(s.acceptance)} |" for s in open_or_recent]
        if st.decisions:
            out += ["", "Decisions so far:"] + [f"- {d}" for d in st.decisions[-30:]]
        if st.history:
            out += ["", "Recent turns:"] + [f"- {h}" for h in st.history[-8:]]
        return "\n".join(out)

    def _human_input(self, st: State) -> str:
        parts: list[str] = []
        if st.phase == Phase.IDEA:
            parts.append(self.ws.read("docs/IDEA.md") or "")
        if st.phase == Phase.FEATURE and st.feature:
            parts.append(f"Feature request:\n\n> {st.feature}")
        answered = [q for q in st.questions if q.answered]
        if answered:
            parts.append("Answers to your questions:")
            for q in answered:
                ans = ", ".join(q.answer or []) or "(none of the options)"
                extra = f' + other: "{q.other.strip()}"' if q.other.strip() else ""
                parts.append(f"- **{q.id}** {q.text} → {ans}{extra}")
        if st.human_note:
            parts.append(st.human_note)
        return "\n".join(parts)

    # ------------------------------------------------------------------ code context via the code graph
    def _snippet(self, hit: SymbolHit, pad: int = 2, cap: int = 200) -> str:
        text = self.ws.read(hit.file)
        if text is None or hit.line is None:
            return f"- `{hit.file}:{hit.line}` {hit.kind} {hit.name}"
        lines = text.split("\n")
        start = max(1, hit.line - pad)
        end = min(len(lines), hit.end_line or hit.line + 40, start + cap)
        body = "\n".join(lines[start - 1 : end])
        return f"`{hit.file}:{hit.line}-{hit.end_line or end}` ({hit.kind} {hit.name})\n{fence(body)}"

    def _file_block(
        self, rel: str, cap_lines: int | None = None, read: Callable[[str], str | None] | None = None
    ) -> str:
        text = (read or self.ws.read)(rel)
        if text is None:
            return f"`{rel}`: (does not exist yet)"
        cap = cap_lines or self.config.max_file_lines
        lines = text.split("\n")
        if len(lines) > cap:
            return f"`{rel}` ({len(lines)} lines, first {cap} shown; request symbols with @@need)\n" + fence(
                "\n".join(lines[:cap])
            )
        return f"`{rel}`\n{fence(text)}"

    def _resolve_needs(self, needs: list[Need], read: Callable[[str], str | None] | None = None) -> str:
        out: list[str] = []
        for need in needs[:25]:
            t = need.target
            if need.kind == "file":
                out.append(self._file_block(t, cap_lines=1500, read=read))
            elif need.kind == "symbol":
                hits = self.index.query(t, limit=5)
                out.append("\n\n".join(self._snippet(h) for h in hits) or f"symbol `{t}`: no match in code graph")
            elif need.kind in ("callers", "callees"):
                fn = self.index.callers if need.kind == "callers" else self.index.callees
                hits = fn(t, 30)
                out.append(
                    f"{need.kind} of `{t}`:\n"
                    + ("\n".join(f"- {h.file}:{h.line} {h.kind} {h.name}" for h in hits) or "- (none)")
                )
            elif need.kind == "impact":
                out.append(f"impact of `{t}`:\n{self.index.impact(t, 2)}")
            elif need.kind == "affected":
                out.append(f"tests affected by `{t}`:\n" + "\n".join(f"- {f}" for f in self.index.affected([t])))
        return "\n\n".join(out)

    def _slice_items(self, sl: Slice, read: Callable[[str], str | None] | None = None) -> dict[str, str]:
        """Code context for an issue as keyed items (``file:<path>`` / ``symbol:<name>``), so delta packets can
        skip the ones a chat already holds."""
        out: dict[str, str] = {}
        paths = [t for t in sl.touches if "/" in t or "." in Path(t).name]
        symbols = [t for t in sl.touches if t not in paths]
        for p in paths:
            out[f"file:{p}"] = self._file_block(p, read=read)
        for sym in symbols:
            hits = self.index.query(sym, limit=3)
            parts = [self._snippet(h) for h in hits]
            callers = self.index.callers(sym, 15)
            if callers:
                parts.append(f"callers of `{sym}`: " + ", ".join(f"{h.name} ({h.file}:{h.line})" for h in callers))
            if parts:
                out[f"symbol:{sym}"] = "\n\n".join(parts)
        rd = read or self.ws.read
        existing = [p for p in paths if rd(p) is not None]
        for test in self.index.affected(existing)[:5]:
            if test not in paths:
                out[f"file:{test}"] = "Affected test: " + self._file_block(test, read=read)
        return out

    def _slice_context(self, sl: Slice) -> str:
        head = f"Slice `{sl.id}` touches: {', '.join(sl.touches) or '(unspecified)'}"
        return "\n\n".join([head, *self._slice_items(sl).values()])

    # ------------------------------------------------------------------ inbound reply
    def apply(self, text: str, force: bool = False) -> ApplyResult:
        if self.in_lane_mode():
            return self.lanes.apply(text, force)
        with self._apply_lock:
            return self._apply_serial(text, force)

    def _apply_serial(self, text: str, force: bool) -> ApplyResult:
        st = self.state
        reply = parse_reply(text)
        errors = list(reply.errors)
        if not force and st.status != Status.AWAITING_REPLY:
            errors.insert(0, f"not waiting for a reply (status: {st.status}); run `chatop next` first")
        if not force and reply.turn is not None and reply.turn != st.turn:
            errors.insert(0, f"reply is for turn {reply.turn} but chatop is on turn {st.turn} (stale paste?)")
        changes, change_errors = plan_changes(reply, self.ws.read, self.config.protected)
        errors += change_errors
        errors += self._syntax_errors(changes)  # every file at once, not one error per round trip
        if errors:
            return self._reject(st, text, errors)

        before = copy.deepcopy(st)
        self.ws.save_turn_file("replies", st.turn, text)
        undo: dict[str, Any] = {"turn": st.turn, "state": before.to_dict(), "files": {}, "commit": None}
        result = ApplyResult(ok=True)
        tests = [c for c in changes if c.role == "test"]
        code_changes = [c for c in changes if c.role == "code"]

        stage_errors, result.red_ok = self._stage(
            changes, undo, result, tdd_red=st.phase == Phase.SLICE and bool(tests and code_changes)
        )
        if stage_errors:
            return self._reject(st, text, stage_errors)
        if changes and self.index.available():
            self.index.ensure_index()

        st = copy.deepcopy(st)
        st.decisions += [d for d in reply.decisions if d not in st.decisions]
        st.proposed_checks |= reply.checks
        st.history.append(f"T{st.turn} {st.phase.value}: {reply.summary or '(no summary)'}")
        st.questions = reply.questions
        st.needs = reply.needs
        st.human_note = ""
        if reply.slices is not None:
            result.messages += self._merge_slices(st, reply.slices)

        if st.phase == Phase.SLICE:
            st = self._finish_slice(st, reply, tests, code_changes, result, undo)
        else:
            run_names = [r for r in reply.runs if r in self.config.checks]
            result.messages += [f"@@run {r}: no such configured check" for r in reply.runs if r not in run_names]
            result.checks = self._run_checks(run_names)
            st.evidence = self._format_checks(result.checks)
            st = self._transition(st, reply, result)

        self.ws.push_undo(before.turn, undo)
        self._save(st)
        result.status = st.status.value
        self.ws.journal(
            {
                "event": "apply",
                "turn": before.turn,
                "phase": before.phase.value,
                "summary": reply.summary,
                "changes": result.changes,
                "checks": {c.name: c.code for c in result.checks},
                "red_ok": result.red_ok,
                "slice_done": result.slice_done,
                "status": st.status.value,
            }
        )
        if st.proposed_checks:
            result.messages.append(
                "LLM proposed checks (accept with `chatop checks --accept`): "
                + "; ".join(f"{k} = {v}" for k, v in st.proposed_checks.items())
            )
        if self._needs_dispatch(st) and self.config.auto_dispatch:
            self.dispatch()
            st = self.state
        if st.status == Status.READY and self.config.auto_next:
            result.next_packet = self.build_packet()
        return result

    def _syntax_errors(self, changes: list[FileChange]) -> list[str]:
        """Built-in lint (pure) over the final content of every changed file."""
        diags = check_all({c.path: c.after for c in changes})
        return [f"syntax error in {d.render()}" for d in diags]

    def _external_preflight(self, changes: list[FileChange]) -> list[Diagnostic]:
        """Run each configured linter ONCE over all matching changed files (files are already on disk)."""
        paths = [c.path for c in changes if c.after is not None]
        found: list[Diagnostic] = []
        for pattern, tool in self.config.preflight.items():
            files = select_files(pattern, paths)
            if not files:
                continue
            run = self.runner.run("preflight", render_command(tool, files), self.ws.root, self.config.check_timeout)
            if run.code != 0:
                found += parse_tool_output(run.output, pattern) or [
                    Diagnostic(f"({pattern})", None, None, f"linter exited with code {run.code}", pattern)
                ]
        return found

    def _revert(self, changes: list[FileChange]) -> None:
        for c in changes:
            self.ws.write(c.path, c.before)

    def _stage(
        self, changes: list[FileChange], undo: dict[str, Any], result: ApplyResult, tdd_red: bool
    ) -> tuple[list[str], bool | None]:
        """Write everything, lint everything in one shot, then (slices) prove RED with the code held back.

        Returns (errors, red_ok). On errors every file is already restored.
        """
        self._write(changes, undo, result)
        lint = self._external_preflight(changes)
        if lint:
            self._revert(changes)
            result.changes.clear()
            return [f"preflight {d.render()}" for d in lint], None
        red_ok: bool | None = None
        code = [c for c in changes if c.role == "code"]
        if tdd_red and "test" in self.config.checks:
            self._revert(code)  # tests alone: they must fail without the implementation
            red = self.runner.run("test", self.config.checks["test"], self.ws.root, self.config.check_timeout)
            red_ok = red.code != 0
            for c in code:
                self.ws.write(c.path, c.after)
        return [], red_ok

    def _write(self, changes: list[FileChange], undo: dict[str, Any], result: ApplyResult) -> None:
        for c in changes:
            undo["files"].setdefault(c.path, c.before)
            self.ws.write(c.path, c.after)
            flag = "D" if c.after is None else "A" if c.before is None else "M"
            result.changes.append(f"{flag} {c.path} [{c.role}]")

    def _merge_slices(self, st: State, new: list[Slice]) -> list[str]:
        done = [s for s in st.slices if s.status == "done"]
        ids = [s.id for s in done] + [s.id for s in new]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            return [f"slice ids collide with existing ones: {dup}; slices were NOT updated"]
        problems = graph_errors(done + new)
        if problems:
            return ["; ".join(problems) + "; slices were NOT updated. Ask the LLM to fix `depends`."]
        st.slices = done + new
        w = width(new)
        if w > self.config.max_parallel:
            return [
                f"this plan lets {w} issues run in parallel (in separate chats); max_parallel is "
                f"{self.config.max_parallel}. Raise it with `chatop config --set max_parallel {w}` to use them."
            ]
        return []

    def _finish_slice(
        self,
        st: State,
        reply: Reply,
        tests: list[FileChange],
        code: list[FileChange],
        result: ApplyResult,
        undo: dict[str, Any],
    ) -> State:
        cur = st.slice(st.current_slice)
        result.checks = self._run_checks(list(self.config.checks))
        verdict = judge_slice(
            strict=self.config.tdd_strict and st.track != Track.AUDIT,
            red_ok=result.red_ok,
            red_already=cur is not None and cur.red_proven,
            check_codes=[c.code for c in result.checks],
            has_tests=bool(tests),
            has_code=bool(code),
            advance=reply.advance,
            touched=bool(tests or code or reply.writes or reply.edits),
        )
        if cur is not None and verdict.red_proven:
            cur.red_proven = True
        if verdict.done:
            sha = None
            if self.config.auto_commit and cur is not None:
                sha = self.vcs.commit_all(f"chatop({cur.id}): {cur.title}\n\n{reply.summary}")
                undo["commit"] = sha
            result.slice_done = True
            result.messages.append(f"slice {st.current_slice} complete" + (f", committed {sha}" if sha else ""))
            st.evidence = self._format_checks(result.checks, only_failures=True)
            return complete_slice(st)
        if cur is not None and bool(tests or code or reply.writes or reply.edits):
            cur.attempts += 1
        st.evidence = "\n\n".join([*verdict.notes, self._format_checks(result.checks)])
        st.status = Status.AWAITING_ANSWERS if any(not q.answered for q in st.questions) else Status.READY
        return st

    def _transition(self, st: State, reply: Reply, result: ApplyResult) -> State:
        if st.questions:
            st.status = Status.AWAITING_ANSWERS
            if st.phase in AUTO_ADVANCE and not st.needs:
                st = advance(st)
                st.status = Status.AWAITING_ANSWERS
            elif st.phase == Phase.REFINE:
                st.refine_round += 1
            return st
        if st.needs:
            st.status = Status.READY
            return st
        if reply.advance or st.phase in AUTO_ADVANCE:
            try:
                return request_advance(st, {Phase(g) for g in self.config.gates}, activate=not self.parallel_enabled())
            except WorkflowError as exc:
                result.messages.append(str(exc))
        if st.phase == Phase.REFINE:
            st.refine_round += 1
        st.status = Status.READY
        return st

    def _reject(self, st: State, text: str, errors: list[str]) -> ApplyResult:
        self.ws.save_turn_file("replies", st.turn, text)
        bullet = "\n".join(f"- {e}" for e in errors)
        repair = (
            f"chatop could not apply your reply for turn {st.turn}. Nothing was changed.\n\n"
            f"Problems:\n{bullet}\n\n"
            f"Resend the COMPLETE corrected reply as one block starting with `<<<CHATOP turn={st.turn}>>>` and "
            "ending with `<<<END>>>`, inside a ````chatop fence. For SEARCH mismatches, use @@file to rewrite the "
            "file, or @@need file <path> to see the current content."
        )
        copied = self.clipboard.copy(repair)
        self.ws.journal({"event": "reject", "turn": st.turn, "errors": errors})
        return ApplyResult(
            ok=False,
            errors=errors,
            repair_prompt=repair,
            status=st.status.value,
            messages=["repair prompt copied to clipboard" if copied else "repair prompt ready"],
        )

    # ------------------------------------------------------------------ checks
    def _run_checks(self, names: list[str]) -> list[RunResult]:
        return [
            self.runner.run(n, self.config.checks[n], self.ws.root, self.config.check_timeout)
            for n in names
            if n in self.config.checks
        ]

    @staticmethod
    def _format_checks(results: list[RunResult], only_failures: bool = False, tail: int = 80) -> str:
        out: list[str] = []
        for r in results:
            ok = r.code == 0
            if ok and only_failures:
                continue
            out.append(f"### {r.name}: {'PASS' if ok else 'FAIL'} (exit code {r.code}, {r.seconds}s) `{r.cmd}`")
            if not ok:
                out.append(fence("\n".join(r.output.rstrip().split("\n")[-tail:])))
        return "\n".join(out)

    # ------------------------------------------------------------------ undo / watch / doctor / status
    def undo(self) -> list[str]:
        if self.state.chats:
            raise SessionError("undo is not available once parallel chats are in use; use `git revert` on the commit")
        data = self.ws.pop_undo()
        if data is None:
            raise SessionError("nothing to undo")
        if data.get("commit"):
            self.ws.push_undo(data["turn"], data)
            raise SessionError(f"turn {data['turn']} was committed ({data['commit']}); use `git revert` instead")
        for path, before in data["files"].items():
            self.ws.write(path, before)
        st = State.from_dict(data["state"])
        st.status = Status.AWAITING_REPLY
        self._save(st)
        return list(data["files"])

    def watch_tick(self, last_seen: str | None) -> tuple[str | None, ApplyResult | None]:
        """Poll the clipboard once. Apply when a new envelope for the current turn appears."""
        text = self.clipboard.paste()
        if not text or text == last_seen:
            return last_seen, None
        turn = contains_envelope(text)
        st = self.state
        if self.in_lane_mode():
            if turn is None:
                return text, None
            route = self.route(text)
            chat = st.chat(route.chat) if route.ok else None
            if chat is None or chat.status.value != "awaiting_reply" or turn not in (chat.turn, -1):
                return text, None
            return text, self.apply(text)
        if turn is None or st.status != Status.AWAITING_REPLY or turn not in (st.turn, -1):
            return text, None
        return text, self.apply(text)

    def status(self) -> dict[str, Any]:
        st = self.state
        cur = st.slice(st.current_slice)
        hint = {
            Status.READY: "run `chatop next` (packet goes to your clipboard)",
            Status.AWAITING_REPLY: "paste the packet in chat, copy the reply, run `chatop apply`",
            Status.AWAITING_ANSWERS: "answer: `chatop answer` (or `chatop accept` for the recommended options)",
            Status.AWAITING_APPROVAL: f"review docs for {st.phase.value}, then `chatop approve` or `chatop reject`",
            Status.DONE: 'done. Next: `chatop feature "..."`',
        }[st.status]
        board = self.lanes.board() if self.parallel_enabled() or st.chats else None
        if board is not None and self.in_lane_mode():
            hint = board["hint"]
        return {
            "mode": "parallel" if board is not None else "serial",
            "chats": board["chats"] if board is not None else [],
            "event_seq": st.event_seq,
            "max_parallel": self.config.max_parallel,
            "project": self.ws.root.name,
            "track": st.track.value,
            "phase": st.phase.value,
            "status": st.status.value,
            "turn": st.turn,
            "hint": hint,
            "slice": None if cur is None else {"id": cur.id, "title": cur.title, "attempts": cur.attempts},
            "slices": [{"id": s.id, "title": s.title, "status": s.status} for s in st.slices],
            "questions": [q.__dict__ for q in st.questions],
            "proposed_checks": st.proposed_checks,
            "checks": self.config.checks,
            "decisions": st.decisions[-10:],
            "history": st.history[-10:],
            "evidence": st.evidence,
            "clipboard": self.clipboard.name,
        }

    def doctor(self) -> list[tuple[str, bool, str]]:
        import sys

        return [
            ("python>=3.11", sys.version_info >= (3, 11), sys.version.split()[0]),
            (
                "codegraph CLI",
                self.index.available(),
                "found" if self.index.available() else "install: npm i -g @colbymchenry/codegraph",
            ),
            ("git repository", self.vcs.is_repo(), "yes" if self.vcs.is_repo() else "run: git init"),
            (
                "clipboard",
                self.clipboard.name != "file",
                f"backend: {self.clipboard.name}"
                + (
                    ""
                    if self.clipboard.name != "file"
                    else " (packets -> .chatop/outbox.md, replies <- .chatop/inbox.md)"
                ),
            ),
            (
                "checks configured",
                bool(self.config.checks),
                ", ".join(self.config.checks)
                or "LLM proposes them in SPEC/RECON, or: chatop checks --set test '<cmd>'",
            ),
        ]

    def pending_questions(self, chat: str | None = None) -> list[Question]:
        if chat is not None or self.in_lane_mode():
            return self.lanes.pending_questions(chat)
        return [q for q in self.state.questions if not q.answered]

    # ------------------------------------------------------------------ parallel relay (delegated to the lane engine)
    def parallel_enabled(self) -> bool:
        """New plans are dispatched to chats (instead of one serial slice) when parallelism is on."""
        return self.config.max_parallel > 1 and self.config.auto_commit

    def in_lane_mode(self) -> bool:
        st = self.state
        return st.phase == Phase.SLICE and st.current_slice is None

    def _needs_dispatch(self, st: State) -> bool:
        return st.phase == Phase.SLICE and st.current_slice is None and st.status == Status.READY and bool(st.slices)

    def dispatch(self) -> list[Assignment]:
        return self.lanes.dispatch()

    def assign(self, issue: str, chat: str | None = None) -> Assignment:
        return self.lanes.assign(issue, chat)

    def next_up(self) -> str | None:
        return self.lanes.next_up()

    def route(self, text: str) -> Route:
        return self.lanes.route(text)

    def board(self) -> dict[str, Any]:
        return self.lanes.board()

    def events_since(self, seq: int) -> list[dict[str, Any]]:
        return self.lanes.events_since(seq)

    def reset_chat(self, chat: str) -> None:
        self.lanes.reset_chat(chat)

    def mark_sent(self, chat: str, sent: bool = True) -> None:
        self.lanes.mark_sent(chat, sent)

    def configure(self, key: str, value: str) -> dict[str, Any]:
        """Change a scalar option (max_parallel, max_attempts, ...) from a UI."""
        try:
            self.config.set_option(key, value)
        except KeyError as exc:
            raise SessionError(f"unknown or non-scalar option: {key}") from exc
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        self.ws.save_config(self.config)
        return {key: getattr(self.config, key)}
