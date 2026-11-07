"""Application facade. CLI, TUI and Web UI call ONLY this class (one narrow surface).

One human turn = build_packet() -> [human pastes to chat, copies reply] -> apply(reply_text).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from chatop.app.config import Config
from chatop.app.recon import build_recon, detect_checks, fence, list_files, source_files
from chatop.app.workspace import Workspace
from chatop.domain.changes import FileChange, plan_changes
from chatop.domain.models import Phase, Question, Slice, State, Status, Track
from chatop.domain.packet import Section, assemble, estimate_tokens
from chatop.domain.reply import Reply, contains_envelope, infer_role, parse_reply
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


class SessionError(Exception):
    pass


@dataclass
class PacketResult:
    turn: int
    text: str
    tokens: int
    notes: list[str]
    path: Path
    copied: bool


@dataclass
class ApplyResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    checks: list[RunResult] = field(default_factory=list)
    red_ok: bool | None = None
    slice_done: bool = False
    messages: list[str] = field(default_factory=list)
    repair_prompt: str | None = None
    next_packet: PacketResult | None = None
    status: str = ""


PHASE_DOCS: dict[Phase, list[tuple[str, int]]] = {
    Phase.IDEA: [],
    Phase.REFINE: [("docs/IDEA.md", 1), ("docs/REFINEMENT.md", 1), ("docs/FEATURE.md", 1), ("docs/AS-BUILT.md", 4)],
    Phase.PRD: [("docs/REFINEMENT.md", 1), ("docs/IDEA.md", 3)],
    Phase.SPEC: [("docs/PRD.md", 1), ("docs/REFINEMENT.md", 3), ("docs/AS-BUILT.md", 2)],
    Phase.PLAN: [
        ("docs/SPEC.md", 1),
        ("docs/PRD.md", 2),
        ("docs/FEATURE.md", 1),
        ("docs/AUDIT.md", 1),
        ("docs/AS-BUILT.md", 3),
        ("docs/PLAN.md", 4),
    ],
    Phase.SLICE: [("docs/PRD.md", 3), ("docs/FEATURE.md", 3), ("docs/SPEC.md", 4), ("docs/PLAN.md", 5)],
    Phase.FEATURE: [("docs/AS-BUILT.md", 2), ("docs/SPEC.md", 2), ("docs/PRD.md", 3)],
    Phase.DELTA: [("docs/FEATURE.md", 1), ("docs/SPEC.md", 1), ("docs/PRD.md", 2), ("docs/AS-BUILT.md", 2)],
    Phase.RECON: [],
    Phase.AUDIT: [("docs/AS-BUILT.md", 1)],
    Phase.DONE: [],
}
TRACK_NOTES: dict[tuple[Track, Phase], str] = {
    (Track.NEW, Phase.PLAN): "- S0 is the walking skeleton: layout, dependency manifest, `.gitignore`, working check "
    "commands, one passing smoke test.",
    (Track.CONTINUE, Phase.PLAN): "- Slices implement `docs/FEATURE.md` only. Use IDs that do not collide with "
    "existing slices (for example F2-S1). Existing done slices are listed in *State*.",
    (Track.AUDIT, Phase.PLAN): "- This is a STABILISATION plan derived from `docs/AUDIT.md`. The first slices add "
    "characterization tests that pin current behavior around the riskiest hotspots (expected to PASS immediately). "
    "Then fix critical findings, one slice each. Never refactor untested code.",
    (Track.ADOPT, Phase.RECON): "This phase advances automatically. Next, the human adds features with "
    "`chatop feature`.",
    (Track.AUDIT, Phase.RECON): "This phase advances automatically to AUDIT. Note where quality looks weak.",
}


def _template(name: str) -> Template:
    return Template(resources.files("chatop.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8"))


class Session:
    def __init__(self, ws: Workspace, index: CodeIndex, clipboard: Clipboard, runner: RunnerPort, vcs: Vcs) -> None:
        self.ws, self.index, self.clipboard, self.runner, self.vcs = ws, index, clipboard, runner, vcs
        self._state: State | None = None
        self._config: Config | None = None

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
    def answer(self, qid: str, choices: list[str], other: str = "") -> None:
        st = self.state
        q = next((q for q in st.questions if q.id == qid), None)
        if q is None:
            raise SessionError(f"no pending question {qid}")
        q.answer, q.other = choices, other
        self._after_answers(st)

    def accept_recommended(self) -> None:
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
            nxt = advance(st)
        except WorkflowError as exc:
            raise SessionError(str(exc)) from exc
        nxt.human_note = note
        self._save(nxt)
        self.ws.journal({"event": "approve", "phase": st.phase.value, "note": note})
        return nxt

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
    def build_packet(self, copy_to_clipboard: bool = True) -> PacketResult:
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
            Section("Role and rules", _template("system").safe_substitute(common), 0),
            Section(f"Your task: {st.phase.value.upper()}", _template(st.phase.value).safe_substitute(common), 0),
            Section("Reply contract", _template("contract").safe_substitute(common), 0),
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
            secs.append(Section("Requested context (your @@need lines)", self._resolve_needs(st), 1))
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

    def _file_block(self, rel: str, cap_lines: int | None = None) -> str:
        text = self.ws.read(rel)
        if text is None:
            return f"`{rel}`: (does not exist yet)"
        cap = cap_lines or self.config.max_file_lines
        lines = text.split("\n")
        if len(lines) > cap:
            return f"`{rel}` ({len(lines)} lines, first {cap} shown; request symbols with @@need)\n" + fence(
                "\n".join(lines[:cap])
            )
        return f"`{rel}`\n{fence(text)}"

    def _resolve_needs(self, st: State) -> str:
        out: list[str] = []
        for need in st.needs[:25]:
            t = need.target
            if need.kind == "file":
                out.append(self._file_block(t, cap_lines=1500))
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

    def _slice_context(self, sl: Slice) -> str:
        out: list[str] = [f"Slice `{sl.id}` touches: {', '.join(sl.touches) or '(unspecified)'}"]
        paths = [t for t in sl.touches if "/" in t or "." in Path(t).name]
        symbols = [t for t in sl.touches if t not in paths]
        for p in paths:
            out.append(self._file_block(p))
        for sym in symbols:
            hits = self.index.query(sym, limit=3)
            out += [self._snippet(h) for h in hits]
            callers = self.index.callers(sym, 15)
            if callers:
                out.append(f"callers of `{sym}`: " + ", ".join(f"{h.name} ({h.file}:{h.line})" for h in callers))
        existing = [p for p in paths if self.ws.read(p) is not None]
        for test in self.index.affected(existing)[:5]:
            if test not in paths:
                out.append("Affected test: " + self._file_block(test))
        return "\n\n".join(out)

    # ------------------------------------------------------------------ inbound reply
    def apply(self, text: str, force: bool = False) -> ApplyResult:
        st = self.state
        reply = parse_reply(text)
        errors = list(reply.errors)
        if not force and st.status != Status.AWAITING_REPLY:
            errors.insert(0, f"not waiting for a reply (status: {st.status}); run `chatop next` first")
        if not force and reply.turn is not None and reply.turn != st.turn:
            errors.insert(0, f"reply is for turn {reply.turn} but chatop is on turn {st.turn} (stale paste?)")
        changes, change_errors = plan_changes(reply, self.ws.read, self.config.protected)
        errors += change_errors
        if errors:
            return self._reject(st, text, errors)

        before = copy.deepcopy(st)
        self.ws.save_turn_file("replies", st.turn, text)
        undo: dict[str, Any] = {"turn": st.turn, "state": before.to_dict(), "files": {}, "commit": None}
        result = ApplyResult(ok=True)
        tests = [c for c in changes if c.role == "test"]
        rest = [c for c in changes if c.role != "test"]
        code_changes = [c for c in rest if c.role == "code"]

        if st.phase == Phase.SLICE and tests and code_changes and "test" in self.config.checks:
            self._write(tests, undo, result)
            red = self.runner.run("test", self.config.checks["test"], self.ws.root, self.config.check_timeout)
            result.red_ok = red.code != 0
            self._write(rest, undo, result)
        else:
            self._write(changes, undo, result)
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
            slice_err = self._merge_slices(st, reply.slices)
            if slice_err:
                result.messages.append(slice_err)

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
        if st.status == Status.READY and self.config.auto_next:
            result.next_packet = self.build_packet()
        return result

    def _write(self, changes: list[FileChange], undo: dict[str, Any], result: ApplyResult) -> None:
        for c in changes:
            undo["files"].setdefault(c.path, c.before)
            self.ws.write(c.path, c.after)
            flag = "D" if c.after is None else "A" if c.before is None else "M"
            result.changes.append(f"{flag} {c.path} [{c.role}]")

    def _merge_slices(self, st: State, new: list[Slice]) -> str:
        done = [s for s in st.slices if s.status == "done"]
        ids = [s.id for s in done] + [s.id for s in new]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            return f"slice ids collide with existing ones: {dup}; slices were NOT updated"
        st.slices = done + new
        return ""

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
        notes: list[str] = []
        all_green = bool(result.checks) and all(c.code == 0 for c in result.checks)
        strict = self.config.tdd_strict and st.track != Track.AUDIT
        if result.red_ok is False:
            notes.append(
                "RED not proven: the new tests already passed before the implementation was applied. "
                "Strengthen the tests so they fail without the change, or add @@advance if this slice "
                "only pins existing behavior."
            )
        if not result.checks:
            notes.append("No checks configured, so the slice cannot be verified. Propose them with @@check.")
        if result.red_ok and cur is not None:
            cur.red_proven = True
        tdd_ok = result.red_ok is not False or reply.advance or not strict
        red_known = cur is not None and cur.red_proven
        if strict and code and not tests and not reply.advance and not red_known:
            tdd_ok = False
            notes.append("Code changed without tests. Add @@test files, or @@advance for a pure refactor.")
        touched = bool(tests or code or reply.writes or reply.edits)
        if touched and all_green and tdd_ok:
            sha = None
            if self.config.auto_commit and cur is not None:
                sha = self.vcs.commit_all(f"chatop({cur.id}): {cur.title}\n\n{reply.summary}")
                undo["commit"] = sha
            result.slice_done = True
            result.messages.append(f"slice {st.current_slice} complete" + (f", committed {sha}" if sha else ""))
            st.evidence = self._format_checks(result.checks, only_failures=True)
            return complete_slice(st)
        if cur is not None and touched:
            cur.attempts += 1
        st.evidence = "\n\n".join([*notes, self._format_checks(result.checks)])
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
                return request_advance(st, {Phase(g) for g in self.config.gates})
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
        return {
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

    def pending_questions(self) -> list[Question]:
        return [q for q in self.state.questions if not q.answered]
