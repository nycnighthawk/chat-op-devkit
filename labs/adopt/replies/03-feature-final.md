````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Feature brief final (ISO dates)
@@doc docs/FEATURE.md
# Feature: due dates

## Stories and ACs
- US-1 A todo may carry an optional due date.
  - AC-1.1 `add(title, due="2026-01-01")` stores the due date; it survives reload.
  - AC-1.2 `overdue(today)` returns the open todos whose due date is before `today`; done or undated todos are excluded.

## Impact
`Todo` gains `due: str | None = None`. The JSON stays backward compatible: old files have no `due`, which defaults to None.
`TodoStore.add` gets an optional `due`; there is a new `TodoStore.overdue(today: date)`.

## Risks
Old JSON files: covered by the default value.
@@end
@@decision Due dates are ISO strings YYYY-MM-DD (q1)
<<<END>>>
````
