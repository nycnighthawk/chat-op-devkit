````chatop
<<<CHATOP turn=@TURN@>>>
@@summary PRD v1
@@doc docs/PRD.md
# PRD: csv2md v1

## 1. Summary
A CLI that converts CSV to a GitHub-flavoured Markdown table.

## 2. Goals
- G1: a correct table for any well-formed CSV in under 100 ms for 10k rows.

## 3. Non-goals
Alignment, TSV, Excel and HTML.

## 4. Users
Developers and CI scripts.

## 5. User stories
- US-1 As a developer I convert a CSV file to a Markdown table.
  - AC-1.1 Given rows [[a,b],[1,2]] When converted Then the output is `| a | b |`, `| --- | --- |`, `| 1 | 2 |`.
  - AC-1.2 Given a cell containing `|` When converted Then it is escaped as `\|`.
  - AC-1.3 Given a short row When converted Then it is padded with empty cells.
- US-2 As a CI script I pipe CSV through stdin.
  - AC-2.1 Given no path argument When run Then csv2md reads stdin and prints the table.
  - AC-2.2 Given a path When run Then csv2md reads the file and prints the table.

## 6. Functional requirements
FR-1 conversion (US-1) · FR-2 CLI input handling (US-2)

## 7. Non-functional requirements
NFR-1 stdlib only · NFR-2 mypy --strict · NFR-3 macOS and Linux

## 8. Constraints
Python ≥3.11.

## 9. Release scope
All of the above is in the MVP.

## 10. Success metrics
Used in our own docs pipeline.

## 11. Open issues
None.
@@end
@@advance
<<<END>>>
````
