### Phase SLICE: $slice_id · $slice_title (attempt $attempt)

Goal: $slice_goal
Acceptance criteria: $slice_acceptance

Deliver the whole slice in ONE reply, TDD style:
1. `@@test` files first: tests that encode the acceptance criteria. chatop applies the tests alone and runs the
   `test` check. They **must fail** (red) before your implementation exists. $red_note
2. `@@file` / `@@edit` for the minimal implementation that makes them pass, fully type-annotated.
3. If you changed behavior or interfaces, update the docs (`@@edit docs/SPEC.md`, ADRs).

chatop then applies the code and runs: $checks. The slice completes and is committed only if every check passes.
- If *Evidence* shows a failure from the previous attempt, fix the root cause. Never weaken or delete tests to get green.
- If you truly lack context, send only `@@need` lines (no code). That costs a turn, so first check *Code context*.
- For a pure refactor or docs slice with no new behavior, say so in `@@summary` and add `@@advance` to accept it
  without a red step.
