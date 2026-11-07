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
