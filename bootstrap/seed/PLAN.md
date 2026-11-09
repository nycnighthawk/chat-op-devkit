# Plan: rebuild chatop from nothing (reference plan, 11 slices)

Rules for every slice: tests first (several test files in one reply is fine), then the code, one reply per slice,
type-annotated Python 3.11+, `ruff` and `mypy --strict` clean, no file over 400 lines. Core code imports only
`chatop.domain` and `chatop.ports`; adapters and UIs are the outside. The behavior contract is `docs/BEHAVIOR.md`;
the lab runner `accept.py` is the final oracle.

Waves (what can be open in separate chats at the same time): **A** S1, S4 | **B** S2, S3, S5 | **C** S6 then S7 |
**D** S8, S9 | **E** S10, S11. After wave C the labs `lab1` and `lab2` must pass: that is the moment chatop adopts
itself and the remaining waves run through chatop.

## S1: Models and the reply parser
- depends: none
- touches: src/chatop/__init__.py, src/chatop/domain/__init__.py, src/chatop/domain/models.py, src/chatop/domain/reply.py, tests/domain/test_models.py, tests/domain/test_reply.py
- reads: docs/BEHAVIOR.md
- goal: `Track`, `Phase`, `Status` enums; `State`, `Slice`, `Question`, `Chat` dataclasses with JSON round trip; `parse_reply(text) -> Reply` for every directive in BEHAVIOR 5, with truncated, packet-pasted, missing-header and unknown-directive reported as errors, not exceptions.
- acceptance: parser tests cover each directive, edit blocks with several SEARCH/REPLACE pairs, a fence-wrapped reply, CRLF input, an `@@ask` with recommended and other options; `State` survives `from_json(to_json(s)) == s`.

## S2: Applying changes safely
- depends: S1
- touches: src/chatop/domain/changes.py, src/chatop/domain/preflight.py, src/chatop/domain/tdd.py, tests/domain/test_changes.py, tests/domain/test_preflight.py, tests/domain/test_tdd.py
- reads: docs/BEHAVIOR.md, src/chatop/domain/reply.py
- goal: pure functions: `plan_changes(ops, read) -> (changes, problems)` with path safety and exact-once edits (whitespace-tolerant fallback); `preflight(changes)` collecting every syntax problem in one pass (ast, json, toml); the TDD rules of BEHAVIOR 5.6 as a small decision function (`red_expected`, `code_only_allowed`).
- acceptance: every rule in BEHAVIOR 5.1 to 5.6 has a test; problems from several files come back in one list.

## S3: Workflow, scheduler, stage, packet
- depends: S1
- touches: src/chatop/domain/workflow.py, src/chatop/domain/scheduler.py, src/chatop/domain/stage.py, src/chatop/domain/packet.py, src/chatop/domain/delta.py, tests/domain/test_workflow.py, tests/domain/test_scheduler.py, tests/domain/test_stage.py, tests/domain/test_packet.py
- reads: docs/BEHAVIOR.md, docs/ARCHITECTURE.md, src/chatop/domain/models.py
- goal: pure state machine (tracks, gates, auto-advance, slice activation, `start_feature`); plan validation (cycles, unknown deps, duplicates); `ready_issues`, file-overlap exclusion, best-chat choice; the stage of a chat (your move / waiting for the LLM / applying / closed); packet assembly with a token budget (`~4 chars/token`) and per-chat digests so a continuing chat gets only changes.
- acceptance: transitions table-tested for all four tracks; scheduler never returns two overlapping issues; packet stays under budget and drops low-priority context first.

## S4: Ports and adapters
- depends: none
- touches: src/chatop/ports.py, src/chatop/adapters/__init__.py, src/chatop/adapters/clipboard.py, src/chatop/adapters/codegraph.py, src/chatop/adapters/git.py, src/chatop/adapters/runner.py, tests/adapters/test_clipboard.py, tests/adapters/test_codegraph.py, tests/adapters/test_git.py, tests/adapters/test_runner.py
- reads: docs/BEHAVIOR.md, docs/CODEGRAPH-CLI.md
- goal: the five Protocols (`CodeIndex`, `Clipboard`, `Runner`, `Vcs`, plus the `SymbolHit`/`RunResult` types) and one adapter each. The codegraph adapter takes an injectable `exec(cmd) -> (code, stdout)` and tolerates missing fields; the clipboard auto-detects pbcopy, wl-copy, xclip, xsel, else files; git uses the real binary.
- acceptance: contract tests with injected exec for codegraph (found, empty, binary missing); clipboard picks `file` when `CHATOP_CLIPBOARD=file`; git commit/churn/tracked files in a temp repo; runner timeout returns code 124.

