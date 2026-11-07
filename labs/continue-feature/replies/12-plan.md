````chatop
<<<CHATOP turn=@TURN@>>>
@@summary One slice for alignment
@@edit docs/PLAN.md
<<<<<<< SEARCH
Risk: ragged rows. Covered in S1.
=======
Risk: ragged rows. Covered in S1.

## Feature: alignment
| F1-S1 | --align core + CLI | AC-3.1..3.3 | S2 |
>>>>>>> REPLACE
@@end
@@slices
[{"id":"F1-S1","title":"--align core + CLI","goal":"alignment markers","acceptance":["AC-3.1","AC-3.2","AC-3.3"],
  "touches":["src/csv2md/convert.py","src/csv2md/cli.py"]}]
@@end
@@advance
<<<END>>>
````
