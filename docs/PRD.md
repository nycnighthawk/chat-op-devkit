# PRD: chatop

| | |
|---|---|
| Document | Product requirements, v0.1 |
| Status | Implemented in the reference repo; this document is the spec for rebuilding it or porting it into another product |
| Companion docs | `DESIGN.md` (modules, traceability, integration), `ARCHITECTURE.md` (layers, flows, state machine), `BEHAVIOR.md` (externally visible contract), `DECISIONS.md` (ADRs), `UX.md` (relay UX) |
| IDs | `P-n` persona, `UC-n` use case, `FR-n` functional, `NFR-n` non-functional, `R-n` risk. IDs are stable; never renumber, only append |

## 1. Summary

**chatop** is a local tool that lets a person build and maintain software with chat LLMs (Claude, ChatGPT, Gemini and
similar) that have no access to the repository. It owns project state, builds the exact text to paste into a chat
(a **packet**), and applies the chat's structured answer (a **reply**) to the repo with checks. The human's work per
turn is two actions: copy the packet to the chat, copy the reply back.

## 2. Problem

Using a chat window as a developer is limited by everything around the model, not by the model:

1. **Context gathering is manual and lossy.** The human assembles files, errors and history by hand, every turn.
2. **Applying output is manual and error-prone.** Code arrives as prose and fragments; edits are applied by hand and
   syntax errors are found one file at a time, one turn at a time.
3. **Nothing enforces engineering discipline.** "Tests first" is on the honour system; replies are trusted, not checked.
4. **State is lost between turns and between chats.** Several chats cannot work in parallel without the human
   becoming the scheduler and the merge tool.
5. **Unknown codebases are hard to enter.** Code written by other agents, of unknown quality, has no map, no tests
   and no stated intent.

## 3. Users

| ID | Persona | Situation | Needs most |
|---|---|---|---|
| P-1 | Solo builder | Has an idea and only chat access (or prefers it) | Idea to shipped slices with minimal turns; discipline enforced for them |
| P-2 | Engineer on an existing product | Adds features to a repo; may use several chats at once | Parallel work that does not collide; small packets; safe application |
| P-3 | Maintainer of an unknown codebase | Inherits code written by coding agents of unknown kind and quality | A map, an evidence-based assessment, and a safe path to change it |
| P-4 | Integrator | Wants this workflow inside another tool or process | Narrow, stable surfaces; a language-agnostic contract |

## 4. Goals and non-goals

**Goals**

* G-1 Minimise human effort and tokens per turn: one copy out, one copy back, optimised context.
* G-2 Make replies safe by construction: validated as a batch, applied atomically, tests proven red then green.
* G-3 Support four situations with one tool: new project, continue, adopt unknown code, audit unknown quality.
* G-4 Let the human run several chats in parallel and always show whose move it is.
* G-5 Keep the integration surface narrow so a change stays local.
* G-6 Be rebuildable through chat alone (the bootstrap plays) and able to adopt itself.

**Non-goals**

* NG-1 No coding agent, harness or autonomous loop. A human is always the relay.
* NG-2 No direct LLM API calls. Chat UIs are the interface.
* NG-3 No Windows support. macOS and Linux only.
* NG-4 No replacement for CI, code review or an issue tracker. chatop keeps its own small plan, not a project-management system.
* NG-5 No code search of its own. The `codegraph` CLI is the only code search used.

## 5. Constraints

| ID | Constraint |
|---|---|
| C-1 | macOS and Linux only |
| C-2 | Code search is the `codegraph` CLI (npm `@colbymchenry/codegraph`) and nothing else |
| C-3 | No coding harness may be invoked by chatop or by the process that builds it |
| C-4 | Python 3.11+, type annotations everywhere, `mypy --strict` and `ruff` clean |
| C-5 | TDD for chatop itself; the apply step enforces it for managed projects |
| C-6 | Chat context windows are at least 250K tokens; packets still have a budget |
| C-7 | Interfaces: CLI, web UI (FastAPI) and TUI (Textual), all over one core |

## 6. Use cases

| ID | Use case | Persona | Flow | Reference lab |
|---|---|---|---|---|
| UC-1 | New project | P-1 | idea, refine, PRD, SPEC, plan, slices, done | `new-project` |
| UC-2 | Continue: add a feature | P-1, P-2 | feature, refine, delta, plan, slices, done | `continue-feature` |
| UC-3 | Adopt an unknown project | P-3 | recon (map, churn, tests, agent markers), then work as UC-2 | `adopt` |
| UC-4 | Audit unknown quality | P-3 | recon, audit (findings, characterization tests), plan, slices | `audit` |
| UC-5 | Parallel relay | P-2 | plan becomes issues, issues go to chats, replies routed by chat id | `parallel-relay` |
| UC-6 | Manual mode | P-1 | the same protocol with copy/paste prompts and no app (the playbook) | n/a |
| UC-7 | Rebuild or integrate | P-4 | rebuild from the plays, or take one layer into another product | `bootstrap/accept.py` |

## 7. Functional requirements

