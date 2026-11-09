"""The content of the bootstrap plays (data only). Rendered by scripts/build_bootstrap.py into one HTML file.

A play is a dict: id, title, where ("terminal" | "chat" | "terminal + chat" | "editor"), mode ("both" | "seeded" |
"purist"), do (steps; `code` spans allowed), cmds ([(label, code)] copy blocks), expect, check, ifnot, slice (optional).
"""

from __future__ import annotations

from typing import Any

Play = dict[str, Any]

CONTRACT_NOTE = "every chat gets the same envelope contract inside each packet, so a fresh tab needs no explanation"

BRIEF = """# Brief: chatop

A copy/paste tool for building software with chat LLMs that cannot see the repo. It keeps project state, builds the
exact text to paste into a chat (a packet), and applies the chat's structured reply to the repo with checks.

Hard constraints
- macOS and Linux only. Python 3.11+, type annotations everywhere, `mypy --strict` and `ruff` clean.
- Code search is the `codegraph` CLI (npm @colbymchenry/codegraph) only. No coding agent or harness is ever invoked.
- TDD: tests first and proven red, then code, then green. Several test files and all the code of a slice in one reply.
- Narrow integration surface: a pure domain core, five ports (CodeIndex, Clipboard, Runner, Vcs and the types they
  return), one adapter per port, a Session use-case layer, and thin shells (CLI, FastAPI web UI, Textual TUI).
- Workflows: new project (idea -> refine -> PRD -> SPEC -> plan -> slices), continue with features, adopt an unknown
  project (recon), audit an unknown-quality project.
- Parallel relay: several chats at once, issues assigned to chats, paste routes by chat id, delta packets for
  continuing chats, a board by stage (your move / waiting for the LLM / applying / closed) and an "I pasted it" flag.
- Every context window is at least 250K tokens.
"""

KERNEL_PROMPT = """You are writing ONE Python file, `bootstrap/relay.py`: a stage-0 "relay kernel". Standard library only,
Python 3.11+, macOS and Linux, type-annotated, `ruff` clean at line length 120. No coding agent will help; a human
copies text between you and a terminal.

What it does
- `relay.py pack S2 [--chat c2] [--evidence FILE] [--cg "callers apply"] [--read PATH] [--print]` builds a packet
  (the text a human pastes into a chat): the envelope contract, the `## S2` section of docs/PLAN.md (bullets
  `depends:`, `touches:`, `reads:`), the documents and files named in reads/touches, `git ls-files`, optional
  `codegraph` output and evidence, and a last line telling the chat the exact first line of its reply
  (`<<<CHATOP chat=c2 turn=N>>>`). `pack --task TEXT` packs a free task. Turn numbers increase per pack. The packet
  starts with `# CHATOP PACKET` and is copied to the clipboard (pbcopy, wl-copy, xclip or xsel), else `--print`.
- `relay.py apply [FILE|-]` (default: clipboard) applies a reply. Envelope: a 4-backtick `chatop` fence (optional),
  first line `<<<CHATOP chat=cN turn=N>>>`, last line `<<<END>>>`. Directives: `@@summary`, `@@file|@@test|@@doc
  PATH` ... `@@end`, `@@edit PATH` with `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` blocks ... `@@end`, `@@delete
  PATH`, `@@decision TEXT`.
- Rules: report ALL problems at once and change nothing on rejection (exit 1, with a repair prompt on the clipboard);
  reject truncated replies (no terminator), pasted packets, unsafe paths (absolute, `..`, `.git/`, `.relay/`,
  `.env*`), SEARCH text that matches zero or several times (a trailing-whitespace-tolerant fallback is fine);
  preflight every Python file with `ast`, `.json` and `.toml` before writing anything; reject a reply whose turn does
  not match the packet it answers. TDD: if a reply has tests and code, write the tests only, run them (they must
  FAIL: "red"), then write the code and run the whole test command (must pass); `RELAY_TEST` overrides the test
  command (default `<venv python> -m pytest -q`; exit 5 = no tests yet is fine), `RELAY_CHECKS` is a `;` separated
  list of more commands. If the checks fail, keep the files in place, print and copy the evidence, exit 3. On success
  `git add -A` and commit with the summary, exit 0. Docs-only replies skip tests. Set PYTHONDONTWRITEBYTECODE=1 for
  subprocesses (stale .pyc files break fast edit loops).
- `relay.py undo` reverts the last apply; `relay.py status` lists chats that owe a reply. State lives in a git-ignored
  `.relay/` folder.

Below is the acceptance script your file must pass (`python relay_acceptance.py bootstrap/relay.py` must print
"kernel OK: 9/9 checks passed"). Read it as the exact specification of the behavior above.

Reply with the complete file in ONE python code block and nothing else of substance.
"""

# --- the plays ------------------------------------------------------------------------------------------------

