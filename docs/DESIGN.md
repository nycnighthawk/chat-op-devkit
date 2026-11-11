# Design: chatop

Companion to `PRD.md` (what and why). This document is the **how, at module level**, the **traceability from every
requirement to a module and a test**, and the **guide for taking chatop (or one layer of it) into another product**.
Diagrams, flows and the state machine are in `ARCHITECTURE.md`; the externally visible contract is `BEHAVIOR.md`.

## 1. System context

```
 human ──copy packet──►  chat LLM (Claude / ChatGPT / Gemini, no repo access)
   ▲  │                        │
   │  └──────◄── reply ────────┘
   │
   ▼
 ┌──────────────────────────── chatop (local) ──────────────────────────────┐
 │  shells:  CLI · web (FastAPI) · TUI (Textual)        no business logic    │
 │      │                                                                    │
 │  app:  Session facade · LaneEngine · Workspace · Config · recon          │
 │      │                                                                    │
 │  domain (pure):  reply · changes · preflight · tdd · workflow ·           │
 │                  scheduler · stage · packet · delta · models              │
 │      │                                                                    │
 │  ports: CodeIndex · Clipboard · Runner · Vcs                              │
 └──────┼────────────────────────────────────────────────────────────────────┘
        ▼
  adapters: codegraph CLI · pbcopy/wl-copy/xclip/file · shell · git        project repo + .chatop/
```

## 2. Design principles

1. **Text at the edges, types inside.** Everything that crosses the LLM boundary is text; it becomes typed data once
   (`parse_reply`) and typed data becomes text once (`assemble`).
2. **A pure core.** `domain` does no I/O. Every decision (what to apply, what is ready, whose move it is) is a function.
3. **Narrow surfaces.** Five ports, one facade (`Session`), one reply parser, one packet assembler. A change stays local.
4. **Evidence over claims.** A reply is trusted only after it is validated, applied, and its tests proven red then green.
5. **The human owns the gates.** Approvals, checks and unblocking are human decisions; the LLM may propose, never execute.
6. **State is files.** `state.json` plus an append-only journal; every shell and every restart sees the same truth.

## 3. Module map

| Module | Responsibility | Implements |
|---|---|---|
| `domain/models.py` | enums (track, phase, status), `State`, `Slice`, `Question`, `Chat`, JSON round trip | FR-1, FR-5, FR-7 |
| `domain/workflow.py` | tracks as data, transitions, gates, auto-advance, slice activation, `start_feature` | FR-1, FR-3, FR-6 |
| `domain/reply.py` | `parse_reply(text) -> Reply`; every directive; truncated and pasted-packet detection | FR-20, FR-21 |
| `domain/changes.py` | `plan_changes`: path safety, protected globs, exact-once edits with tolerant fallback | FR-22, FR-24, FR-70 |
| `domain/preflight.py` | one-shot syntax check of every generated Python, JSON, TOML file; repair prompt | FR-22, FR-23 |
| `domain/tdd.py` | red/green verdict rules, code-only retry, relaxed audit mode | FR-30, FR-31 |
| `domain/scheduler.py` | `graph_errors`, `ready_issues`, `pick_dispatch`, `touches` exclusion, plan width | FR-5, FR-40, FR-41, FR-42 |
| `domain/stage.py` | the stage of each chat: your move, waiting for the LLM, applying, closed | FR-44 |
| `domain/packet.py` | `assemble(sections, budget)`: priority ordering, budget, notes on what was dropped | FR-10, FR-11 |
| `domain/delta.py` | per-chat digests so a continuing chat gets only changes | FR-13 |
| `ports.py` | Protocols: `CodeIndex`, `Clipboard`, `Runner`, `Vcs` and their result types | NFR-2, NFR-3 |
| `adapters/codegraph.py` | codegraph CLI behind `CodeIndex`; tolerant JSON; failures mean "no hits" | FR-28, FR-50, C-2 |
| `adapters/clipboard.py` | pbcopy, wl-copy, xclip, xsel, file fallback (`CHATOP_CLIPBOARD=file`) | FR-12 |
| `adapters/runner.py` | run configured checks with a timeout | FR-32, FR-71 |
| `adapters/git.py` | commit, status, churn, tracked files | FR-26, FR-50 |
| `app/workspace.py` | root-confined file access, state load/save, journal, packet/reply archive | FR-7, FR-14, FR-70 |
| `app/config.py` | `config.toml`: checks, protected paths, limits, parallel options | FR-32, FR-4 |
| `app/prompts.py` + `prompts/*.md` | the wording of every phase, rendered into packets | FR-10 |
| `app/session.py` | the use-case facade: init, packets, apply, answer, approve, reject, feature, undo, status, doctor, watch | FR-2 to FR-4, FR-6, FR-10, FR-12, FR-14, FR-21 to FR-33, FR-63, FR-64, FR-71 |
| `app/recon.py` | evidence for unknown projects: map, entry points, churn, tests, agent markers | FR-50 to FR-52 |
| `app/lanes.py` | issues, dispatch, assign, routing by chat id, delta packets, sent flag, event sequence, board | FR-13, FR-40 to FR-45 |
| `app/wiring.py` | the composition root: the only place adapters meet the app | NFR-2 |
| `ui/cli.py` | argparse shell; `status --json`; exit codes | FR-60 |
| `ui/web.py` + `static/` | FastAPI shell and single-page board | FR-61 |
| `ui/tui.py` | Textual shell | FR-62 |

