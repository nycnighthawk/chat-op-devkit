````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Create PRD/SPEC scoped to the feature (adopted project had none)
@@doc docs/PRD.md
# PRD: agentic-todo
## Existing system
See docs/AS-BUILT.md.
## User stories
- US-1 Due dates (AC-1.1, AC-1.2 in docs/FEATURE.md)
@@end
@@doc docs/SPEC.md
# SPEC: agentic-todo
## Boundaries
- `todo.Todo(id: int, title: str, done: bool = False, due: str | None = None)`
- `todo.TodoStore.add(title: str, due: str | None = None) -> Todo`
- `todo.TodoStore.overdue(today: datetime.date) -> list[Todo]`
## Compatibility
JSON files without `due` still load.
@@end
@@advance
<<<END>>>
````
