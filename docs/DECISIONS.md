# Architecture decision log

Each entry: context → decision → alternatives → consequences.

## ADR-001: Build an app (a harness), not just a prompt pack
* **Context.** Turn cost is dominated by context gathering and manual application, not by the LLM's thinking.
* **Decision.** A local app (`chatop`) builds packets, applies replies, runs checks and keeps state.
* **Alternatives.** Prompt templates only (manual mode): about 3-5× more turns, and unverified code.
* **Consequences.** A Python dependency on the dev machine. The protocol still works manually.

## ADR-002: A line-oriented reply envelope, not JSON
* **Context.** Code in JSON needs escaping, and LLMs regularly break the escaping. Chat UIs mangle some fences.
* **Decision.** `<<<CHATOP turn=N>>>` … `<<<END>>>` with `@@directive` lines and `@@end` block terminators,
  wrapped in a 4-backtick fence so inner triple-backtick fences survive and the UI's copy button grabs the whole block.
* **Alternatives.** JSON (escaping errors), raw markdown (ambiguous), tool calls (not available in plain chat).
* **Consequences.** A file containing a line that is exactly `@@end` cannot be written with `@@file`. This is
  negligible and documented.

## ADR-003: SEARCH/REPLACE edits, not unified diffs
* **Context.** LLM-written unified diffs often have wrong line numbers or hunk counts.
* **Decision.** `@@edit` with exact SEARCH blocks that must match once, plus a trailing-whitespace-tolerant fallback,
  plus `@@file` for rewrites.
* **Consequences.** Ambiguous or missing matches are rejected with a repair prompt; nothing is half-applied.

## ADR-004: Two-stage apply makes TDD verifiable in one turn
* **Context.** TDD normally needs a red turn and a green turn. Without enforcement, "tests first" is on the honour system.
* **Decision.** In SLICE, tests (by `@@test` or a path pattern) are written first and the `test` check must fail.
  Then the code is written and all checks must pass. `red_proven` is remembered per slice, so code-only fixes on a
  retry are allowed. The audit track and `@@advance` relax this for characterization and refactor slices.
* **Consequences.** It costs one extra test run per slice. It caught a mis-specified characterization in Lab 4.

## ADR-005: The repo is the memory; packets are stateless
* **Context.** Long chats drift and lose early decisions. Different LLMs or chats may be used across phases.
* **Decision.** All memory lives in `docs/` and `.chatop/state.json`. Each packet includes a state digest, decisions,
  recent history and the relevant docs.
* **Consequences.** A fresh chat per phase is free. The docs stay current because the LLM must maintain them.

## ADR-006: Ports and adapters, one Session facade, three thin UIs
* **Context.** The CLI, TUI and web UI were required. Integration surfaces must be narrow to localize change.
* **Decision.** A pure `domain/`; `ports.py` Protocols (CodeIndex, Clipboard, Runner, Vcs); `adapters/`; a
  `Session` facade that is the only API the UIs call; one composition root (`wiring.py`).
* **Consequences.** UIs carry no logic, so they are tested shallowly. Swapping codegraph or the clipboard is one file.

## ADR-007: codegraph is the only code search, behind a schema-tolerant adapter
* **Context.** Requirement: use the codegraph CLI to search code. Its JSON output is not formally specified.
* **Decision.** `CodegraphIndex` wraps `init -i | sync | status | query | callers | callees | impact | files |
  affected`, and `normalise_hits` walks any JSON shape to find name, file and line objects. Failures degrade to
  empty context, never to a crash. Local recon uses only git and file metadata, never text grep.
* **Consequences.** Without codegraph, symbol context is empty (`chatop doctor` flags it). File-path `touches` and
  `@@need file` still work.

## ADR-008: Check commands are human-owned
* **Context.** Running LLM-authored shell commands is a remote-code-execution risk.
* **Decision.** chatop runs only `[checks]` from `config.toml`. The LLM may `@@check`-propose; the human accepts
  explicitly or at a gate. `.chatop/**` is protected from writes.
