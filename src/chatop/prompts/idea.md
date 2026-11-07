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