## 4. Traceability: requirement to module to test

Tests live under `tests/`; labs are replayed by `tests/e2e/test_labs.py` and, through the CLI only, by `bootstrap/accept.py`.

| Requirement | Module(s) | Test area |
|---|---|---|
| FR-1 tracks and phases | `workflow`, `session` | `tests/domain/test_workflow.py`, labs 1-4 |
| FR-2 track detection | `session` | `tests/app/test_session.py`, labs 1, 3 |
| FR-3 gates and rejection | `workflow`, `session` | `test_workflow.py`, `test_session.py`, labs 1, 2, 4 |
| FR-4 bounded refinement, recommended answers | `reply`, `session`, `config` | `test_reply.py`, `test_session.py`, labs 1, 2 |
| FR-5 structured plan, validation | `scheduler`, `models`, `reply` | `tests/domain/test_scheduler.py` |
| FR-6 feature on a finished project | `workflow`, `session` | `test_workflow.py`, lab 2 |
| FR-7 state on disk | `models`, `workspace` | `test_session.py` |
| FR-10 self-contained packet | `packet`, `prompts`, `session` | `tests/domain/test_packet.py`, labs |
| FR-11 token budget | `packet` | `test_packet.py` |
| FR-12 clipboard and file fallback | `clipboard`, `session` | `tests/ui/test_ui.py`, `test_session.py` |
| FR-13 delta packets | `delta`, `lanes` | `tests/domain/test_delta_tdd.py`, lab 5 |
| FR-14 archive of packets and replies | `workspace`, `session` | `test_session.py` |
| FR-20 envelope grammar | `reply` | `tests/domain/test_reply.py` |
| FR-21 truncated and pasted packets | `reply`, `session` | `test_reply.py` |
| FR-22 batch validation | `changes`, `preflight` | `test_changes.py`, `test_preflight.py`, `tests/app/test_preflight_session.py` |
| FR-23 atomic apply | `session`, `workspace` | `test_session.py`, labs |
| FR-24 exact-once edits | `changes` | `test_changes.py` |
| FR-25 stale reply | `session`, `lanes` | `test_session.py`, `tests/app/test_lanes.py`, lab 5 |
| FR-26 auto-commit, next packet | `session`, `git` | labs |
| FR-27 undo | `session` | `test_session.py` |
| FR-28 `need` requests | `reply`, `session`, `codegraph` | `tests/adapters/test_codegraph.py`, `test_session.py` |
| FR-30 red then green | `tdd`, `session` | `test_delta_tdd.py`, labs 1, 2, 5 |
| FR-31 code-only retry, relaxed audit | `tdd`, `session` | `test_delta_tdd.py`, lab 4 |
| FR-32 human-owned checks | `config`, `session`, `runner` | `tests/app/test_config.py`, `test_session.py` |
| FR-33 evidence and blocking | `session` | `test_session.py` |
| FR-40 plan becomes issues | `scheduler`, `lanes` | `test_scheduler.py`, lab 5 |
| FR-41 `touches` exclusion | `scheduler` | `test_scheduler.py` |
| FR-42 chat assignment | `scheduler`, `lanes` | `test_scheduler.py`, `test_lanes.py` |
| FR-43 routing by header | `lanes`, `reply` | `test_lanes.py`, lab 5 |
| FR-44 stages and sent flag | `stage`, `lanes`, UIs | `tests/domain/test_stage.py`, `tests/ui/test_ui.py`, lab 5 |
| FR-45 event sequence | `lanes` | `test_lanes.py` |
| FR-50 recon evidence | `recon`, `codegraph`, `git` | labs 3, 4 |
| FR-51 adopt ends with recon doc | `recon`, `session` | lab 3 |
| FR-52 audit findings and characterization | `recon`, `tdd`, `session` | lab 4 |
| FR-60 CLI | `cli` | `tests/ui/test_ui.py`, `accept.py` |
| FR-61 web UI | `web`, `static/` | `tests/ui/test_ui.py` |
| FR-62 TUI | `tui` | `tests/ui/test_ui.py` |
| FR-63 watch | `session`, `cli` | `tests/ui/test_ui.py` |
| FR-64 doctor | `session` | `test_session.py` |
| FR-70 write confinement | `changes`, `workspace` | `test_changes.py` |
| FR-71 never execute reply commands | `session`, `runner` | `test_session.py` |
| NFR-2 narrow surface | all layers | `tests/test_layers.py` |

