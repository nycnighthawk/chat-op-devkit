# Architecture

## Layers and the import rule

```mermaid
flowchart TB
  subgraph UI["ui/ (thin shells)"]
    CLI[cli.py argparse] --- TUI[tui.py Textual] --- WEB[web.py FastAPI + static/index.html]
  end
  subgraph APP["app/"]
    S[session.py — Session facade]:::core
    LN[lanes.py — LaneEngine: dispatch, route, delta packets, lane apply, mark_sent]:::core
    W[workspace.py]:::core
    R[recon.py]:::core
    C[config.py]:::core
    WI[wiring.py — composition root]
  end
  subgraph DOM["domain/ (pure, no I/O)"]
    RP[reply.py parser] --- CH[changes.py planner] --- PK[packet.py budgeter] --- WF[workflow.py state machine] --- M[models.py]
    PF[preflight.py batch lint] --- SC[scheduler.py] --- DL[delta.py] --- TD[tdd.py verdict]
  end
  subgraph PORTS["ports.py (Protocols)"]
    CI[CodeIndex] --- CB[Clipboard] --- RN[Runner] --- V[Vcs]
  end
  subgraph AD["adapters/"]
    CG[codegraph.py] --- CL[clipboard.py] --- SR[runner.py] --- G[git.py]
  end
  UI --> S
  S --> LN
  LN --> DOM
  S --> DOM
  S --> PORTS
  AD -. implements .-> PORTS
  WI --> AD
  WI --> S
```

| Layer | May import | Must not import |
|---|---|---|
| `domain` | stdlib, `domain` | everything else |
| `ports` | stdlib | everything else |
| `adapters` | stdlib, `ports` | `domain`, `app`, `ui` |
| `app` | `domain`, `ports`, stdlib | `adapters` (except `wiring.py`), `ui` |
| `ui` | `app`, `domain.models` (enums) | `adapters`, `domain` internals |

**Why it stays local.** A new code-search tool is one adapter. A new UI is one shell over `Session`. A new phase is one
prompt file plus one entry in `workflow.TRACKS`. A reply-format change touches `reply.py` and `contract.md` only.

## Boundary surfaces (the only things that cross)

| Boundary | Surface |
|---|---|
| LLM → chatop | text, through `parse_reply(text) -> Reply` |
| chatop → LLM | text, from `assemble(sections, budget) -> (str, notes)` |
| UI → core | `Session`: `init, detect_track, build_packet(chat=, full=), apply, answer(chat=), accept_recommended(chat=), approve, reject, accept_checks, feature, undo, watch_tick, status, doctor` plus the parallel surface `dispatch, assign, next_up, route, board, events_since, reset_chat, configure` (the UIs never import `LaneEngine`) |
| core → codegraph | `CodeIndex` (9 methods), CLI flags `--json`, `--limit`, `--depth`, `--quiet` |
| core → OS | `Clipboard.copy/paste`, `Runner.run`, `Vcs` (5 methods), and `Workspace` (root-confined fs) |

## One turn, end to end

```mermaid
sequenceDiagram
  actor H as Human
  participant C as chatop (Session)
  participant G as codegraph
  participant L as Chat LLM
  H->>C: chatop next / watch
  C->>G: sync, query/callers/impact/affected (touches + @@need)
  C->>C: assemble sections under budget, save packets/turn-N.md
  C-->>H: packet on clipboard
  H->>L: paste
  L-->>H: ````chatop <<<CHATOP turn=N>>> … <<<END>>>
  H->>C: copy (watch) or chatop apply
  C->>C: parse → validate paths → resolve edits in memory
  alt any error
    C-->>H: repair prompt on clipboard (nothing changed)
  else slice with tests + code
    C->>C: write tests → run test (must FAIL) → write code
    C->>C: run all checks → commit if green → advance
  end
  C-->>H: next packet on clipboard (auto_next)
```

## Parallel relay (lanes)

A *chat* is one browser tab the human relays to. State lives in `State.chats` and `State.events`; each issue (slice)
has `depends`, `touches` and `lane`. The UIs do not show the raw status: `domain/stage.py` derives who acts next
(`send`/`paste`/`fix`/`answer`/`blocked` = you, `waiting` = the LLM, `applying` = chatop, `closed`) from the status, the
"I pasted it" flag (`Chat.sent_at`) and the repair prompt, and `board()` returns it with a summary (docs/UX.md).