Priority: **M** must, **S** should, **C** could. "Verified by" names the lab (`accept.py` replays them through the CLI)
or the kind of test.

### 7.1 Workflow and state

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-1 | Provide tracks `new`, `continue`, `adopt`, `audit`, each a fixed sequence of phases | M | 1-4 | labs 1-4 |
| FR-2 | `init` detects the track (empty or no code: new; code with tests: adopt) and accepts an explicit track | M | 1,3 | labs 1,3; unit |
| FR-3 | Gated phases (PRD, SPEC, delta, plan, audit by default) wait for explicit human approval; rejection returns the phase with the human's note | M | 1-4 | labs 1,2,4 |
| FR-4 | Refinement is bounded (rounds and questions per round) and questions carry recommended options the human can accept in one action | M | 1,2 | labs 1,2 |
| FR-5 | The plan is structured data: slices with id, goal, depends, touches, tests, acceptance; invalid plans (unknown dependency, cycle, duplicate id) are rejected with all problems listed | M | 1,2 | unit |
| FR-6 | `feature` starts the continue track on a finished project and refuses mid-phase unless forced | M | 2 | lab 2 |
| FR-7 | All state is on disk (`state.json`, append-only journal) so any session or shell can resume | M | all | unit; labs |

### 7.2 Packets (chatop to chat)

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-10 | Build one self-contained packet per turn: contract, phase prompt, project memory, relevant code (from codegraph), evidence of the last failure, and the exact first line the reply must start with | M | all | labs; unit |
| FR-11 | Respect a token budget; drop the lowest-priority context first and say what was dropped | M | all | unit |
| FR-12 | Copy the packet to the system clipboard; fall back to a file; a pasted packet is never accepted as a reply | M | all | unit |
| FR-13 | Continuing chats receive a delta packet (only changed context); new chats receive a full packet | M | 5 | lab 5 |
| FR-14 | Save every packet and reply for audit | S | all | unit |

### 7.3 Replies and apply (chat to chatop)

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-20 | Parse a line-oriented envelope: header with chat and turn, directives for summary, files, tests, docs, edits, deletes, questions, slices, needs, decisions, checks, runs, advance, and a terminator | M | all | unit; labs |
| FR-21 | Reject truncated replies (no terminator) and pasted packets | M | all | unit |
| FR-22 | Validate the whole reply as a batch before writing anything: path safety, edit matching, and syntax of every generated Python, JSON and TOML file; report all problems at once with one repair prompt | M | all | unit; labs |
| FR-23 | Apply atomically: a rejected reply changes nothing | M | all | unit; labs |
| FR-24 | Edits are SEARCH/REPLACE blocks that must match exactly once, with a whitespace-tolerant fallback | M | all | unit |
| FR-25 | Reject a reply whose turn or chat does not match the packet it answers (stale) | M | all | unit; lab 5 |
| FR-26 | On success commit automatically with the reply's summary and prepare the next packet | S | all | labs |
| FR-27 | Undo the last applied, uncommitted reply | S | all | unit |
| FR-28 | The LLM may request more context (`need`: symbol, file, callers, callees, impact, affected) and the next packet satisfies it through codegraph | S | 2,3 | unit |

### 7.4 TDD and checks

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-30 | In slice work, tests are applied first and must fail with the code held back (red proof); then the code is applied and the checks must pass (green) | M | 1,2,5 | labs 1,2,5 |
| FR-31 | A code-only retry is allowed after a failing attempt of the same slice; the audit track and an explicit advance relax red proof for characterization or refactoring | M | 4 | lab 4 |
| FR-32 | Checks are commands owned by the human; the LLM may only propose checks, and a proposal is never executed until accepted | M | all | unit |
| FR-33 | A slice that fails checks keeps its files in place and returns the evidence in the next packet; after a bounded number of attempts it blocks for a human decision | M | all | unit |

### 7.5 Parallel relay

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-40 | Turn the approved plan into issues; an issue is ready when its dependencies are done | M | 5 | lab 5 |
| FR-41 | Never run two issues at once whose `touches` overlap; an issue with unknown touches overlaps everything | M | 5 | unit; lab 5 |
| FR-42 | Assign ready issues to chats: reuse a chat that already holds related files up to a limit, otherwise open a new one; the human can override | M | 5 | lab 5 |
| FR-43 | Route a pasted reply to its chat by the header, in any order, from any chat | M | 5 | lab 5 |
| FR-44 | Show for every chat whose move it is: your move, waiting for the LLM, applying, closed; let the human flag "packet pasted" | M | 5 | lab 5; UI tests |
| FR-45 | Publish a monotonic event sequence so UIs can refresh without polling everything | S | 5 | unit |

### 7.6 Unknown projects

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-50 | Recon builds evidence for an unknown repo from codegraph and git: structure map, entry points, change churn, test inventory and failing tests, and markers of which agents wrote it | M | 3,4 | labs 3,4 |
| FR-51 | Adopt ends with a recon document and configured checks, after which the project continues on the continue track | M | 3 | lab 3 |
| FR-52 | Audit produces findings with severity and characterization tests that pin current behaviour before any change | S | 4 | lab 4 |

