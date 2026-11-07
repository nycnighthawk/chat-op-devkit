````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Feature brief for --align; no blocking questions
@@doc docs/FEATURE.md
# Feature: column alignment

## Restatement
Add `--align left|center|right` to the CLI. It sets the GFM alignment marker of every column. The default stays
`---` (unchanged output).

## New user story
- US-3 As a developer I choose the column alignment.
  - AC-3.1 Given align=right When converted Then the separator cells are `---:`.
  - AC-3.2 Given align=center Then they are `:---:`; Given no option Then the output is unchanged (`---`).
  - AC-3.3 Given `--align center` on the CLI Then the printed table uses `:---:`.

## Impact
`convert.to_markdown` gains an `align: str = "left"` parameter (backward compatible). `cli.main` parses `--align`.

## Risks
None significant.
@@end
@@decision Alignment applies to all columns (per-column alignment is out of scope)
<<<END>>>
````
