````chatop
<<<CHATOP turn=@TURN@>>>
@@summary One slice
@@doc docs/PLAN.md
# Plan: due dates
| D1 | due dates + overdue() | AC-1.1, AC-1.2 |
@@end
@@slices
[{"id":"D1","title":"due dates + overdue()","acceptance":["AC-1.1","AC-1.2"],"touches":["todo.py","tests/test_todo.py"]}]
@@end
@@advance
<<<END>>>
````
