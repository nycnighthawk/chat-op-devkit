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
