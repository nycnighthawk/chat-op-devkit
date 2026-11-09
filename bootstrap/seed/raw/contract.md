Your reply MUST contain exactly this envelope (copy the first line verbatim):

````chatop
$header
@@summary <one line: what this reply does>
...directives...
<<<END>>>
````

| Directive | Meaning |
|---|---|
| `@@test <path>` … `@@end` | create/overwrite a **test** file. Applied and run *before* code (TDD red step) |
| `@@file <path>` … `@@end` | create/overwrite a whole file |
| `@@doc <path>` … `@@end` | create/overwrite a document (under `docs/`) |
| `@@edit <path>` … `@@end` | one or more SEARCH/REPLACE blocks (see below) |
| `@@delete <path>` | delete a file |
| `@@ask <id> [single]` … `@@end` | a question for the human: text, then `- [x] recommended` / `- [ ] option` lines. The human can always add free text |
| `@@slices` JSON `@@end` | slice plan (PLAN phase) |
| `@@need <symbol\|file\|callers\|callees\|impact\|affected> <target>` | context you need; it is resolved by the code graph into the next packet |
| `@@decision <text>` | a durable decision, kept in project state |
| `@@check <name> <command>` | propose a check command (e.g. `@@check test python -m pytest -q`); the human must accept it |
| `@@run <check>` | run a configured check after applying. Configured: $checks |
| `@@advance` | the exit criteria of this phase are met |

SEARCH/REPLACE syntax (SEARCH must match the current file exactly once; copy it verbatim from this packet):

```
@@edit src/pkg/module.py
<<<<<<< SEARCH
existing lines
=======
new lines
>>>>>>> REPLACE
@@end
```

The first line of your block must be the header exactly as shown above (it names the chat window, so chatop
can route your reply even when the human pastes several replies out of order).

Rules: paths are relative to the repo root. Never write to: $protected. File content is literal
(no line numbers, no extra indentation). Use `@@edit` for large files you have seen and `@@file`
for new or small files. If you are near your output limit, finish fewer files cleanly and still end
with `<<<END>>>`. A cut-off reply is rejected.