```mermaid
stateDiagram-v2
  [*] --> queued: issue assigned to a NEW chat (full packet)
  [*] --> ready: issue assigned to a chat that holds its files (delta packet)
  queued --> awaiting_reply: build_packet(chat)
  ready --> awaiting_reply: build_packet(chat)
  awaiting_reply --> applying: reply routed by header
  awaiting_reply --> awaiting_reply: rejected (syntax / mismatch / conflict): repair prompt
  applying --> ready: red or partial: evidence kept, next packet is a delta
  applying --> needs_input: @@ask
  applying --> blocked: attempts >= max_attempts
  applying --> done: green: committed, dependents unblocked
  needs_input --> ready: answered
  blocked --> ready: reset_chat
  done --> ready: reused for another issue
```

**Applying a reply in a lane** (`LaneEngine._apply_checked`, under the session's `_apply_lock`):

```mermaid
flowchart LR
  A[route by header] --> B[plan edits against the chat's VIEW: overlay over tree]
  B --> C[built-in syntax check of ALL files + conflict check]
  C -->|errors| R[one rejection, repair prompt, nothing changed]
  C --> D[materialise overlay in the tree]
  D --> E[external linters once per glob]
  E -->|errors| X[restore tree, reject]
  E --> F[tests only: must FAIL = RED]
  F --> G[all checks]
  G -->|green| H[commit, drop overlay, dispatch dependents]
  G -->|red| I[restore tree, keep overlay, evidence for the next delta packet]
```

Isolation uses an overlay plus serialised applies instead of git worktrees: no per-chat checkout, no dependency
reinstall, and the check commands run in the real project directory. The cost is that applies queue (the LLM wait,
not the apply, is what overlaps). Locks: `_apply_lock` guards the tree; `_state_lock` guards short state mutations so
the UIs can poll `board()` while checks run.

**Delta packets.** `domain.delta.plan_delta` compares `chat.seen` (content digests of what the chat holds) with the
current documents, files and repo map. A full packet sends everything and records the digests; a delta sends the
changed items and names the rest. Files the chat wrote itself are recorded after each apply so they are not sent back.

**Events.** Every transition that matters to a human (`ready`, `done`, `question`, `blocked`, `rejected`, `finished`)
appends `{seq, ts, kind, chat, issue, text}` to `State.events`. UIs poll `board()` and show anything newer than the
last `seq` they saw: toast + tab title in the web UI, notifications in the TUI, `chatop board` in the CLI.

## State machine

```mermaid
stateDiagram-v2
  [*] --> idea: new
  idea --> refine
  refine --> refine: questions
  refine --> prd: @@advance
  prd --> spec: approve
  spec --> plan: approve
  plan --> slice: approve
  slice --> slice: next slice / retry
  slice --> done
  done --> feature: chatop feature
  feature --> refine
  refine --> delta: (continue track)
  delta --> plan: approve
  [*] --> recon: adopt/audit
  recon --> done: adopt
  recon --> audit: audit
  audit --> plan: approve
```

Statuses: `ready → awaiting_reply → (awaiting_answers | awaiting_approval | ready) … → done`.

## Data layout in a managed project

```
.chatop/
  config.toml      human-owned: checks, gates, budget, protected globs, tdd_strict, auto_commit, auto_next,
                   max_parallel, max_attempts, max_issues_per_chat, auto_dispatch, delta_packets, [preflight]
  state.json       track, phase, status, turn, slices (+depends, lane), chats, events, questions, needs, decisions,
                   history, evidence (commit it)
  journal.jsonl    append-only audit trail of every init/apply/reject/approve
  packets/ replies/ undo/ lanes/   per-turn artifacts and per-chat overlays (git-ignored; chat packets are cN-turn-NNNN.md)
docs/              the human-readable memory the LLM maintains
```

## Testing strategy (chatop itself)

| Level | Folder | Notes |
|---|---|---|
| Domain unit | `tests/domain` | parser edge cases, planner validation, budgeter, workflow transitions |
| Adapter contract | `tests/adapters` | codegraph command lines and schema-tolerant parsing via an injected exec fn |
| Use cases | `tests/app` | `Session` against real git and real pytest in temp dirs, with a fake index and clipboard |
| UI shells | `tests/ui` | CLI via `main(argv, factory)`, web via TestClient, TUI via the Textual pilot |
| End to end | `tests/e2e` | all five labs replayed with reference replies; the mock UI is rebuilt and its scenario run under node |

The tests were written first; several real defects were found this way (packet self-apply in watch mode, stale `.pyc`
in fast edit loops, code-only retry blocked by strict TDD, missing audit evidence after a late check acceptance).
