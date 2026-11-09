# Getting started

## 1. Install (macOS or Linux)

```bash
# Prerequisites: Python ≥ 3.11, git, Node ≥ 18 (for codegraph)
npm i -g @colbymchenry/codegraph

git clone https://github.com/nycnighthawk/chat-op-devkit
cd chat-op-devkit
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

# Linux clipboard (pick one): sudo apt install wl-clipboard   |   sudo apt install xclip
chatop --help
```

Build or verify from source:

```bash
pytest -q && mypy && ruff check src tests     # 145 tests, including all five labs end to end
python -m build                               # optional: wheel in dist/ (pip install build)
```

## 2. Check the environment

```bash
cd /path/to/any/project && chatop doctor
[ok] python>=3.11: 3.12.4
[ok] codegraph CLI: found
[ok] git repository: yes
[ok] clipboard: backend: pbcopy
[!!] checks configured: LLM proposes them in SPEC/RECON, or: chatop checks --set test '<cmd>'
```

## 3. Try it offline first (two minutes, no LLM needed)

```bash
python labs/run_lab.py new-project --workdir /tmp/lab1
cd /tmp/lab1 && ls docs && git log --oneline && cat .chatop/packets/turn-0007.md | less
```

The lab replays reference LLM replies through the real app: packets, apply, the TDD red/green proof, checks and commits.

## 4. Your first real project

```bash
mkdir ~/code/my-tool && cd ~/code/my-tool && git init
chatop init --track new --idea "describe it in one or two sentences, vaguely is fine"
chatop watch
```

Then, in your chat app (Claude.ai, ChatGPT or Gemini):

1. **Paste** (the packet is already on your clipboard).
2. When the reply finishes, click **copy** on the ````chatop code block, or select the whole message and copy it.
3. `chatop watch` notices, applies the reply, runs the checks, and copies the **next packet**. Go back to step 1.

When chatop needs you, it stops and says so:

| You see | Do |
|---|---|
| `awaiting_answers` | `chatop accept` (recommended options) or `chatop answer` (interactive), then `chatop next` |
| `awaiting_approval` | read the doc (`docs/PRD.md`, …), then `chatop approve` or `chatop reject "what to change"`, then `chatop next` |
| `REJECTED` | the repair prompt is on your clipboard: paste it into the **same** chat |
| proposed checks | `chatop checks`, review the commands, then `chatop checks --accept` |

Prefer screens? `chatop tui` (keys: **n** next · **a** apply clipboard · **w** watch · **y** accept · **p** approve ·
**u** undo · **q** quit) or `chatop web` → <http://127.0.0.1:8765>.

## 5. Existing code

```bash
cd existing-repo
chatop init                 # auto: adopt (tests exist and a test command is detected) or audit (otherwise)
chatop init --track audit   # force a quality audit
chatop watch
# after recon/audit:  chatop feature "the thing you want next"
```

## 6. Configuration: `.chatop/config.toml`

```toml
[chatop]
budget_tokens = 80000        # packet budget (models have ≥250K; leaves room for reply + history)
max_refine_rounds = 3
max_questions = 6
gates = ["prd", "spec", "delta", "plan", "audit"]
protected = [".git/**", ".chatop/**", ".codegraph/**", ".env", ".env.*", "**/*.pem", "**/id_rsa*"]
tdd_strict = true            # slices must prove RED before GREEN (audit track exempt)
auto_commit = true           # commit each completed slice
auto_next = true             # build + copy the next packet right after a successful apply
codegraph_bin = "codegraph"
check_timeout = 900
max_file_lines = 400         # larger files are truncated in context (the LLM can @@need symbols)
max_parallel = 1             # chats worked at once; >1 turns the plan into issues for parallel chats
max_attempts = 4             # failed attempts before an issue is blocked for a human decision
max_issues_per_chat = 3      # after this many issues a chat is retired (long chats drift)
auto_dispatch = true         # hand newly unblocked issues to chats as soon as one finishes
delta_packets = true         # continuing chats get only what changed

[checks]
test = "python -m pytest -q"
typecheck = "python -m mypy --strict src"
lint = "ruff check ."

[preflight]                  # optional: linters run ONCE over all generated files before tests ({files})
"**/*.py" = "ruff check --quiet {files}"
```

