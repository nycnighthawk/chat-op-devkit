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
