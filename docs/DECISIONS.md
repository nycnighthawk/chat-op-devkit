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