ACTS: list[dict[str, Any]] = [
    {
        "id": "act0",
        "title": "Act 0. Prepare the ground",
        "goal": "A git repo with the kit unpacked, a venv, codegraph installed and a tab plan. About 20 minutes, once.",
        "plays": [
            {
                "id": "0.1",
                "title": "Check the machine",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "You need macOS or Linux, `git`, `python3` 3.11 or newer, `node` 18 or newer and `npm`.",
                    "Install the code search tool: `npm i -g @colbymchenry/codegraph`. It is the only way code is "
                    "searched in this plan; the plays below call it for you.",
                    "Clipboard: macOS has `pbcopy`; on Linux install `wl-clipboard` (Wayland) or `xclip` (X11). Without "
                    "one the kernel can `--print` and you copy by hand.",
                ],
                "cmds": [
                    (
                        "versions",
                        "git --version && python3 --version && node --version && npm --version\n"
                        "codegraph --version || echo 'codegraph missing'\n"
                        "command -v pbcopy wl-copy xclip xsel",
                    )
                ],
                "expect": ["python 3.11+, node 18+, a codegraph version, and at least one clipboard tool listed."],
                "ifnot": [
                    "`codegraph` not found after install: `npm bin -g` is not on PATH; add it and open a new terminal.",
                    "No clipboard tool: continue, and add `--print` to every `pack`; select-and-copy from the terminal.",
                ],
            },
            {
                "id": "0.2",
                "title": "Create the repo from the kit",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "Download the kit with the button under Artifacts (`chatop-bootstrap-kit.zip`). It holds the "
                    "kernel, its acceptance script, the conformance runner `accept.py`, the seed replies, a skeleton "
                    "`pyproject.toml` and `.gitignore`. Nothing else exists yet: no app code.",
                    "Make the repo, unzip the kit into it, create the venv, install only the dev tools and commit.",
                ],
                "cmds": [
                    (
                        "repo",
                        "mkdir chatop && cd chatop && git init -q -b main\n"
                        "unzip -o ~/Downloads/chatop-bootstrap-kit.zip\n"
                        "mv gitignore .gitignore && mkdir -p src/chatop tests docs\n"
                        "python3 -m venv .venv && . .venv/bin/activate\n"
                        "pip install -q pytest pytest-asyncio httpx mypy ruff\n"
                        "source bootstrap/env.sh\n"
                        "git add -A && git commit -qm 'bootstrap: kit (kernel, conformance runner, seed)'",
                    )
                ],
                "expect": ["`relay ready: ...` from env.sh and a clean `git status`."],
                "check": "git status --short | wc -l   # 0",
                "ifnot": ["`git commit` complains about identity: `git config user.name` / `user.email`."],
            },
            {
                "id": "0.3",
                "title": "Plan your chat tabs",
                "where": "browser",
                "mode": "both",
                "do": [
                    "Use one chat per slice, named after it: slice S4 is chat `c4`, S7 is `c7`. The number in the "
                    "chat id is the slice number, so you never need a lookup table. Tab title: `c4 · S4 ports`.",
                    "Any chat UI works (Claude, ChatGPT, Gemini). Pick a model with a big context window; "
                    f"{CONTRACT_NOTE}.",
                    "Paste the packet as the first message of a fresh chat. Never type code or edit the reply by hand "
                    "except where a play tells you to.",
                    "A chat is reused only to repair its own slice (you paste the repair prompt or the evidence into "
                    "the same tab). A new slice always gets a new tab: no drift, and every packet is self-contained.",
                ],
                "expect": ["Eleven tab names ready (you open them when their wave starts)."],
            },
        ],
    },
    {
        "id": "act1",
        "title": "Act 1. Stage 0: a kernel you can trust",
        "goal": "One standard-library script that builds packets and applies replies safely, proven by 9 black-box checks.",
        "plays": [
            {
                "id": "1.1",
                "title": "Verify the kernel",
                "where": "terminal",
                "mode": "seeded",
                "do": [
                    "The kit already contains `bootstrap/relay.py`. You do not trust it, you test it: the acceptance "
                    "script drives it in throwaway git repos (red/green/commit, all problems at once, unsafe paths, "
                    "truncated replies, ambiguous edits, failing-then-fixed checks, docs-only commits, undo).",
                ],
                "cmds": [("verify", "python bootstrap/relay_acceptance.py bootstrap/relay.py")],
                "expect": ["The last line is `kernel OK: 9/9 checks passed`."],
                "ifnot": ["A failing check prints its name and the output: that is the whole bug report."],
            },
            {
                "id": "1.1p",
                "title": "Have a chat write the kernel (purist)",
                "where": "terminal + chat",
                "mode": "purist",
                "do": [
                    "Delete the kit's kernel: `rm bootstrap/relay.py`. Keep `relay_acceptance.py`.",
                    "Open a chat. Paste the kernel prompt, then paste the contents of `relay_acceptance.py` (copy "
                    "buttons under Artifacts). It answers with one python code block.",
                    "Save it as `bootstrap/relay.py` (the only file you ever save by hand) and run the acceptance script.",
                    "Failures: paste the script's output into the SAME chat and ask for a corrected full file. "
                    "Repeat until 9/9. Budget three to six turns.",
                ],
                "paste": ("kernel prompt", "KERNEL_PROMPT"),
                "cmds": [
                    (
                        "verify",
                        "python bootstrap/relay_acceptance.py bootstrap/relay.py && git add -A && git commit -qm 'bootstrap: relay kernel'",
                    )
                ],
                "expect": ["`kernel OK: 9/9 checks passed`."],
                "ifnot": [
                    "Still red after six turns: switch to the seeded path for this play only; the rest is unchanged."
                ],
            },
            {
                "id": "1.2",
                "title": "Shakedown: one real round trip",
                "where": "terminal + chat",
                "mode": "both",
                "do": [
                    "Prove that your chat and your clipboard obey the envelope before spending real turns. The task "
                    "is tiny on purpose: a test and one line of code.",
                    "Run `pack`; the packet is on your clipboard. Open a new chat, paste, wait for the reply, click the "
                    "chat's **copy code block** button on the reply (never select text by hand), run `apply`.",
                ],
                "cmds": [
                    (
                        "pack",
                        'relay pack --chat c0 --task \'Create src/chatop/__init__.py containing __version__ = "0.0.1" '
                        'and tests/test_version.py asserting that chatop.__version__ == "0.0.1".\'',
                    ),
                    ("apply (clipboard)", "relay apply"),
                ],
                "expect": [
                    "`red proven: the new tests fail without the code`, then `OK: 2 file(s) changed, committed: ...`.",
                    "`relay status` shows chat c0 as applied.",
                ],
                "check": "git log --oneline | head -2",
                "ifnot": [
                    "Rejected with a list of problems: the repair prompt is already on your clipboard; paste it into the "
                    "same chat and apply the new reply. See the failure guide (Appendix B) for each message.",
                    "`mypy` or `ruff` complain about the tiny files: fix nothing by hand; paste the evidence to the chat.",
                ],
            },
        ],
    },
    {
        "id": "act2",
        "title": "Act 2. Seed the design",
        "goal": "docs/ARCHITECTURE, DECISIONS, UX, BEHAVIOR and PLAN, the prompt files, and the codegraph CLI notes are committed.",
        "plays": [
            {
                "id": "2.1",
                "title": "Apply the seed design",
                "where": "terminal",
                "mode": "seeded",
                "do": [
                    "The seed is itself a reply file, so it goes in through the kernel like everything else (a docs-only "
                    "reply: no tests, one commit).",
                    "Read `docs/BEHAVIOR.md` and `docs/PLAN.md` now (ten minutes). They are the contract and the plan "
                    "the next acts build against. This is your design gate: change them here if you disagree, "
                    "before any code exists.",
                ],
                "cmds": [("apply", "relay apply bootstrap/seed/seed-design.reply.md")],
                "expect": [
                    "`OK: 5 file(s) changed, committed: seed: architecture, decisions, UX, behavior contract and reference plan`."
                ],
                "check": "ls docs   # ARCHITECTURE.md BEHAVIOR.md DECISIONS.md PLAN.md UX.md",
            },
            {
                "id": "2.1p",
                "title": "Have the chat design it (purist)",
                "where": "terminal + chat",
                "mode": "purist",
                "do": [
                    "Same destination files, authored by a chat. Save the brief, then ask for the architecture "
                    "and decisions, then for the behavior contract and the plan. You keep the fixed shape the "
                    "later plays rely on: eleven slices `S1..S11`, waves A to E, `depends/touches/reads` bullets.",
                    "Read every doc the chat returns. Cut anything the brief does not need.",
                ],
                "paste": ("the brief (also in the kit as bootstrap/seed/BRIEF.md)", "BRIEF"),
                "cmds": [
                    (
                        "architecture + decisions",
                        "cp bootstrap/seed/BRIEF.md docs/BRIEF.md\n"
                        "relay pack --chat c0 --read docs/BRIEF.md --task 'Write docs/ARCHITECTURE.md (layers, import rule, "
                        "ports, one turn end to end, parallel relay, state machine, data layout, testing strategy) and "
                        "docs/DECISIONS.md (ADR style, one per major choice, with context, decision, consequences) for "
                        "the project in docs/BRIEF.md. Use @@doc.'",
                    ),
                    ("apply", "relay apply"),
                    (
                        "behavior + plan",
                        "relay pack --chat c0 --read docs/ARCHITECTURE.md --read docs/BRIEF.md --task 'Write docs/BEHAVIOR.md "
                        "(CLI commands and exit codes, workflow tracks and gates, the status --json keys, the reply envelope "
                        "and the apply rules, parallel relay, file layout, ports) and docs/PLAN.md: eleven slices S1..S11 "
                        'as sections "## S1: title" with bullets depends:, touches:, reads:, goal:, acceptance:. Waves: '
                        "A = S1 models+reply parser, S4 ports+adapters; B = S2 changes/preflight/tdd, S3 workflow/scheduler/"
                        "stage/packet, S5 workspace/config/prompts; C = S6 session, S7 CLI; D = S8 recon, S9 lanes; E = S10 "
                        "web UI, S11 TUI. Slices of one wave must not share a file in touches. After S7 the lab runner "
                        "accept.py lab1 and lab2 must pass. Use @@doc.'",
                    ),
                    ("apply", "relay apply"),
                ],
                "expect": ["Two commits; `docs/PLAN.md` has sections `## S1` to `## S11`."],
                "ifnot": [
                    "The plan drifts from the wave shape: `relay undo`, and repeat with the wave list in the task."
                ],
            },
            {
                "id": "2.2",
                "title": "Apply the prompts, copy the contract, record the codegraph CLI",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "The prompt files are the words chatop later puts into packets. They are applied as a reply; one of "
                    "them (`contract.md`) describes the envelope itself and so cannot travel inside one: copy it as a file.",
                    "A chat cannot guess the real codegraph command line, so show it: the help text of each subcommand "
                    "goes into `docs/CODEGRAPH-CLI.md`, which slice S4 reads.",
                ],
                "cmds": [
                    (
                        "prompts",
                        "relay apply bootstrap/seed/seed-prompts.reply.md\n"
                        "cp bootstrap/seed/raw/contract.md src/chatop/prompts/contract.md",
                    ),
                    (
                        "codegraph notes",
                        "{ echo '# codegraph CLI (captured help text)'; for c in '' init sync status query callers callees impact files affected; do\n"
                        "  echo; echo \"## codegraph $c --help\"; echo '```'; codegraph $c --help 2>&1 | head -60; echo '```'; done; } > docs/CODEGRAPH-CLI.md\n"
                        "git add -A && git commit -qm 'seed: contract prompt and codegraph CLI notes'",
                    ),
                ],
                "expect": ["12 files in `src/chatop/prompts/` and a non-trivial `docs/CODEGRAPH-CLI.md`."],
                "check": "ls src/chatop/prompts | wc -l   # 12",
                "ifnot": [
                    "A codegraph subcommand prints an error in the notes: leave it; the chat sees it and avoids that call."
                ],
            },
            {
                "id": "2.3",
                "title": "Gate: the first packet reads well",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "Look at what a chat will receive for slice S1. If the task section is clear to you, it is clear to "
                    "the chat.",
                ],
                "cmds": [("preview", "relay pack S1 --chat c1 --print | head -80")],
                "expect": [
                    "The envelope contract, `## Task` with the S1 section, the BEHAVIOR document, and the repo file list."
                ],
                "ifnot": ["`no section '## S1'`: the plan was not applied; redo play 2.1."],
            },
        ],
    },
    {
        "id": "act3",
        "title": "Act 3. Build the core with the kernel",
        "goal": "Waves A to D: eleven slices minus the two UIs, in parallel chats. Ends with accept.py passing 5/5 labs.",
        "plays": [
            {
                "id": "3.1",
                "title": "The round trip (learn it once)",
                "where": "terminal + chat",
                "mode": "both",
                "do": [
                    "Every slice play below is this loop. `pack` copies the packet. Paste it into the slice's own fresh "
                    "chat. When the reply is complete (it ends with `<<<END>>>`), use the chat's copy-code-block "
                    "button and run `relay apply`.",
                    "Several chats may be open at once: pack all of a wave's slices first, paste each into its tab, "
                    "and apply the replies in whatever order they arrive. The header names the chat, so a reply "
                    "pasted to the wrong place is caught as stale.",
                    "Read the exit code: 0 done, 1 rejected (nothing changed; the repair prompt is on your clipboard), "
                    "3 applied but checks failed (files in place; the evidence is on your clipboard). In both cases paste "
                    "the clipboard into the same chat and apply the next reply.",
                ],
                "cmds": [
                    ("pack", "relay pack S1 --chat c1"),
                    ("apply", "relay apply   # reads the clipboard; or: relay apply path/to/reply.md"),
                    ("who owes me a reply?", "relay status"),
                    ("oops", "relay undo"),
                ],
                "expect": ["After apply: `OK: N file(s) changed, committed: <summary>`."],
                "ifnot": [
                    "Three failed attempts on the same slice: stop; read the failure guide (Appendix B), then decide whether to split the slice."
                ],
            },
            {
                "id": "3.2",
                "title": "Wave A: models and parser (S1), ports and adapters (S4)",
                "where": "terminal + chat",
                "mode": "both",
                "slice": "S1 S4",
                "do": [
                    "S1 and S4 share no files, so run two chats at the same time.",
                    "S4 needs the real codegraph command line: it reads `docs/CODEGRAPH-CLI.md` (play 2.2).",
                ],
                "cmds": [
                    ("c1 · S1", "relay pack S1 --chat c1"),
                    ("c4 · S4", "relay pack S4 --chat c4"),
                    ("after each reply", "relay apply"),
                ],
                "expect": [
                    "Both slices committed, each with a `red proven` line. The suite is green and `ruff` and `mypy --strict` are clean."
                ],
                "check": "pytest -q && ruff check src tests && mypy --strict src",
                "ifnot": [
                    "Rejected for a syntax error: the message names the file and line. Paste the repair prompt back.",
                    "S4: adapters that call a codegraph command that does not exist: paste the exact error and the relevant help section.",
                ],
            },
            {
                "id": "3.3",
                "title": "Wave B: changes (S2), workflow (S3), workspace and config (S5)",
                "where": "terminal + chat",
                "mode": "both",
                "slice": "S2 S3 S5",
                "do": [
                    "Three chats at once. All three import the S1 types; none of them touches the same file.",
                    "If a chat asks to change an S1 file, let it: the reply uses `@@edit`, and the kernel proves the SEARCH text matches.",
                ],
                "cmds": [
                    ("c2 · S2", "relay pack S2 --chat c2"),
                    ("c3 · S3", "relay pack S3 --chat c3"),
                    ("c5 · S5", "relay pack S5 --chat c5"),
                ],
                "expect": ["Three more commits. Test counts grow; mypy stays strict-clean."],
                "check": "pytest -q && ruff check src tests && mypy --strict src",
                "ifnot": [
                    "A test fails only after two slices are combined: pack a fix with the failing output as `--evidence` (Appendix B, case 7)."
                ],
            },
            {
                "id": "3.4",
                "title": "Wave C: session (S6), then the CLI (S7)",
                "where": "terminal + chat",
                "mode": "both",
                "slice": "S6 S7",
                "do": [
                    "S6 is the biggest slice and the one that wires everything. It is a single chat on purpose: "
                    "a use-case layer split across chats drifts.",
                    "Give it code context beyond the plan's reads when you have it: the symbols it will call.",
                    "S7 starts only after S6 is applied (it depends on `Session`).",
                ],
                "cmds": [
                    (
                        "c6 · S6",
                        "relay pack S6 --chat c6 --cg 'query Workspace' --cg 'callers plan_changes'",
                    ),
                    ("c7 · S7", "relay pack S7 --chat c7 --cg 'query Session'"),
                ],
                "expect": ["Two more commits and `chatop` still not installed."],
                "ifnot": [
                    "S6 reply is cut off (no `<<<END>>>`): tell the chat to answer in two replies, tests and the first half "
                    "of the code first, then the rest with `@@edit`. Pack again with `--task`.",
                ],
            },
            {
                "id": "3.5",
                "title": "Gate C: two labs pass",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "Install what the chat built and run the oracle. `accept.py` replays labs through the `chatop` command "
                    "line only, with the same reference replies the original app was proven against, so it does not care "
                    "how your chat structured the code.",
                    "lab1 = new project from an idea to shipped slices. lab2 = continue with a feature on a finished project.",
                ],
                "cmds": [
                    ("install", "pip install -q -e . && chatop doctor"),
                    (
                        "labs",
                        "CHATOP=chatop python bootstrap/accept.py lab1\nCHATOP=chatop python bootstrap/accept.py lab2",
                    ),
                ],
                "expect": ["`ok   new-project`, `ok   continue-feature`."],
                "ifnot": [
                    "A lab fails: the output names the step and the line, e.g. `new-project step 31: expect phase=done`. "
                    "Pack a fix for the owning slice with `--task` and the failing output as `--evidence`.",
                    "Most common: `status --json` is missing a key (BEHAVIOR 4), or the exit code of a rejection is not 1.",
                ],
            },
            {
                "id": "3.6",
                "title": "Wave D: recon (S8) and parallel lanes (S9)",
                "where": "terminal + chat",
                "mode": "both",
                "slice": "S8 S9",
                "do": [
                    "Two chats at once. Both make small changes to `session.py` and `cli.py` with `@@edit`; apply the "
                    "replies one at a time. If the second one's SEARCH no longer matches, the repair prompt says so: "
                    "re-pack that slice with `--read src/chatop/app/session.py` so the chat sees the new file.",
                ],
                "cmds": [
                    ("c8 · S8", "relay pack S8 --chat c8 --cg 'query Session' --cg 'files'"),
                    ("c9 · S9", "relay pack S9 --chat c9 --cg 'query Session'"),
                    ("labs", "CHATOP=chatop python bootstrap/accept.py all"),
                ],
                "expect": ["`chatop conformance: 5/5 labs passed`."],
                "ifnot": [
                    "lab3 and lab4 failing alone: S8. lab5 failing alone: S9. Both: look at the shared `Session` edits."
                ],
            },
            {
                "id": "3.7",
                "title": "Gate D: the core is done",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "Everything green, then tag. This is the last point at which the kernel is the only way to change the code."
                ],
                "cmds": [
                    (
                        "full check",
                        "pytest -q && ruff check . && mypy --strict src && CHATOP=chatop python bootstrap/accept.py all\n"
                        "git tag v0.1-core",
                    )
                ],
                "expect": ["No failures, 5/5 labs, a tag."],
                "ifnot": [
                    "`mypy --strict` failures across modules: one cleanup chat: `relay pack --task 'make mypy --strict pass' --evidence out.txt`."
                ],
            },
        ],
    },
    {
        "id": "act4",
        "title": "Act 4. Self-hosting: chatop builds chatop",
        "goal": "chatop adopts its own repo, then builds the web UI and the TUI with parallel chats. The kernel is retired.",
        "plays": [
            {
                "id": "4.1",
                "title": "Adopt the repo you just built",
                "where": "terminal + chat",
                "mode": "both",
                "do": [
                    "From here every command is `chatop`, not `relay`. Treat the repo as an unknown project: that is what "
                    "recon is for, and it is the live test of the adopt track.",
                    "`chatop next` copies the recon packet (repo map, churn, tests, agent markers). Paste into a fresh chat "
                    "(`c1` again; chatop numbers its own chats), copy the reply, `chatop apply`.",
                ],
                "cmds": [
                    (
                        "init",
                        "chatop init --track adopt\nchatop checks --set test 'python -m pytest -q'\nchatop checks --set lint 'ruff check src tests'\nchatop checks --set types 'mypy --strict src'",
                    ),
                    ("recon", "chatop next"),
                    ("apply", "chatop apply"),
                    ("where am I", "chatop status"),
                ],
                "expect": [
                    "`phase=done` and a `docs/RECON.md` the chat wrote. `chatop checks` lists the three checks."
                ],
                "ifnot": [
                    "`init` picked a different track: pass `--track adopt` as shown, never rely on detection here."
                ],
            },
            {
                "id": "4.2",
                "title": "First feature through chatop: web UI and TUI in parallel",
                "where": "terminal + chat",
                "mode": "both",
                "slice": "S10 S11",
                "do": [
                    "Turn on parallel mode and start one feature. The chat refines it (answer the questions with "
                    "`chatop accept`, or choose), writes the delta, then plans slices S10 and S11, which touch different files.",
                    "Approve the plan, then `chatop dispatch`: two chats get one issue each. For each chat: `chatop next cN`, "
                    "paste into a fresh tab, press `chatop sent cN`, and when the reply arrives `chatop apply` (any order). "
                    "`chatop board` shows who owes what.",
                    "Feed the chat the UX document and the labs' use cases: they are in `docs/`.",
                ],
                "paste": ("the feature text (also in the kit as bootstrap/seed/features/ui.txt)", "FEATURE_UI"),
                "cmds": [
                    (
                        "start",
                        'chatop config --set max_parallel 2\nchatop feature "$(cat bootstrap/seed/features/ui.txt)"',
                    ),
                    (
                        "loop",
                        "chatop next && chatop accept      # refine and delta turns\nchatop approve                  # at each gate you review docs/DELTA.md, docs/PLAN.md\nchatop dispatch\nchatop board",
                    ),
                    ("per chat", "chatop next c2\nchatop sent c2\nchatop apply\nchatop board"),
                ],
                "expect": ["`chatop board` ends with every chat closed; `chatop status` shows `phase=done`."],
                "check": "pytest -q && ruff check src tests && mypy --strict src",
                "ifnot": [
                    "A chat drifts or is blocked after 4 attempts: `chatop reset-chat cN`, open a fresh tab, send a full packet (`chatop next cN --full`)."
                ],
            },
            {
                "id": "4.3",
                "title": "Look at it and cut over",
                "where": "terminal",
                "mode": "both",
                "do": [
                    "Run both shells on the real project. The board should show the stages and the 'I pasted it' flag.",
                    "From now on `bootstrap/relay.py` is a rescue tool only; keep it in the repo, it has no dependencies.",
                ],
                "cmds": [
                    ("web", "chatop web --port 8765   # open http://127.0.0.1:8765"),
                    ("tui", "chatop tui"),
                    ("cut over", "CHATOP=chatop python bootstrap/accept.py all && git tag v0.1"),
                ],
                "expect": ["Both UIs open the board; 5/5 labs still pass; tag `v0.1`."],
            },
        ],
    },
    {
        "id": "act5",
        "title": "Act 5. Ready for continuous development",
        "goal": "Day-2 operation: features go through chatop, regressions are caught by the labs, rescue is one script away.",
        "plays": [
            {
                "id": "5.1",
                "title": "Readiness checklist",
                "where": "terminal",
                "mode": "both",
                "do": ["Tick each line when its command passes. All of them: you are done bootstrapping."],
                "checklist": [
                    ("Tests, lint and types are green", "pytest -q && ruff check . && mypy --strict src"),
                    ("The oracle passes", "CHATOP=chatop python bootstrap/accept.py all"),
                    ("chatop's own state says done", "chatop status   # phase=done"),
                    ("Checks are configured", "chatop checks   # test, lint, types"),
                    ("Parallel is configured", "chatop config   # max_parallel >= 2"),
                    ("A recon document exists", "ls docs/RECON.md"),
                    ("The web UI starts", "chatop web --port 8765   # open the board, Ctrl-C"),
                    ("The TUI starts", "chatop tui   # q to quit"),
                    ("Rescue works", "python bootstrap/relay_acceptance.py bootstrap/relay.py   # kernel OK"),
                    ("Everything is committed and tagged", "git status --short | wc -l; git tag"),
                ],
                "expect": ["Ten ticks."],
            },
            {
                "id": "5.2",
                "title": "Your first real features",
                "where": "terminal + chat",
                "mode": "both",
                "do": [
                    "Each feature below is a ready `chatop feature` text, small enough to finish in a few turns and "
                    "shaped to exercise a different part of the loop. Start with F1.",
                ],
                "backlog": True,
                "expect": ["Each ends with the labs still green."],
            },
            {
                "id": "5.3",
                "title": "The day-2 loop and when it breaks",
                "where": "terminal + chat",
                "mode": "both",
                "do": [
                    "Daily loop: `chatop feature` (or `chatop next` mid-flow) -> paste -> `chatop apply` -> repeat until the "
                    "board is closed. Keep `chatop watch` running if you like clipboard ping-pong.",
                    "Before you merge: run `CHATOP=chatop python bootstrap/accept.py all`. If a lab breaks, the change "
                    "broke observable behavior; fix the code or, if the behavior change is intended, change the lab "
                    "in the same feature.",
                    "If chatop itself is broken and cannot apply its own fix: `relay pack --task ... --evidence out.txt`, "
                    "apply with the kernel, and go back. That is what the kernel is for.",
                    "Unknown projects of unknown quality: `chatop init --track adopt` (or `audit`) in their repo; it is the same "
                    "tool you just built.",
                ],
                "cmds": [
                    (
                        "rescue",
                        "source bootstrap/env.sh\nrelay pack --task 'chatop apply crashes on ...' --evidence out.txt\nrelay apply",
                    ),
                ],
                "expect": ["You are in continuous development."],
            },
        ],
    },
]

