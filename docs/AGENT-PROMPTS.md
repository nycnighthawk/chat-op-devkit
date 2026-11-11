# Agent prompts

Copy-paste prompts for a coding agent or a chat. Attach `SPEC-BUNDLE.md`.

## Implement from the spec (new repository)

You want a coding agent (or a chat) to build the product from the documents.

```text
You are implementing the product described in the attached spec bundle (docs/SPEC-BUNDLE.md, or the files under docs/).

Read in this order: PRD.md (what and why; ids FR-n, NFR-n, UC-n), DESIGN.md (modules, traceability, extension), ARCHITECTURE.md
(layers and the import rule), BEHAVIOR.md (the externally visible contract: CLI, envelope, apply rules, status --json),
DECISIONS.md (why), UX.md (the relay model).

Rules
1. The requirement ids are the scope. Create a checklist of every FR and NFR with Must priority first.
2. Follow the layer rules exactly: domain is pure, adapters implement ports, shells call only the Session facade.
3. Test first. Name tests after the requirement ids they verify (for example test_fr22_batch_validation).
4. Put the id in each commit message (for example "FR-22: validate all generated files in one pass").
5. Where PRD, DESIGN and BEHAVIOR disagree, BEHAVIOR wins for observable behavior; list the conflict in docs/SPEC-NOTES.md.
6. Do not add features that are not a requirement. Record anything unclear as a question in docs/SPEC-NOTES.md and choose the
   simplest reading.
7. Finish with a conformance table: every FR/NFR, the module that implements it, the test that proves it, and its status.
```

## Incorporate into an existing product

You have a codebase and want this workflow, or one layer of it, inside it.

```text
You are integrating part of the product described in the attached spec bundle into an existing codebase.

Step 1. Read PRD.md sections 3 to 7 and DESIGN.md sections 3, 4 and 7. Do not write code yet.
Step 2. Inspect the existing codebase (use its own search tools; do not guess). Produce docs/INTEGRATION-PLAN.md containing:
  a. Which adoption level (A protocol, B kernel, C library, D whole app) fits, and why, in five lines.
  b. The requirement ids in scope and the ids explicitly out of scope.
  c. For each in-scope module in DESIGN.md section 3: the existing code it replaces, wraps or sits beside.
  d. The seams: which of the four ports map to existing abstractions, and which need a new adapter.
  e. The integration contract items from DESIGN.md section 7 that the existing product must preserve or adopt.
  f. A sequence of small, independently shippable steps, each with its tests and its rollback.
  g. Risks and open questions.
Step 3. Stop and wait for approval of the plan before any implementation.
Step 4. Implement one step at a time, tests first, ids in commit messages. Keep domain code free of I/O and keep the existing
product's behavior unchanged unless a step says otherwise.
```

## Audit an implementation against the PRD

A rebuild or integration exists and you want evidence of conformance, not a claim.

```text
Audit the implementation in this repository against the spec bundle (PRD.md, DESIGN.md, BEHAVIOR.md).

For every FR and NFR in PRD.md produce one row: id | status (met, partial, missing, not applicable) | evidence (file and symbol,
and the test that proves it) | gap and smallest fix. Use the code search tool of the repository; cite paths and symbols, not memory.

Then list: (1) behavior in the code that no requirement asks for, (2) layer-rule violations against ARCHITECTURE.md, (3) places
where BEHAVIOR.md and the code differ in observable behavior. Do not change code. Output a markdown table and a prioritized fix list.
```
