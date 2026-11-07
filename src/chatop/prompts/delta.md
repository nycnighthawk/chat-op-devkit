### Phase DELTA: update the specification for the feature

1. Update `docs/PRD.md` (new or changed US/AC) and `docs/SPEC.md` (interfaces, data model, boundaries). Prefer `@@edit`.
   If they do not exist yet (adopted project), create them scoped to this feature, with a short *Existing system*
   section drawn from `docs/AS-BUILT.md`.
2. Add an ADR for every architectural decision.
3. State the backward-compatibility, migration and rollout impacts explicitly.
4. Append a *Spec delta* section to `docs/FEATURE.md`.

Then `@@advance`. The human approves.