FEATURE_UI = """Add the web UI and the terminal UI as thin shells over Session.

Web (FastAPI, `chatop web`): a projects hub; per-project board grouped by stage (your move / waiting for the LLM /
applying / closed); a single paste box that routes the reply to the right chat by its header and applies it; an
"I pasted it" button per chat (`sent`); approve and reject for gated phases; the page polls by event_seq.

TUI (Textual, `chatop tui`): the same board and actions, keyboard first.

Both: no business logic of their own, every action is one Session call. Read docs/UX.md and docs/BEHAVIOR.md."""

BACKLOG: list[dict[str, str]] = [
    {
        "id": "F1",
        "title": "doctor shows the codegraph version and index age",
        "text": "chatop doctor should print the codegraph version and say whether the index is older than the newest git commit.",
        "why": "small, one slice: tests plus an adapter method plus a doctor line.",
    },
    {
        "id": "F2",
        "title": "log: a readable journal",
        "text": "Add `chatop log [-n N]` that prints the last N journal events (time, event, phase, chat) one per line.",
        "why": "read-only feature on the CLI shell; good first use of parallel mode alongside F1.",
    },
    {
        "id": "F3",
        "title": "tolerate more chat UI quirks",
        "text": "The reply parser should accept an envelope wrapped in a ```chatop or plain ``` fence, with smart quotes in the header, and a missing trailing newline; add tests for each.",
        "why": "exercises the domain parser, where most real-world copy/paste problems live.",
    },
    {
        "id": "F4",
        "title": "token budget from config",
        "text": "Make the packet token budget configurable per chat (`chatop config --set budget_tokens N`) and print the estimated tokens when a packet is built.",
        "why": "touches config, packet assembly and the CLI: a three-file vertical slice.",
    },
    {
        "id": "F5",
        "title": "export the project memory",
        "text": "Add `chatop export OUT.md` that concatenates docs/PRD, SPEC, PLAN, RECON and the decisions into one markdown file for pasting into a fresh chat.",
        "why": "useful for the 'unknown project' case when a chat has lost the history.",
    },
    {
        "id": "F6",
        "title": "web board shortcuts",
        "text": "In the web UI add keyboard shortcuts: j/k to move between chats, p to focus the paste box, s to mark sent; show them in a help overlay.",
        "why": "UI-only and independent of F1 to F5: run it in parallel with another feature.",
    },
]

