````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Draft feature brief; I need todo.py and one decision
@@doc docs/FEATURE.md
# Feature: due dates (draft)
- US-1 A todo may have a due date; I can list overdue open todos.
@@end
@@need file todo.py
@@ask q1 single
How should due dates be stored?
- [x] ISO date string "YYYY-MM-DD" (keeps the JSON format human-readable)
- [ ] Unix timestamp
@@end
<<<END>>>
````