* **Consequences.** Once per project, the human reads one or two commands.

## ADR-009: Packet budget defaults to 80K tokens
* **Context.** The target LLMs have ≥250K context. The packet, the reply (up to ~30K) and a few turns of history
  must fit, and very long prompts degrade attention.
* **Decision.** `budget_tokens = 80000`. Sections have priorities (0 = never cut; repo map cut first). Truncation
  notes tell the LLM to use `@@need`.
* **Consequences.** Typical packets are 2-20K. Large repos rely on precise `touches`.

## ADR-010: Stack: Python ≥3.11 typed core, FastAPI and Textual for the UIs
* **Context.** The user chose FastAPI + Textual. Type annotations are required.
* **Decision.** Stdlib-only core (dataclasses, tomllib, subprocess). `mypy --strict` and ruff in CI. FastAPI is bound
  to localhost. The web page is vanilla JS (no build step).
* **Consequences.** Three runtime deps (fastapi, uvicorn, textual).

## ADR-011: Clipboard ping-pong (watch mode)
* **Context.** Even `chatop apply` is a context switch per turn.
* **Decision.** `watch_tick` polls the clipboard. When an envelope for the current turn appears, it is applied
  and the next packet is copied. Packets carry a `# CHATOP PACKET` marker and are never mistaken for replies.
* **Consequences.** The human loop is: paste in chat → click copy. Questions and gates still need the terminal, TUI or web.

## ADR-012: Gates at PRD, SPEC, DELTA, PLAN, AUDIT only
* **Context.** Human attention is the scarcest resource. Slices are verified mechanically.
* **Decision.** Approvals happen at the documents that fix scope or architecture. Slices auto-advance on green checks
  and auto-commit.
* **Consequences.** `gates` in config can add or remove gates per team taste.

## ADR-013: Parallel relay is opt-in; serial stays the default
* **Context.** The human is idle while a chat writes. Several chats can work at once if the plan allows it.
* **Decision.** `max_parallel` (default 1). At 1, nothing changes. Above 1, an approved plan is turned into issues and
  dispatched to chats. Serial and parallel share the apply pipeline (`_stage`, `judge_slice`), so TDD rules are identical.
* **Alternatives.** Parallel only (rewrites every flow and lab); a second app mode (two code paths to maintain).
* **Consequences.** A project can switch at any time (`chatop config --set max_parallel 3`); a running serial issue
  is adopted as a chat. Parallel needs `auto_commit` because a commit is what ends an issue.

## ADR-014: Replies carry their chat id; paste routing is by header
* **Context.** With several chats, "which chat did this come from?" must not be a human decision.
* **Decision.** The header is `<<<CHATOP chat=c2 turn=3>>>`. The contract tells the model to copy it verbatim. A
  headerless reply routes only when exactly one chat is waiting (or one matches the turn). Unknown chats and stale
  turns are rejected with a repair prompt.
* **Consequences.** Replies can arrive in any order; a packet pasted into the wrong tab still produces a correctly
  routed reply. Cost: one more attribute for the model to echo; the repair path covers the rare omission.

## ADR-015: Continuing chats get deltas, tracked by content digests
* **Context.** Resending SPEC, PRD and unchanged files every turn wastes tokens and reading time, and the chat
  already has them.
* **Decision.** Each chat records a digest per context item (`doc:`, `file:`, `symbol:`, `repomap`, `task:`). A
  packet contains only items whose digest changed, plus one line naming the rest. "Copy full" or `reset-chat`
  clears the record for fresh tabs. A chat is reused for the next issue only if it already holds one of that issue's
  files; otherwise a fresh chat avoids carrying unrelated context.
* **Alternatives.** Always full packets (simple, costly); reuse any free chat (cheaper bootstrap, but long unrelated
  history degrades output, so `max_issues_per_chat` caps it anyway).
* **Consequences.** In Lab 5 a continuing chat's packet is about a fifth of a full one. A chat that silently lost
  its history is the failure mode; the recovery is one button.

