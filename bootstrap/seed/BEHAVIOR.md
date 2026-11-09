# chatop behavior contract (v0.1)

This is the externally visible behavior a rebuilt chatop must have. It is deliberately about *what*, not *how*:
the architecture (docs/ARCHITECTURE.md) says how. Where this document and a lab (`accept.py`) disagree, **the lab
wins** and this document gets fixed.

## 1. Product in one paragraph

chatop is a relay between a human and chat LLMs that have no repo access. It keeps project state in `.chatop/`,
builds a **packet** (the exact text to paste into a chat), and applies the chat's **reply** (a structured envelope)
to the repo with checks. Two shells (CLI, web, TUI) sit on one core. macOS and Linux only. Code search is the
`codegraph` CLI only. No coding agent or harness is ever invoked.

## 2. CLI (the stable surface)

Global: `chatop [-C DIR] <command>`; `-C` is the project root (default `.`). Exit codes: `0` ok, `1` rejected or
user error (nothing changed), `3` reply applied but checks failed (files stay in place, evidence recorded).

| Command | Behavior |
|---|---|
| `init [--track new\|adopt\|audit] [--idea T] [--idea-file F] [--parallel N]` | create `.chatop/`; without `--track`: empty or no code -> `new`; code+tests+test command -> `adopt`. `new` writes `docs/IDEA.md`; `adopt`/`audit` index the code. Check commands are auto-detected (e.g. pytest) into `config.toml`. `--parallel N` sets `max_parallel`. A second `init` is refused (exit 1) and points at `feature` |
| `status [--json]` | where am I and what next (schema in 4) |
| `next [CHAT] [--full] [--accept] [--approve] [--print] [--no-clip]` | build the next packet; copy to the clipboard (or `.chatop/outbox.md` when `CHATOP_CLIPBOARD=file`); save to `.chatop/packets/` |
| `apply [FILE\|-] [--force]` | apply a reply from file, stdin or clipboard (`CHATOP_CLIPBOARD=file` reads `.chatop/inbox.md`) |
| `answer [QID CHOICES... --other T --chat C]`, `accept [--chat C]` | answer pending questions; `accept` takes every recommended option |
| `approve [--note T]`, `reject NOTE` | gate decisions; `approve` also accepts the checks the LLM proposed |
| `checks [--accept] [--set NAME CMD] [--unset NAME]` | show/accept/set check commands (only the human can accept) |
| `feature TEXT [--force]` | start the continue track on a finished project |
| `undo` | revert the last applied, uncommitted reply |
| `watch [--interval S]` | clipboard ping-pong: apply replies as they appear, copy the next packet |
| `board [--json]`, `dispatch`, `assign ISSUE [--chat C]`, `reset-chat CHAT`, `sent CHAT [--undo]` | parallel relay (6) |
| `config [--set K V]`, `doctor`, `tui`, `web [--port P --host H]` | options, environment check, shells |

## 3. Workflow

Tracks and phases (a phase is left only through the rules below):

* `new`: idea -> refine -> prd -> spec -> plan -> slice -> done
* `continue` (via `feature`): feature -> refine -> delta -> plan -> slice -> done
* `adopt`: recon -> done; `audit`: recon -> audit -> plan -> slice -> done

Statuses: `ready` -> `awaiting_reply` -> (`awaiting_answers` | `awaiting_approval` | `ready`) ... -> `done`.

* Phases `idea`, `feature`, `recon` advance after one reply. Others advance on `@@advance`.
* Gated phases (default `prd, spec, delta, plan, audit`) wait in `awaiting_approval` until `approve`; `reject` sends
  the phase back with the human's note in the next packet.
* `refine` is bounded (`max_refine_rounds`=3, `max_questions`=6). Unanswered questions block `next`.
* `plan` accepts `@@slices` JSON: `[{"id","title","goal","depends":[],"touches":[],"tests":[],"acceptance":[]}]`.
  Unknown dependencies, cycles, duplicate ids and ids that already exist are rejected with all problems listed.
* `slice` runs one issue at a time (serial) or many (parallel). A slice is done when its tests are green and the
  configured checks pass; `max_attempts`=4 failures block the issue for a human decision.
* `done` + `feature TEXT` starts the continue track (refuses mid-phase unless `--force`).

## 4. `status --json` (consumed by the labs, the web UI and the mock)

Keys: `mode` (serial|parallel), `chats` (list of `{id, issue, status, turn, kind, sent}`), `event_seq`, `max_parallel`,
`project`, `track`, `phase`, `status`, `turn` (int, the number the next packet will carry), `hint`, `slice`
(`{id,title,attempts}` or null), `slices` (`[{id,title,status}]`), `questions`, `proposed_checks`, `checks`,
`decisions` (last 10), `history` (last 10), `evidence`, `clipboard` (adapter name).

