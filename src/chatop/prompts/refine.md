### Phase REFINE: round $round of $max_rounds

Inputs: the brief `docs/$brief` and the human's answers (see *Human input*).

1. Fold every answer into `docs/$brief` (rewrite the whole doc with `@@doc`). Convert each answered question into a
   `@@decision`. Treat free-text "other" answers as authoritative.
2. If blocking unknowns remain **and** this is not the last round, ask the next batch (≤ $max_questions) with `@@ask`
   (recommended options pre-checked). Otherwise write the remaining assumptions explicitly into the doc and `@@advance`.

Exit criteria for `@@advance`: scope is fixed (Must / Should / Won't), the users and primary flows are named, and the
constraints (platform, data, security, performance, budget) are known or explicitly assumed.
On the last round you MUST `@@advance`.
