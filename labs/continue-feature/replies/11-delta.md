````chatop
<<<CHATOP turn=@TURN@>>>
@@summary PRD/SPEC delta for alignment
@@edit docs/PRD.md
<<<<<<< SEARCH
## 6. Functional requirements
=======
- US-3 As a developer I choose the column alignment (AC-3.1..3.3, see docs/FEATURE.md).

## 6. Functional requirements
>>>>>>> REPLACE
@@end
@@edit docs/SPEC.md
<<<<<<< SEARCH
- `csv2md.convert` (pure core): `to_markdown(rows: list[list[str]]) -> str`
=======
- `csv2md.convert` (pure core): `to_markdown(rows: list[list[str]], align: str = "left") -> str`
>>>>>>> REPLACE
@@end
@@edit docs/FEATURE.md
<<<<<<< SEARCH
## Risks
=======
## Spec delta
- `to_markdown` gets an optional `align` parameter (default keeps the old output). CLI flag `--align`.
- No migration is needed.

## Risks
>>>>>>> REPLACE
@@end
@@advance
<<<END>>>
````
