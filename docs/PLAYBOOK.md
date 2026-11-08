# The chatop playbook

How to build software with a chat LLM when you can only copy and paste: no coding harness, macOS/Linux,
and codegraph as the only code search. The interactive version is in [`chatop-playbook.html`](chatop-playbook.html).

---

## 1. The constraint, and what "optimal" means here

The chat model cannot see your disk, run commands, or remember the previous chat. Everything crosses the gap through
your clipboard. So the unit of cost is the **turn**: one copy *to* the chat and one copy *back*, plus the human
attention spent in between. Optimal therefore means:

1. **Few turns per unit of verified progress.** One turn should finish a whole slice (tests + code + docs), not one file.
2. **Near-zero thinking per turn**: the human should not have to decide what context to include, or how to apply
   what came back.
3. **No wasted turns.** No "can you show me X?", no hand-merging, no re-explaining after a new chat, no unverified code.
4. **Human attention only where it pays**: decisions (answers), approvals (PRD/SPEC/PLAN/AUDIT), and command safety.

## 2. Sixteen techniques that make each turn count

| # | Technique | What it saves | Where it lives |
|---|---|---|---|
| T1 | **Self-contained packets.** Role, rules, phase task, reply contract, state digest, decisions, docs, code, evidence | re-explaining; it works in a fresh chat | `Session.build_packet` |
| T2 | **Repo-as-memory.** `.chatop/state.json` plus `docs/*.md` are the only memory | context rot in long chats | `Workspace` |
| T3 | **One machine-applicable reply envelope** (`<<<CHATOP turn=N>>>` … `<<<END>>>`) | hand-applying code; mismatched pastes | `domain/reply.py` |
| T4 | **Pre-loaded context.** Each slice declares `touches`; codegraph resolves files and symbols, callers, and affected tests up front | "please paste file X" turns | `_slice_context` |
| T5 | **Batched requests.** All `@@need` and `@@ask` in one reply, all served in the next packet | serial Q&A | `_resolve_needs`, questions |
| T6 | **Multiple choice with recommended options pre-checked**, plus free-text other; `accept` takes them all | human deliberation time | `@@ask`, `chatop accept` |
| T7 | **Two-stage apply = TDD in one turn.** Tests are applied alone and must fail; then the code is applied and all checks must pass | a separate red turn; unverified "it works" | `Session.apply` |
| T8 | **Evidence loop.** Failing output (tail) goes into the next packet automatically | copying logs by hand | `_format_checks` |
| T9 | **Atomic, validated apply with repair prompts.** Nothing changes on any error; a precise fix-up prompt goes to the clipboard | broken half-applied states; vague retries | `plan_changes`, `_reject` |
| T10 | **Clipboard ping-pong** (`chatop watch`): replies are detected, applied, and the next packet is copied automatically | terminal interaction per turn | `watch_tick` |

| T11 | **More per turn.** A slice is sized for one reply and ships its *complete* test suite (every AC, edge cases, error paths), not a first sample | extra "now add the other tests" turns | `prompts/slice.md`, `plan.md` |
| T12 | **Issues, not a queue.** The plan's slices carry `depends` and `touches`. The scheduler hands every unblocked, non-overlapping issue to a chat, up to `max_parallel` | idle time: you wait on one chat while others could work | `domain/scheduler.py`, `Session.dispatch` |
| T13 | **Delta packets.** A new chat gets the full bootstrap packet. A continuing chat gets only what changed since its last turn, plus a line naming what it already holds (content digests per document and file) | tokens and reading time on every later turn | `domain/delta.py`, `LaneEngine._sections` |
| T14 | **Paste anything, anywhere.** Every reply header names its chat (`<<<CHATOP chat=c2 turn=3>>>`). chatop routes a pasted reply to the right chat, in any order, and applies it in the background | deciding which chat a reply belongs to; waiting for the slowest chat | `LaneEngine.route` |
| T15 | **One-shot preflight.** Every generated file is syntax-checked together (Python `ast`, JSON, TOML built in; ruff/tsc/gofmt per glob in `[preflight]`, run once). All problems, plus SEARCH mismatches, come back in ONE repair prompt | one typo = one round trip, per file | `domain/preflight.py`, `Session._stage` |
| T16 | **Isolated lanes and "ready" events.** A chat's failing code is held in its own overlay, never in the shared tree, so it cannot break another chat's checks. When a chat's next packet is ready the UI says so | cross-chat breakage; polling the terminal | `LaneEngine._apply_checked`, `board()` events |