## ADR-016: One-shot preflight over all generated files
* **Context.** A syntax error in one of five generated files used to cost a whole round trip, once per file.
* **Decision.** Before anything runs, every changed file is checked together: Python (`ast`), JSON and TOML are
  built in and pure; project linters are configured per glob in `[preflight]` and run once over all matching files
  (`{files}`), with the files restored on failure. All diagnostics are merged with edit mismatches into one repair prompt.
* **Consequences.** One rejection instead of several. External linters only run on files that parse, so a linter's
  confusing output on broken syntax is avoided; its output is parsed best-effort (`path:line:col: message`).

## ADR-017: Lane isolation through overlays and serialised applies, not worktrees
* **Context.** Two chats' half-finished code must not break each other's checks.
* **Decision.** Each chat's uncommitted files are an overlay in `.chatop/lanes/`. An apply materialises that
  chat's overlay in the shared tree, runs the checks, then commits (green) or restores the tree (red). Applies are
  serialised. Overlay entries record their base so a file committed by another chat is detected as a conflict.
* **Alternatives.** One git worktree per chat (true isolation, but dependency installs and tool state per tree, and
  merges to resolve); no isolation (one chat's red tests block everyone).
* **Consequences.** Cheap and simple; apply time is serial (seconds) while LLM time (minutes) overlaps. `undo`
  is disabled once chats exist (use `git revert`).

## ADR-018: Scheduling by `depends` and `touches`
* **Context.** Parallelism is only safe when issues are independent.
* **Decision.** An issue is ready when its `depends` are done. Issues with overlapping `touches` (equal path or
  parent directory; empty means "unknown, assume overlap") never run together. The PLAN prompt asks the model for
  both, chatop rejects cycles, and warns when the plan is wider than `max_parallel`.
* **Consequences.** Imprecise `touches` reduce parallelism rather than cause conflicts; conflicts that still happen
  are caught at apply time.

## ADR-019: The clipboard is a human resource
* **Context.** Auto-copying the next packet is great in serial work and harmful when you are holding a reply.
* **Decision.** Packets are copied on request. After an apply, chatop copies the next packet automatically only if no
  other chat is waiting for a reply or being applied; otherwise it shows a "next up" button and the board hint.
* **Consequences.** No clobbered clipboards. With `watch`, replies are consumed from the clipboard and routed.

## ADR-021: The board is organised by who acts next, with an explicit "I pasted it" flag
* **Context.** With several chats, a card per status ("awaiting reply") does not tell the human what to do. "Waiting"
  hid two different situations: a packet copied but not pasted yet, and a packet pasted into a chat that is writing.
* **Decision.** Derive a `stage` and an `owner` for every chat (`domain/stage.py`, pure, shared by every UI): `send`,
  `paste`, `fix`, `answer`, `blocked` belong to the human; `waiting` to the LLM; `applying` to chatop; `closed` to
  nobody. Add `Chat.sent_at`, set by `mark_sent` (CLI `chatop sent`, `POST /api/chat/sent`, the "I pasted it" button),
  because chatop cannot observe the chat window. The page groups chats into *Your move* and *Waiting for the LLM*,
  has one primary button per card and one for the screen (**N**), and routes a reply pasted anywhere on the page.
* **Consequences.** The human always sees the next action first; the flag is optional (forgetting it costs only an
  unclear card). The multi-project hub is a mock-only proposal: it needs a project registry the app does not have.
  Rationale and the UX laws are in docs/UX.md.

## ADR-020: The mock UI is the real page on a fake backend
* **Context.** People should be able to try the workflow without installing anything, and a hand-drawn mock drifts.
* **Decision.** The web page talks to the server only through `window.CHATOP_API`. `docs/chatop-mock-ui.html` embeds
  that exact page, an in-browser backend that mirrors the lane rules (tested with node against the same scenario as
  Lab 5) and scripted chat tabs. It is rebuilt from sources and checked for drift in the test suite.
* **Consequences.** The mock shows true UI behavior; the build, tests and LLM in it are scripted, which it says so.
