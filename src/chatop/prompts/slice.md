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