Result: in steady state a slice costs **one turn and two clipboard actions**, and with `max_parallel = 3` three of
them overlap. Lab 1 goes from a vague idea to three committed, tested, type-checked slices in 8 LLM turns; Lab 5
runs two of the slices in parallel chats, including a typo rejection and a failing chat that never blocks the other.

## 3. The kit

```
chatop (Python app: CLI + TUI + web)        codegraph CLI (code search)        your chat LLM (Claude/ChatGPT/Gemini)
.chatop/  config.toml  state.json  journal.jsonl  packets/  replies/  undo/
docs/     IDEA  REFINEMENT  PRD  SPEC  PLAN  FEATURE  AS-BUILT  AUDIT  adr/
prompts   system · contract · idea · refine · prd · spec · plan · slice · feature · delta · recon · audit
```

* **Packets** = `system.md` + the phase prompt + `contract.md` + state + human input + evidence + docs + code context +
  repo map, assembled under a token budget (default 80K tokens; all target models have ≥250K, which leaves room for
  the reply and a few turns of chat history).
* **Replies**: one envelope. Directives: `@@test @@file @@doc @@edit @@delete @@ask @@slices @@need @@decision
  @@check @@run @@advance @@summary`.
* **Memory**: state, decisions, slices, history and evidence live in `.chatop/state.json` (commit it). Packets,
  replies and undo data are git-ignored.

## 4. Setup (once per machine)

```bash
npm i -g @colbymchenry/codegraph
pip install -e '.[dev]'           # from a clone of chat-op-devkit
chatop doctor                     # python, codegraph, git, clipboard backend, checks
```

Clipboard backends: pbcopy/pbpaste (macOS), wl-clipboard (Wayland), xclip or xsel (X11). Headless:
`CHATOP_CLIPBOARD=file`, which writes packets to `.chatop/outbox.md` and reads replies from `.chatop/inbox.md`.

## 5. Choosing the track

```
Is there code?
├─ no ─────────────────────────────────────────► chatop init --track new --idea "…"
└─ yes ─ Is .chatop/ present? ─ yes ───────────► chatop feature "…"            (continue)
          └─ no ─ Tests exist and a test command is detected? ─ yes ─► adopt
                                                               └─ no ──► audit (default; safest)
```

`chatop init` without `--track` applies exactly this rule. Override it when you know better. A project with passing
tests but known rot should still be **audited**.

## 6. Use case A: new project (track `new`)

| Step | Who | Action | Output | Gate |
|---|---|---|---|---|
| 1 | Human | `chatop init --track new --idea "…"` (or edit `docs/IDEA.md`) | state, config | |
| 2 | LLM | IDEA: restate, scope, assumptions, ≤6 decision questions | `docs/REFINEMENT.md`, `@@ask` | |
| 3 | Human | `chatop accept`, or answer with free text | answers | |
| 4 | LLM | REFINE ⟲ (≤3 rounds): fold answers in, ask more or `@@advance` | final brief, decisions | |
| 5 | LLM | PRD: US/AC with IDs, Given/When/Then, all testable | `docs/PRD.md` | **approve** |
| 6 | LLM | SPEC: boundaries with typed interfaces, ports and adapters, test strategy, ADRs, `@@check`s | `docs/SPEC.md`, `docs/adr/` | **approve** (accepts the checks) |
| 7 | LLM | PLAN: S0 walking skeleton, then vertical slices sized for one reply, with `touches` | `docs/PLAN.md`, slices | **approve** |
| 8 | LLM | SLICE ⟲: tests → code → docs in one reply. chatop proves red, runs checks, commits | commits | automatic |
| 9 | | DONE → `chatop feature "…"` | | |

