````chatop
<<<CHATOP turn=@TURN@>>>
@@summary 4 issues: S1 and S2 are independent and can run in two chats at once
@@doc docs/PLAN.md
# Plan
| id | title | ACs | depends | touches |
|---|---|---|---|---|
| S0 | Walking skeleton | n/a | n/a | pyproject, package |
| S1 | Converter core | AC-1.1, AC-1.2, AC-1.3 | S0 | convert.py |
| S2 | Numeric column detection | AC-3.1 | S0 | align.py |
| S3 | CLI with --align | AC-2.1, AC-2.2, AC-3.2 | S1, S2 | cli.py, convert.py, align.py |

S1 and S2 touch different files and do not depend on each other: two chats work them at the same time.
@@end
@@slices
[
 {"id":"S0","title":"Walking skeleton","goal":"package importable, checks green","acceptance":[],"touches":["pyproject.toml","src/csv2md/__init__.py"]},
 {"id":"S1","title":"Converter core","goal":"to_markdown()","acceptance":["AC-1.1","AC-1.2","AC-1.3"],"touches":["src/csv2md/convert.py"],"depends":["S0"]},
 {"id":"S2","title":"Numeric columns","goal":"numeric_columns()","acceptance":["AC-3.1"],"touches":["src/csv2md/align.py"],"depends":["S0"]},
 {"id":"S3","title":"CLI with --align","goal":"csv2md [--align] file|stdin","acceptance":["AC-2.1","AC-2.2","AC-3.2"],"touches":["src/csv2md/cli.py","src/csv2md/convert.py","src/csv2md/align.py"],"depends":["S1","S2"]}
]
@@end
@@advance
<<<END>>>
````
