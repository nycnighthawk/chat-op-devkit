### Phase PLAN: vertical slices

1. `@@doc docs/PLAN.md`: milestones; a slice table (id, title, ACs, depends-on); risks and mitigations.
2. `@@slices` with a JSON array. Each item:
   `{"id":"S1","title":"…","goal":"…","acceptance":["AC-1.1"],"touches":["src/pkg/mod.py","SymbolName"]}`

Slice rules:
- Each slice is a thin end-to-end increment that can be finished in **one reply**: at most about 5 files and
  300 changed lines, tests first.
- Order by dependency, then by risk (test the riskiest assumption early).
- `touches` lists the files and symbol names chatop pre-loads into that slice's packet through the code graph.
  Be precise: this is how you get the right context without extra turns.
- Every AC is covered by at least one slice.
$track_notes

Then `@@advance`. The human approves the plan.