## S5: Workspace, config, prompts
- depends: S1
- touches: src/chatop/app/__init__.py, src/chatop/app/workspace.py, src/chatop/app/config.py, src/chatop/app/prompts.py, tests/app/test_workspace.py, tests/app/test_config.py, tests/app/test_prompts.py
- reads: docs/BEHAVIOR.md, src/chatop/prompts/contract.md, src/chatop/prompts/system.md
- goal: `Workspace` (paths, state load/save, journal append, git-ignore of `.chatop/{packets,replies,undo,lanes}`), `Config` from TOML with `set_option` type coercion and `[checks]`/`[preflight]` tables, and `render_prompt(name, **vars)` over the files in `src/chatop/prompts/` (packaged data).
- acceptance: config round trip; unknown keys ignored; `protected` defaults include `.git/**`, `.chatop/**`, `.env*`.

## S6: Session, the serial core
- depends: S2, S3, S4, S5
- touches: src/chatop/app/session.py, src/chatop/app/results.py, src/chatop/app/wiring.py, tests/app/test_session.py, tests/app/test_session_tdd.py
- reads: docs/BEHAVIOR.md, docs/ARCHITECTURE.md, src/chatop/ports.py
- goal: `Session(workspace, index, clipboard, runner, vcs)` with `init`, `next_packet`, `apply`, `answer`, `accept_recommended`, `approve`, `reject`, `feature`, `undo`, `status`, `doctor`, and `wiring.build_session(root)` as the only composition root. Real git and real pytest in temp dirs in tests, fakes for index and clipboard.
- acceptance: the new-project flow idea -> done with scripted replies; red proof; failing green keeps files and returns evidence; rejected reply changes nothing; undo.

## S7: CLI
- depends: S6
- touches: src/chatop/ui/__init__.py, src/chatop/ui/cli.py, pyproject.toml, tests/ui/test_cli.py
- reads: docs/BEHAVIOR.md section 2 and 4
- goal: `main(argv, session_factory)` with every command of BEHAVIOR 2 that exists by now (parallel commands are added in S9), global `-C`, `status --json`, exit codes 0/1/3, `[project.scripts] chatop = chatop.ui.cli:main` and packaged prompt files in `pyproject.toml`.
- acceptance: **`CHATOP=chatop python accept.py lab1` and `lab2` pass.** Then stop and run the "adopt yourself" play before continuing.

## S8: Recon, adopt and audit tracks
- depends: S7
- touches: src/chatop/app/recon.py, tests/app/test_recon.py
- reads: docs/BEHAVIOR.md, src/chatop/prompts/recon.md, src/chatop/prompts/audit.md
- goal: build the recon evidence for unknown projects with codegraph (repo map, entry points, churn from git, test inventory, who wrote it: agent markers such as AGENTS.md and Co-Authored-By trailers), plus the adopt and audit transitions in `Session` (small `@@edit` blocks only).
- acceptance: `accept.py lab3` and `lab4` pass.

## S9: Parallel relay (lanes)
- depends: S7
- touches: src/chatop/app/lanes.py, tests/app/test_lanes.py
- reads: docs/BEHAVIOR.md section 6, docs/ARCHITECTURE.md, src/chatop/domain/scheduler.py, src/chatop/domain/stage.py
- goal: chats, dispatch and assign, delta packets, reset-chat, sent flag, board, event sequence; the CLI verbs `board dispatch assign reset-chat sent`, `next CHAT`, `--parallel` (small `@@edit` blocks in `cli.py` and `session.py` only).
- acceptance: `accept.py lab5` passes; replies applied in any order land in the right chat.

## S10: Web UI
- depends: S9
- touches: src/chatop/ui/web.py, src/chatop/ui/static/app.html, tests/ui/test_web.py
- reads: docs/UX.md, docs/BEHAVIOR.md section 4, src/chatop/ui/cli.py
- goal: FastAPI app (`chatop web`) as a thin shell over `Session`: projects hub, per-project board by stage, paste box that routes to the right chat, "I pasted it" flag, approve/reject, polling by `event_seq`. No logic of its own.
- acceptance: TestClient tests for every route; the paste route applies a reply and the board moves the chat to "closed".

## S11: TUI
- depends: S9
- touches: src/chatop/ui/tui.py, tests/ui/test_tui.py
- reads: docs/UX.md, src/chatop/ui/web.py
- goal: Textual app (`chatop tui`) with the same board and actions as the web UI, keyboard first.
- acceptance: Textual pilot tests: open board, flag sent, paste, approve.
