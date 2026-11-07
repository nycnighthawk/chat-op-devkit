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