BUDGET: list[tuple[str, str, str, str]] = [
    ("Act 0 to 2", "setup, kernel, seed", "1 to 2 (shakedown) or 5 to 8 (purist)", "30 to 45 min seeded"),
    ("Wave A", "S1, S4", "2 to 4", "30 to 60 min"),
    ("Wave B", "S2, S3, S5", "3 to 6", "30 to 60 min"),
    ("Wave C", "S6, S7", "4 to 8", "1 to 2 h"),
    ("Wave D", "S8, S9", "3 to 6", "30 to 60 min"),
    ("Gates and integration", "labs, mypy, fixes", "2 to 6", "30 to 60 min"),
    ("Act 4", "adopt, S10, S11 via chatop", "8 to 14", "1 to 2 h"),
    ("Total", "", "about 25 to 45 pastes", "about 5 to 9 h of wall clock"),
]

FAILURES: list[tuple[str, str, str]] = [
    (
        "The reply has no envelope (prose, or code in plain fences)",
        "Rejected: no `<<<CHATOP` header found.",
        "Paste the repair prompt (already on the clipboard). If the chat keeps ignoring it, start a fresh tab with the same packet: some chats lose the thread after long answers.",
    ),
    (
        "The reply is cut off",
        "Rejected: truncated (no `<<<END>>>`).",
        "Ask for fewer files per reply, tests plus the first half of the code first and the rest as `@@edit`. Or split the slice: add `S6a` and `S6b` sections to docs/PLAN.md and pack each.",
    ),
    (
        "The copy button or your selection mangled the reply",
        "Parse problems on lines with `<<<<<<<` or `>>>>>>>`, or missing blank lines.",
        "Always use the reply's own copy-code-block button. Some UIs render `<<<` as markup when you select text.",
    ),
    (
        "A SEARCH block does not match",
        "`SEARCH text not found` or `ambiguous SEARCH`.",
        "The chat edited from memory of an older file. Re-pack the slice with `--read` for that file and say 'edit the file as shown'. If the file is small, ask for a full `@@file` rewrite.",
    ),
    (
        "The tests passed before the code existed",
        "`RED not proven`.",
        "The test does not test the change. The repair prompt asks for stronger tests. If the slice only refactors, apply with `relay apply --no-red` and say so in the commit.",
    ),
    (
        "Checks fail after applying",
        "exit 3, `CHECKS FAILED`, files stay in place.",
        "Paste the clipboard (evidence) into the same chat. Do not fix by hand. After three tries, read the failing test yourself: it is often a wrong test, not wrong code.",
    ),
    (
        "A chat 'fixes' a test by weakening it",
        "Green, but `git show --stat` shows a changed test file you did not expect.",
        "Review the stat of every commit before the next pack; `relay undo` and pack with the instruction 'do not change tests that already exist'.",
    ),
    (
        "Two chats changed the same file",
        "The second apply is rejected with a SEARCH problem.",
        "Expected for S8 and S9. Re-pack the second slice with `--read <file>` after the first is applied.",
    ),
    (
        "Stale bytecode makes a fixed bug look unfixed",
        "The same failure after a one-line fix, within the same second.",
        "The kernel sets `PYTHONDONTWRITEBYTECODE=1`. If you run pytest yourself in between, `find . -name __pycache__ -prune -exec rm -rf {} +`.",
    ),
    (
        "codegraph output does not match what an adapter expects",
        "The S4 contract tests pass but a real index returns no hits.",
        "Run `codegraph query main --json` in the repo, paste the output to the S4 chat's tab: 'the real output looks like this; make normalise_hits accept it'. The adapter is the only file that knows.",
    ),
    (
        "The clipboard is empty or the wrong thing",
        "`nothing to apply`, or a packet gets applied.",
        "Packets begin with `# CHATOP PACKET` and are never applied; use `relay apply FILE` with a saved reply (`.relay/replies/`).",
    ),
    (
        "A lab fails and you cannot tell which slice owns it",
        "`accept.py` prints `lab step N: <line>` and the tail of the output.",
        "Steps in the first third are S6/S7 (flow, CLI), recon steps S8, board/dispatch steps S9, apply rejections S2/S6. Pack a fix with the whole failure output as evidence.",
    ),
]

UNVERIFIED: list[str] = [
    "Turn and time figures are estimates from the shape of the plan, not measurements; replace them with your own "
    "numbers after wave A.",
    "The conformance labs and the kernel were verified against the reference implementation here. A chat-built "
    "implementation will differ in code; the labs are the oracle, not a diff against the reference.",
    "The codegraph command lines come from the reference adapter and `--help` capture; JSON shapes were not verified "
    "against a live index in the environment where this kit was built (play 2.2 and failure case 10 cover it).",
    "The real system clipboard (pbcopy, xclip, wl-copy) was not exercised in the build environment; the file-based "
    "fallback was.",
]
