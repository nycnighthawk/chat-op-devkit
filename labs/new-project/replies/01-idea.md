Here is the refinement draft and the decisions I need from you.

````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Refined the csv2md idea; 3 blocking decisions
@@doc docs/REFINEMENT.md
# Refinement: csv2md

## Problem statement
Developers paste tabular data into READMEs and docs by hand. Converting CSV to a Markdown table is tedious and
error-prone (escaping pipes, aligning columns).

## Users and jobs-to-be-done
- Developer writing docs: "turn this CSV into a table I can paste into a README".
- CI script: "regenerate the table in docs when data changes".

## Value proposition
One command, correct escaping, stable output (diff-friendly).

## Scope candidates
- Must: read a CSV file or stdin; write a GitHub-flavoured Markdown table to stdout; escape `|`.
- Should: header-row handling; column alignment option.
- Could: TSV input; width limits.
- Won't (v1): Excel input, HTML output.

## Assumptions
- A1 Python 3.11+, stdlib only (csv module).
- A2 The first row is the header.

## Open questions
See the @@ask items.

## Risks
- Ragged rows (inconsistent column counts) in real-world CSVs.
@@end
@@ask q1 single
Distribution format?
- [x] Python package with console script (pip install)
- [ ] Single-file script
@@end
@@ask q2 single
How should ragged rows be handled?
- [x] Pad short rows with empty cells
- [ ] Fail with an error
@@end
@@ask q3
Which extras are in v1?
- [x] Read from stdin when no file is given
- [ ] Column alignment flag
- [ ] TSV support
@@end
@@decision Output is GitHub-flavoured Markdown; '|' in cells is escaped as '\|'
<<<END>>>
````