**Gate checklists**
* PRD: Is every AC testable? Is anything missing from Must? Are the non-goals explicit? Are NFRs measurable?
* SPEC: Is each external system behind one interface? Does the import rule keep changes local? Are the check
  commands safe to run on your machine?
* PLAN: Does each slice fit one reply (≤5 files, ≤300 lines)? Is the riskiest work early? Is every AC covered?
  Are the `touches` precise?

## 7. Use case B: continue (track `continue`)

`chatop feature "…"` → FEATURE (impact analysis with `@@need impact/callers`, questions) → REFINE ⟲ → DELTA
(PRD/SPEC edits, ADRs, compatibility) **approve** → PLAN (new non-colliding slice IDs) **approve** → SLICE ⟲.
The packet always carries the existing slices, decisions, AS-BUILT/SPEC and the repo map, so the LLM extends the
system instead of reinventing it.

## 8. Use case C: an unknown project built by other agents (track `adopt`)

Goal: make the implicit explicit before touching anything.
1. `chatop init` runs local recon without the LLM: inventory, languages, manifests, detected checks, git history
   with **agent fingerprints** (Co-Authored-By: Claude, aider, Cursor, Copilot, Codex, Devin, …), churn × size
   hotspots, agent instruction files (CLAUDE.md, AGENTS.md, .cursorrules, copilot-instructions, …), and the
   codegraph repo map.
2. RECON turn: the LLM writes `docs/AS-BUILT.md` (architecture *as it is*, conventions, docs↔code gaps, whether the
   agent instructions are actually followed), proposes checks, and may `@@need` entry points. chatop stays in
   RECON one more turn to serve them.
3. Review AS-BUILT and the proposed checks (`chatop checks --accept`). Then `chatop feature "…"` (track B).

## 9. Use case D: an unknown project of unknown quality (track `audit`)

1. RECON as in C.
2. AUDIT turn: chatop runs the checks fresh and includes the results. The LLM writes `docs/AUDIT.md`: a traffic
   light per area, a **risk register** (severity, evidence, action), a test-gap map of the hotspots, and
   **agent-artifact smells** (hallucinated APIs, stubs that pretend to work, swallowed errors, duplicated logic,
   README claims the code doesn't support). **approve**
3. Stabilization PLAN: characterization slices first (tests that pin current behavior; they may pass immediately),
   then one fix slice per critical finding. **Never refactor untested code.**
4. SLICE ⟲, then normal feature work.

## 10. Parallel relay: several chats at once

Serial work leaves you idle while the model writes. With `max_parallel > 1` you keep several chat windows busy and
become a relay: copy a packet to the chat it names, move on, paste each reply when it arrives.

```
chatop init --parallel 3 --idea "…"      # or: chatop config --set max_parallel 3 (any time)
… PLAN approved → issues dispatched to chats (full packets) …
chatop board                              # chats, issues, events, tokens saved by deltas
```

**How an issue reaches a chat.** The approved plan becomes issues. `dispatch` picks, in plan order, every issue whose
`depends` are done and whose `touches` do not overlap a running issue, up to the free capacity. A free chat that
already holds the issue's files is reused (it receives a **delta** packet); otherwise a new chat is opened (it
receives a **full** packet). Chats that finished `max_issues_per_chat` issues are retired: long chats drift.

**The relay loop.**
1. The UI shows `N ready to send` and a big "Copy packet for c2 (delta)" button. Copy it, paste it in the browser tab
   you use for c2 (name your tabs `c1, c2, …`).
2. Do the same for every other ready chat. You never wait for one chat to finish before starting another.
3. When any reply arrives, copy it and paste it **anywhere** in chatop: the header says which chat it is. Replies
   from different chats may arrive in any order. In `watch` mode (or the web paste box) even this step is automatic.
