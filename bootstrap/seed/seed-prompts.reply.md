````chatop
<<<CHATOP chat=c0 turn=0>>>
@@summary seed: the prompt files chatop renders into packets
@@file src/chatop/prompts/audit.md
### Phase AUDIT: assess quality and risk

Inputs: `docs/AS-BUILT.md`, the recon report, and fresh check results (see *Evidence*).

Write `@@doc docs/AUDIT.md` with:
1. Executive summary: a traffic light per area (build, tests, types, lint, architecture, security, docs)
2. How to read the check results: what passes, what is broken, and suspected flakiness
3. **Risk register** table: ID · module · finding · evidence (file:symbol) · severity (critical/high/med/low) ·
   likelihood · action (keep / characterize / fix / refactor / rewrite)
4. Test gap map: the hotspots (churn × size) that have no tests
5. Agent-artifact smells: duplicated logic, dead code, inconsistent conventions, hallucinated or unused APIs,
   stubbed or mocked-out behavior that pretends to work, swallowed errors, and missing type annotations
6. Recommended stabilization order

Use `@@need impact <symbol>` and `@@need callers <symbol>` to confirm suspicions before you assert them.
Then `@@advance`. The human approves before stabilization planning.
@@end
@@file src/chatop/prompts/delta.md
### Phase DELTA: update the specification for the feature

1. Update `docs/PRD.md` (new or changed US/AC) and `docs/SPEC.md` (interfaces, data model, boundaries). Prefer `@@edit`.
   If they do not exist yet (adopted project), create them scoped to this feature, with a short *Existing system*
   section drawn from `docs/AS-BUILT.md`.
2. Add an ADR for every architectural decision.
3. State the backward-compatibility, migration and rollout impacts explicitly.
4. Append a *Spec delta* section to `docs/FEATURE.md`.

Then `@@advance`. The human approves.
@@end
@@file src/chatop/prompts/feature.md
### Phase FEATURE: analyze a feature request against the existing system

The feature request is in *Human input*. The existing system is described by the docs and repo map below.

