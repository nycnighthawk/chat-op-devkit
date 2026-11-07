````chatop
<<<CHATOP turn=@TURN@>>>
@@summary 3 slices: skeleton, converter, CLI
@@doc docs/PLAN.md
# Plan
| id | title | ACs | depends |
|---|---|---|---|
| S0 | Walking skeleton | n/a | n/a |
| S1 | Converter core | AC-1.1, AC-1.2, AC-1.3 | S0 |
| S2 | CLI file/stdin | AC-2.1, AC-2.2 | S1 |

Risk: ragged rows. Covered in S1.
@@end
@@slices
[
 {"id":"S0","title":"Walking skeleton","goal":"package importable, checks green","acceptance":[],"touches":["pyproject.toml","src/csv2md/__init__.py"]},
 {"id":"S1","title":"Converter core","goal":"to_markdown()","acceptance":["AC-1.1","AC-1.2","AC-1.3"],"touches":["src/csv2md/convert.py"]},
 {"id":"S2","title":"CLI","goal":"csv2md file|stdin","acceptance":["AC-2.1","AC-2.2"],"touches":["src/csv2md/cli.py","to_markdown"]}
]
@@end
@@advance
<<<END>>>
````