## 5. Reply envelope

A reply contains one fenced block (4 backticks, `chatop`, tolerated when missing but a bare envelope must start with
the header). First line `<<<CHATOP chat=cN turn=N>>>`, last line `<<<END>>>`. A reply without the terminator is
**truncated** and rejected. A packet (starts with `# CHATOP PACKET`) pasted as a reply is rejected.

Directives: `@@summary`, `@@file`/`@@test`/`@@doc PATH ... @@end` (whole file), `@@edit PATH` with one or more
`<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks ... `@@end`, `@@delete PATH`, `@@ask ID [single]` with
`- [x] recommended` / `- [ ] option` lines ... `@@end`, `@@slices` JSON `@@end`, `@@need KIND TARGET`
(symbol|file|callers|callees|impact|affected), `@@decision TEXT`, `@@check NAME CMD`, `@@run CHECK`, `@@advance`.

Apply rules (all are testable through the CLI):

1. **All problems at once.** Parse and preflight every file, collect every problem, reject with the full list and
   a repair prompt. A rejected reply changes nothing (exit 1).
2. **Paths.** Relative, inside the repo, never `.git/`, `.chatop/`, secrets or the configured `protected` globs.
3. **Edits.** SEARCH must match exactly once; trailing-whitespace-tolerant fallback; ambiguous or missing -> problem.
4. **Preflight.** Python files via `ast`, `.json`, `.toml` parse before anything is written; extra linters from
   `[preflight]` (glob -> command with `{files}`) run on the staged result.
5. **Stale turn.** A reply whose `turn` (or chat) does not match the packet it answers is rejected as stale.
6. **TDD (strict by default).** Tests are written first; with the code held back they must **fail** (red). Then the
   code goes in and they must pass (green). A reply with tests whose red step passes is rejected. A code-only
   reply is allowed when an earlier attempt of the same slice left failing tests. Docs-only replies skip tests.
7. **Checks fail after apply** -> files stay, evidence (command output tail) goes into the next packet, exit 3.
8. **Success** -> auto-commit (`auto_commit`), journal entry, state advances, next packet is ready (`auto_next`).
9. `@@check` only *proposes*; `@@run` runs only configured checks. A command from the reply is never executed.

## 6. Parallel relay

`init --parallel N` / `config --set max_parallel N`. After approving the plan, `dispatch` gives each ready issue
(dependencies done) to a chat; chats are named `c1..`. Rules: a chat with a free slot and shared files is reused
(at most `max_issues_per_chat`=3, then a fresh chat); `next cN` builds that chat's packet (full for a new chat,
**delta** for a continuing one: only changed context items). `apply` routes by the header's chat id, in any order.
`sent cN` flags the packet as pasted (stage "waiting for the LLM"); applying a reply clears it. `board` lists chats
by stage: your move / waiting for the LLM / applying / closed. Issues whose `touches` overlap never run at once; an issue with empty `touches` overlaps everything.

## 7. Files

`.chatop/config.toml` (human-owned), `.chatop/state.json` (commit it), `.chatop/journal.jsonl` (append-only),
`.chatop/{packets,replies,undo,lanes}/` (git-ignored), `docs/` (the LLM-maintained memory: PRD, SPEC, PLAN, DELTA,
RECON, AUDIT, DECISIONS). Packets are `turn-NNNN.md` (serial) or `cN-turn-NNNN.md` (parallel).

## 8. Adapters (ports)

`CodeIndex` (codegraph CLI: `index/status/query/callers/callees/impact/files/affected`), `Clipboard` (pbcopy,
wl-copy, xclip/xsel, file fallback; `CHATOP_CLIPBOARD=file` forces the file one), `Runner` (shell checks with timeout),
`Vcs` (git). Core code imports only these protocols. Everything is injectable for tests.

Codegraph command lines the adapter uses (the binary is `codegraph`, run with the project root as cwd; verify them
against `codegraph --help` in `docs/CODEGRAPH-CLI.md` before trusting them): `init -i ROOT` (first time) or `sync ROOT`;
`status ROOT`; `query TEXT --limit N --json`; `callers SYM --limit N --json`; `callees SYM --limit N --json`;
`impact SYM --depth N --json`; `files --max-depth N`; `affected FILE... --quiet`. JSON is parsed tolerantly: walk the
document and accept any object that has a name and a file (keys `name|symbol`, `kind`, `file|path|filePath`,
`line|startLine`); a non-zero exit or invalid JSON means "no hits", never an exception. The exec function is injected
so tests never need the real binary.

## 9. Not in this contract

Exact packet wording, prompt text (provided as files), terminal colors, web layout. These are free to differ as long
as the labs pass.