4. chatop applies it in the background and reports: *ready* (next packet waiting), *done* (issue committed and
   dependents unblocked), *question* (that chat needs you), *blocked* (attempts exhausted: decide, then
   `chatop reset-chat c2`), *rejected* (a repair prompt is waiting on that chat's card).

**Why chats cannot break each other.** Each chat's uncommitted work lives in its own overlay
(`.chatop/lanes/cN.json`). When chatop applies a reply it materialises only that chat's overlay in the tree, runs the
checks, then either commits (green) or restores the tree (red). A failing chat's files are therefore never visible to
another chat's checks, and a green chat's commit never contains another chat's files. Applies are serialised; the
LLM wait is what runs in parallel. If two chats do edit the same file, the second apply is rejected with a conflict
message instead of overwriting the first.

**What goes in a delta packet.** The task for the chat's next issue (or "attempt 2" of the same issue), fresh
evidence from this chat's last run, answers to its questions, new decisions, and any document or file whose content
changed (including files other chats committed). Everything else is listed under *Already in your context*. Opening a
fresh browser tab? Press "Copy full" (or `chatop next c2 --full`): the next packet carries everything again.

**Clipboard policy.** chatop copies the next packet automatically only when no other chat is mid-flight. Otherwise
it leaves your clipboard alone (you may be holding a reply) and tells you which chat is next.

**Planning for parallelism.** The PLAN prompt asks for small independent slices, `depends` only for real
dependencies, and `touches` that are precise. chatop warns when a plan is wider than `max_parallel` and refuses
cyclic dependencies.

## 11. Chat hygiene

* Start a **fresh chat per phase**, or every ~5 slices, or whenever the model starts ignoring the contract. Packets
  are self-contained, so nothing is lost.
* Use the strongest model for SPEC, AUDIT and hard slices. A faster model is fine for REFINE and small slices.
* If a reply is cut off (`missing <<<END>>>`), type "continue the CHATOP block from where you stopped" and paste
  the full concatenated reply, or ask it to re-emit fewer files.
* If the model wraps the block oddly, chatop scans for the markers anyway. Paste the whole message.

## 12. Failure modes and recovery

| Symptom | What chatop does | What you do |
|---|---|---|
| Malformed reply / SEARCH mismatch / protected path | rejects atomically; repair prompt on the clipboard | paste the repair prompt into the same chat |
| Stale paste (wrong turn) | rejects with the turn numbers | copy the right reply, or `chatop next` to re-copy the packet |
| Checks fail | evidence goes into the next packet; attempts++ | just continue (next packet already on the clipboard) |
| Slice stuck ≥3 attempts | n/a | `chatop reject` at the next gate, split the slice, or fix by hand and `chatop apply` a small reply |
| Applied something wrong | `chatop undo` restores files and state (uncommitted turns) | for committed slices: `git revert` |
| RED not proven | slice not completed | the LLM strengthens the tests, or justifies with `@@advance` (pure refactor/characterization) |
| Several generated files have typos | one rejection listing every file and line; nothing applied | one repair prompt, one round trip |
| Reply pasted without a header, several chats waiting | rejects, names the waiting chats | paste it again after adding `chat=cN`, or paste it while only one chat is waiting |
| Chat answered for a stale turn | rejects with both turn numbers | re-copy that chat's packet |
| Chat failed `max_attempts` times | chat and issue become *blocked*; others continue | decide, edit docs/tests if needed, `chatop reset-chat cN` |
| Two chats edited the same file | second apply is rejected, its stale edit is dropped | `@@need file …` then resend (the repair prompt says so) |
| Code changes outside chatop | the codegraph index syncs on every packet build and apply | nothing |

## 13. Safety model

* chatop runs **only** commands from `.chatop/config.toml` `[checks]`. The LLM can propose (`@@check`); a human
  accepts (`chatop checks --accept`, or implicitly at a gate after review).
* Writes are confined to the repo root. `.git`, `.chatop`, `.codegraph`, `.env*` and keys are protected (configurable).
* Every apply is atomic and journaled (`.chatop/journal.jsonl`) and is undoable until it is committed.
* The web UI binds to 127.0.0.1.

## 14. Manual mode (no app)

The prompts in `src/chatop/prompts/` work by hand. Paste `system.md`, the phase prompt and `contract.md`, plus your
docs and code, then apply the reply yourself. Use this only to understand the protocol: the app exists because
manual mode wastes most of the turn budget.
