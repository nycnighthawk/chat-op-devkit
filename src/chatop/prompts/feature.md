### Phase FEATURE: analyze a feature request against the existing system

The feature request is in *Human input*. The existing system is described by the docs and repo map below.

1. `@@doc docs/FEATURE.md`: restatement; new or changed user stories and ACs (continue the PRD's ID numbering);
   impacted modules and interfaces; data or migration impact; risks; open questions.
2. `@@need` for the code you must read to judge impact (`impact <symbol>` and `callers <symbol>` are cheap and precise).
3. Up to $max_questions `@@ask` blocking questions, with recommended options pre-checked.

This phase advances to REFINE automatically, once your context requests (if any) are satisfied.