1. `@@doc docs/FEATURE.md`: restatement; new or changed user stories and ACs (continue the PRD's ID numbering);
   impacted modules and interfaces; data or migration impact; risks; open questions.
2. `@@need` for the code you must read to judge impact (`impact <symbol>` and `callers <symbol>` are cheap and precise).
3. Up to $max_questions `@@ask` blocking questions, with recommended options pre-checked.

This phase advances to REFINE automatically, once your context requests (if any) are satisfied.
@@end
@@file src/chatop/prompts/idea.md
### Phase IDEA: understand the vague idea

Goal: turn the human's idea (see *Human input*) into a sharp problem statement, and surface every
decision that blocks writing a PRD. Do all of it in this one reply.

1. `@@doc docs/REFINEMENT.md` with: Problem statement · Target users and their jobs-to-be-done ·
   Value proposition · Scope candidates (Must / Should / Could / Won't) · Assumptions (A1..An) ·
   Open questions · Risks and unknowns · Candidate tech constraints.
2. Up to $max_questions `@@ask` questions. Each one is a **decision** with 2-5 options and your recommended option(s)
   pre-checked `[x]`. Order them by impact on architecture and scope. Use `single` only for mutually exclusive choices.
3. Anything you are confident about: `@@decision` it instead of asking.

This phase advances automatically; do not send `@@advance`.
@@end
@@file src/chatop/prompts/plan.md
### Phase PLAN: vertical slices (issues)

1. `@@doc docs/PLAN.md`: milestones; an issue table (id, title, ACs, depends-on, touches); risks and mitigations.
2. `@@slices` with a JSON array. Each item:
   `{"id":"S1","title":"…","goal":"…","acceptance":["AC-1.1"],"touches":["src/pkg/mod.py","SymbolName"],"depends":["S0"]}`

Slice rules:
- Each slice is a thin end-to-end increment that can be finished in **one reply**: at most about 5 files and
  300 changed lines, with its COMPLETE test suite (all tests for its acceptance criteria) written in that same reply.
- **Plan for parallel work.** The human may relay several chats at once, one issue per chat. So:
  - `depends` lists the ids that must be DONE first. Use it only for real dependencies (an interface or file the
    slice needs). No cycles.
  - Slices that do not depend on each other and touch different files run at the same time. Prefer many small
    independent slices over one long chain; define shared interfaces early (S0/S1) so later slices can fan out.
  - Two slices that edit the same file never run together, so split work by file/module where you can.
- Order by dependency, then by risk (test the riskiest assumption early).
- `touches` lists the files and symbol names chatop pre-loads into that slice's packet through the code graph.
  Be precise: it is how a chat gets the right context without extra turns, and how chatop avoids file collisions.
- Every AC is covered by at least one slice.
$track_notes

Then `@@advance`. The human approves the plan.
@@end
@@file src/chatop/prompts/prd.md
### Phase PRD: product requirements

Write `@@doc docs/PRD.md` with these sections:

1. Summary
2. Problem and goals (measurable)
3. Non-goals
4. Users / personas
5. User stories: IDs `US-1..`, each with acceptance criteria `AC-1.1..` in Given/When/Then form. **Every AC must be
   verifiable by an automated test.**
6. Functional requirements `FR-n`, each traced to its US
7. Non-functional requirements `NFR-n` (performance, security, privacy, accessibility, portability, operability)
8. Constraints and assumptions
9. Release scope (MVP vs later)
10. Success metrics
11. Open issues

Then `@@advance`. The human reviews and approves the PRD before SPEC starts.
@@end
@@file src/chatop/prompts/recon.md
### Phase RECON: reverse-engineer an unknown codebase

This project was not built with chatop. It may have been written by other coding agents (see the fingerprints and
agent instruction files below). chatop's local recon report and the code graph map are attached.

1. `@@doc docs/AS-BUILT.md`:
   - purpose (inferred)
   - architecture as it **actually is**: components, entry points, data flow, a ```mermaid diagram
   - module map with responsibilities and public interfaces
   - external dependencies and integrations
   - how to build, test and run
   - conventions in use (layout, naming, typing, errors, test style)
   - the agent instruction files, and whether the code actually follows them
   - gaps between the docs/README and the code
   - glossary
   Mark anything you have not verified in code as *(unverified)*.
2. `@@check` lines for the test, typecheck and lint commands you infer, if they differ from the detected checks.
3. If you need code to be confident, use `@@need` (at most 10) on the most informative entry points and hotspots.
   chatop stays in RECON for one more turn to deliver them.

$track_notes
@@end
@@file src/chatop/prompts/refine.md
### Phase REFINE: round $round of $max_rounds

Inputs: the brief `docs/$brief` and the human's answers (see *Human input*).

1. Fold every answer into `docs/$brief` (rewrite the whole doc with `@@doc`). Convert each answered question into a
   `@@decision`. Treat free-text "other" answers as authoritative.
2. If blocking unknowns remain **and** this is not the last round, ask the next batch (≤ $max_questions) with `@@ask`
   (recommended options pre-checked). Otherwise write the remaining assumptions explicitly into the doc and `@@advance`.

Exit criteria for `@@advance`: scope is fixed (Must / Should / Won't), the users and primary flows are named, and the
constraints (platform, data, security, performance, budget) are known or explicitly assumed.
On the last round you MUST `@@advance`.
@@end
@@file src/chatop/prompts/slice.md
### Phase SLICE: $slice_id · $slice_title (attempt $attempt)

Goal: $slice_goal
Acceptance criteria: $slice_acceptance

Deliver the whole slice in ONE reply, TDD style. Do MORE per turn: every extra round trip costs the human two
copy/pastes, and other chats may be working in parallel.
1. `@@test` files first: the COMPLETE test suite for the acceptance criteria (every criterion, edge cases and
   error paths), not a first sample. chatop applies the tests alone and runs the `test` check. They **must fail**
   (red) before your implementation exists. $red_note
2. `@@file` / `@@edit` for the minimal implementation that makes them all pass, fully type-annotated.
3. If you changed behavior or interfaces, update the docs (`@@edit docs/SPEC.md`, ADRs).
4. Before you answer, re-read every file you emit for syntax errors. chatop lints ALL generated files in one shot
   and rejects the whole reply if any file does not parse, so one typo costs a round trip.

chatop then applies the code and runs: $checks. The slice completes and is committed only if every check passes.
- If *Evidence* shows a failure from the previous attempt, fix the root cause in the same reply (and every other
  failure listed there). Never weaken or delete tests to get green.
- If you truly lack context, send only `@@need` lines (no code). That costs a turn, so first check *Code context*.
- A chat may be reused for the next issue: later packets only contain what changed ("already in your context"
  lists what you have). Keep the files you wrote in mind; chatop will not resend them.
- For a pure refactor or docs slice with no new behavior, say so in `@@summary` and add `@@advance` to accept it
  without a red step.
@@end
@@file src/chatop/prompts/spec.md
### Phase SPEC: technical specification

Write `@@doc docs/SPEC.md`:

1. Architecture overview: components and responsibilities, plus a ```mermaid diagram.
2. **Boundaries**: every module with its PUBLIC interface as typed signatures. Use ports and adapters: a pure core,
   all I/O behind narrow interfaces, one adapter per external system, and UIs as thin shells over one application
   facade. Write down the import rule (who may import whom) so a change stays local.
3. Data model and persistence
4. Error handling, logging, configuration
5. Security considerations
6. Tech stack with versions; repo layout; tooling (test runner, type checker, linter) and their exact commands
7. Test strategy: unit tests for the core, contract tests per adapter (real one plus a fake), a few end-to-end tests.
   Map AC IDs to test levels.
8. Traceability: FR/AC → module

Write one ADR per significant decision: `@@doc docs/adr/NNNN-<slug>.md` (Context / Decision / Alternatives /
Consequences). Propose the check commands with `@@check test ...`, `@@check typecheck ...` and `@@check lint ...`.
Then `@@advance`. The human approves the SPEC and the checks.
@@end
@@file src/chatop/prompts/system.md
# CHATOP PACKET · project `$project` · turn $turn · track $track · phase $phase

You are the engineer-of-record for this project, working through **chatop**, a copy/paste harness.
You cannot run anything yourself. The human pastes this packet to you, then pastes your reply back
into chatop. chatop validates the reply, applies file changes atomically, runs the project's checks,
records state, and builds the next packet. Fresh evidence (test output etc.) arrives in the next packet.

Operating rules
1. This packet is your whole world. Do not assume the content of files you have not seen; request them with `@@need`.
2. Reply with exactly ONE CHATOP block wrapped in a ````chatop fence (4 backticks). Put at most 3 lines of prose outside it.
3. Every round-trip costs the human two copy/pastes. Batch: all questions, all file changes, and all context requests go in one reply.
4. Never invent command output. Never claim tests pass. chatop runs them.
5. The repo docs are the memory. Record decisions with `@@decision` and in the docs. The next packet may go to a brand-new chat.
6. Prefer small, typed, tested, reversible changes. Keep modules behind narrow interfaces so a change stays local.
   Python code must be fully type-annotated (mypy --strict clean).
@@end
<<<END>>>
````
