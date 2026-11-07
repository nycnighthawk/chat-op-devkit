### Phase PRD: product requirements

Write `@@doc docs/PRD.md` with these sections:

1. Summary
2. Problem and goals (measurable)
3. Non-goals
4. Users / personas
5. User stories: IDs `US-1..`, each with acceptance criteria `AC-1.1..` in Given/When/Then form. **Every AC must be
   verifiable by an automated test.**
6. Functional requirements `FR-n`, each traced to its US
7. Non-functional requirements `NFR-n` (performance, security, privacy, accessibility, portability, operability)
8. Constraints and assumptions
9. Release scope (MVP vs later)
10. Success metrics
11. Open issues

Then `@@advance`. The human reviews and approves the PRD before SPEC starts.
