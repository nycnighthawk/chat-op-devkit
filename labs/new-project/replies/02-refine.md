````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Folded the answers in; scope is fixed
@@doc docs/REFINEMENT.md
# Refinement: csv2md (final)

## Problem statement
Converting CSV to a Markdown table by hand is tedious and error-prone.

## Scope (fixed)
- Must: CSV file or stdin → GFM table on stdout; escape `|`; pad ragged rows.
- Should: none in v1.
- Won't (v1): alignment, TSV, Excel, HTML.

## Decisions
- Packaged as a Python package exposing a `csv2md` console script.
- Ragged rows are padded with empty cells.
- Reads stdin when no path is given.

## Constraints
Python ≥3.11, stdlib only, mypy --strict clean, pytest.
@@end
@@decision Package with console script csv2md (q1)
@@decision Pad ragged rows with empty cells (q2)
@@decision Read stdin when no file argument is given (q3)
@@advance
<<<END>>>
````