Python, JSON and TOML files are always syntax-checked in one shot with no configuration.

## 7. Command reference

| Command | Purpose |
|---|---|
| `chatop init [--track new\|adopt\|audit] [--idea T \| --idea-file F] [--parallel N]` | start managing the project |
| `chatop next [CHAT] [--full] [--accept] [--approve] [--print] [--no-clip]` | build and copy the packet (idempotent within a turn). Parallel mode: the next chat up, or the named one; `--full` for a fresh tab |
| `chatop apply [FILE\|-] [--force]` | apply a reply (default: from the clipboard) |
| `chatop watch [--interval S]` | clipboard ping-pong |
| `chatop answer [ID CHOICE… --other T] [--chat C]` / `chatop accept [--chat C]` | answer questions |
| `chatop board [--json]` | parallel mode: chats, issues, recent events, tokens saved |
| `chatop dispatch` · `chatop assign ISSUE [--chat C]` | hand ready issues to chats (automatic by default) · manual override |
| `chatop sent CHAT [--undo]` | flag that you pasted a chat's packet (or repair prompt); the board then shows how long it has been waiting |
| `chatop reset-chat CHAT` | unblock a chat, or you opened a fresh tab: its next packet is a full one |
| `chatop config [--set KEY VALUE]` | show options · change a scalar option (e.g. `max_parallel 3`) |
| `chatop approve [--note T]` / `chatop reject NOTE` | gates |
| `chatop feature "TEXT" [--force]` | new work on a finished track |
| `chatop checks [--accept] [--set N CMD] [--unset N]` | manage check commands |
| `chatop undo` | revert the last uncommitted apply (files and state) |
| `chatop status [--json]` · `chatop doctor` | where am I · environment |
| `chatop tui` · `chatop web [--port 8765]` | UIs |

## 7b. Parallel relay in five minutes

```bash
chatop init --track new --parallel 3 --idea "…"     # or later: chatop config --set max_parallel 3
chatop web                                           # the board is the web UI's main view (TUI: tab "Board")
```
1. Work PRD → SPEC → PLAN as usual. Approve the plan: chatop turns it into issues and opens chats for every issue
   that can start (the board shows them as *ready to send*).
2. Open one browser tab per chat and name them `c1, c2, …`. For each ready chat press **Copy packet**, paste it in its tab.
3. Whenever a tab finishes, copy its `chatop` block and paste it into the big **paste box** (or run `chatop watch`).
   The header routes it; chatop applies it in the background and shows *ready / done / question / blocked*.
4. A chat with a *ready* badge has its next packet waiting (a small delta). Repeat until the board says *finished*.

No install? Open [`chatop-mock-ui.html`](chatop-mock-ui.html): the real page against a scripted backend and chat tabs.

## 8. Troubleshooting

* **"clipboard unavailable"**: install wl-clipboard or xclip, or use `CHATOP_CLIPBOARD=file` and the
  `.chatop/outbox.md` / `.chatop/inbox.md` files.
* **"reply looks truncated"**: ask the LLM to "re-emit the CHATOP block with fewer files", or to continue it.
* **"SEARCH text not found"**: the repair prompt asks the LLM to use `@@need file` or `@@file`. Paste it.
* **Symbol context is empty**: codegraph is missing or not indexed. Run `chatop doctor`; `codegraph init -i` runs
  on `chatop init` for existing code.
* **"unknown chat cN" or "several chats are waiting"**: the reply's header is missing or wrong. Add `chat=cN`
  (the packet's header line shows it) and paste again.
* **A chat says it has no earlier context** (fresh tab, lost history): `chatop next cN --full`, or "Copy full" in the web UI.
* **Parallelism stays at 1**: check `chatop config` (`max_parallel`), that the plan has `depends`/`touches`, and that
  independent issues touch different files (overlapping or empty `touches` run one after another).
* **Wrong turn**: `chatop next` re-copies the current packet. Old packets are in `.chatop/packets/`.