## 5. Data and state

* `.chatop/config.toml`: human-owned settings (checks, protected globs, limits, parallel options).
* `.chatop/state.json`: the whole workflow state (track, phase, status, turn, slices, questions, chats, decisions).
* `.chatop/journal.jsonl`: append-only event log.
* `.chatop/{packets,replies,undo,lanes}/`: archives and overlays (git-ignored).
* `docs/`: the memory the LLM maintains (IDEA, PRD, SPEC, PLAN, DELTA, RECON, AUDIT, DECISIONS).

Rule: the **chat history is never the memory**. Whatever a later turn needs is in `docs/` and arrives in the packet.

## 6. Extension recipes

| To add | Touch |
|---|---|
| Another code index than codegraph | one adapter implementing `CodeIndex`; wire it in `wiring.py` |
| Another clipboard or transport (a socket, a file watcher) | one adapter implementing `Clipboard` |
| Another UI | one shell over `Session`; never import `LaneEngine` or `domain` internals |
| A new phase | one prompt file and one entry in `workflow.TRACKS` |
| A new directive in replies | `reply.py`, `contract.md`, and the code that consumes it in `session.py` |
| A new preflight language | a `[preflight]` glob-to-command entry in config, or a checker in `preflight.py` |
| A new check | `chatop checks --set NAME CMD` (human-owned, never from a reply) |
| Another vendor's chat UI quirk | `reply.py` tolerance plus a test; nothing else |

## 7. Incorporating chatop into an existing product

Four adoption levels, from smallest to largest. Pick the lowest that meets the need.

| Level | What you take | Surface you integrate with | Effort | Use when |
|---|---|---|---|---|
| A. Protocol only | `prompts/contract.md` and the envelope grammar in `BEHAVIOR.md` | text in, text out | hours | You already have a tool that applies LLM output and want a safer format |
| B. Kernel | `bootstrap/relay.py` (stdlib, one file) | `pack` and `apply` commands; `.relay/` state | a day | You want packets plus safe, TDD-checked apply in a repo without installing the app |
| C. Library | `domain/` and `ports.py` (pure, no I/O) | `parse_reply`, `plan_changes`, `preflight`, `assemble`, scheduler and stage functions | days | You have your own application shell and storage and want the logic |
| D. Whole app | everything | the CLI (`status --json`, exit codes) or the `Session` facade | an afternoon to install | You want the complete workflow and UIs |

**Integration contract** (what must stay stable so the pieces keep working together):

1. The reply envelope and the apply rules (`BEHAVIOR.md` sections 5 and 6).
2. `status --json` keys and the CLI exit codes (0, 1, 3).
3. The `.chatop/` file layout and the `docs/` memory names.
4. The five ports and their result types.

**Checklist for an integrator or a coding agent**

1. Read `PRD.md` sections 4 to 7, then section 3 and 4 of this document.
2. Choose an adoption level; list the requirement IDs it must satisfy (the traceability table is the scope).
3. Implement behind the ports; keep `domain` free of I/O.
4. Prove conformance with the labs: `CHATOP=<your command> python bootstrap/accept.py all` for level D, the kernel
   acceptance script for level B, the domain unit tests ported for level C.
5. Keep requirement IDs in commit messages and test names so the trace stays queryable.
6. Where `PRD.md` and a lab disagree, the lab wins; fix the document.

**Porting to another language.** The contract is language-agnostic: the envelope grammar, apply rules and `status
--json` are specified without reference to Python. Reimplement the domain functions against `BEHAVIOR.md`, keep the same
ports as interfaces, and use `accept.py` unchanged: it only runs a command line.

## 8. Design trade-offs

| Choice | Gain | Cost |
|---|---|---|
| Line-oriented envelope instead of JSON | LLMs rarely break it; code needs no escaping | one limitation: a file with a line exactly `@@end` cannot be written with `@@file` |
| SEARCH/REPLACE edits instead of diffs | robust to wrong line numbers | the chat must see the current file |
| Red proof on every slice | TDD is enforced, not requested | one extra test run per slice |
| Human-owned checks | an LLM cannot run arbitrary commands | one setup step per project |
| Files instead of a database | trivially inspectable, diffable, resumable | no concurrent writers beyond the file-overlap rule |
| One facade, thin shells | UIs are cheap and consistent | `Session` is large (it is the one place that grows) |