### 7.7 Interfaces and safety

| ID | Requirement | Pri | UC | Verified by |
|---|---|---|---|---|
| FR-60 | A CLI exposes every operation, with `status --json`, a global project-root option and stable exit codes (0 ok, 1 rejected, 3 applied but checks failed) | M | all | labs (through `accept.py`) |
| FR-61 | A web UI (FastAPI) shows projects, the per-project board by stage, a paste box that routes automatically, and approve/reject; it contains no business logic | M | 5 | UI tests |
| FR-62 | A TUI (Textual) offers the same board and actions, keyboard first | S | 5 | UI tests |
| FR-63 | `watch` applies replies as they appear on the clipboard and copies the next packet | C | all | unit |
| FR-64 | `doctor` reports the environment (tools found, index state, clipboard adapter) | S | all | unit |
| FR-70 | Writes are confined to the project root; `.git`, chatop state, secrets and configured protected paths are never writable by a reply | M | all | unit |
| FR-71 | A command string coming from a reply is never executed; only configured checks run | M | all | unit |

## 8. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Runs on macOS and Linux with Python 3.11+, git, and codegraph; no network access of its own (web UI binds to localhost) |
| NFR-2 | Narrow integration surface: a pure domain core, five ports, one adapter per port, one use-case facade, thin shells. Layer import rules are enforced by `tests/test_layers.py` |
| NFR-3 | Every external dependency is injectable; the core is testable without git, a clipboard or codegraph |
| NFR-4 | `mypy --strict` and `ruff` clean; modules stay small and single-purpose (guideline: about 400 lines; the reference has two larger ones, `app/lanes.py` and `app/session.py`) |
| NFR-5 | Human actions per turn: two (copy out, copy in). Everything else is automatic or a one-key decision |
| NFR-6 | UX follows the relay model in `UX.md`: one primary action per screen, visible status, no hidden waiting |
| NFR-7 | Failure is evidence, not a dead end: every rejection says what, where, and how to repair, in one message |
| NFR-8 | The envelope and apply rules are language-agnostic and fully described in `BEHAVIOR.md` so another implementation can be conformant |

## 9. Success measures

These are **targets to measure**, not results; the reference repo has not been measured with real chats.

| Measure | Target | How to measure |
|---|---|---|
| Replies applied on the first attempt | 80% or more | journal: applied vs rejected per turn |
| Pastes per finished slice | 2 or fewer median | journal: turns per slice |
| Human actions per turn | 2 | by construction (NFR-5) |
| Time from idea to first green slice | one session | wall clock |
| Parallel speed-up with 3 chats | 2x or more on independent slices | wall clock vs serial |

## 10. Release scope

* **v0.1 (this PRD):** FR-1 to FR-71 above; five labs; the bootstrap plays and conformance oracle.
* **Later (not committed):** configurable token budget per chat; project memory export; journal viewer; more chat-UI
  quirks tolerated by the parser; keyboard shortcuts in the web board; richer audit reports; per-language preflight
  plugins.

## 11. Acceptance

The release is acceptable when all of these hold:

1. The test suite passes, `mypy --strict` and `ruff` are clean.
2. `accept.py all` passes the five labs through the CLI.
3. The kernel acceptance script passes 9 of 9.
4. The layer rules in `ARCHITECTURE.md` hold (`tests/test_layers.py` passes).

## 12. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R-1 | Chat UIs mangle fences or copy buttons | 4-backtick fence, tolerant parser, explicit repair prompts, failure guide |
| R-2 | Long replies are truncated | terminator required; replies split by slice; `@@edit` for follow-ups |
| R-3 | The LLM weakens tests to pass | red proof, human review of test diffs, human-owned checks |
| R-4 | codegraph output shape changes | one adapter, tolerant parsing, contract tests with injected exec |
| R-5 | Two chats edit the same file | `touches` exclusion, serialized apply, SEARCH must match once |
| R-6 | Context grows beyond the window | token budget, delta packets, memory in docs not in chat history |
| R-7 | A rebuilt implementation drifts from the original | conformance labs as oracle, `BEHAVIOR.md` as contract |

## 13. Open questions

* OQ-1 Which chat UIs need tolerance beyond the current parser (smart quotes, code-block rewriting)?
* OQ-2 Should the token budget be calibrated from observed rejections instead of a fixed estimate (4 characters per token)?
* OQ-3 Is a per-language preflight plugin interface worth its surface, or should non-Python projects rely on checks only?

## 14. Glossary

| Term | Meaning |
|---|---|
| Packet | The text chatop builds for the human to paste into a chat |
| Reply | The structured text a chat returns; parsed and applied by chatop |
| Envelope | The reply grammar: header, directives, terminator |
| Slice | The unit of work: tests plus code, one reply |
| Issue | A slice assigned to a chat, with dependencies and touched files |
| Delta | A packet carrying only what changed since the chat's last packet |
| Red proof | Evidence that new tests fail before the code is applied |
| Recon | Evidence gathering for an unknown project |
| Kernel | The standard-library bootstrap script that builds packets and applies replies before chatop exists |
