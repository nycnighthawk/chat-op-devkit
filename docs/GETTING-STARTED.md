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
pytest -q && mypy && ruff check src tests     # 62 tests, including all labs end to end
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

[checks]
test = "python -m pytest -q"
typecheck = "python -m mypy --strict src"
lint = "ruff check ."
```

## 7. Command reference

| Command | Purpose |
|---|---|
| `chatop init [--track new\|adopt\|audit] [--idea T \| --idea-file F]` | start managing the project |
| `chatop next [--accept] [--approve] [--print] [--no-clip]` | build and copy the packet (idempotent within a turn) |
| `chatop apply [FILE\|-] [--force]` | apply a reply (default: from the clipboard) |
| `chatop watch [--interval S]` | clipboard ping-pong |
| `chatop answer [ID CHOICE… --other T]` / `chatop accept` | answer questions |
| `chatop approve [--note T]` / `chatop reject NOTE` | gates |
| `chatop feature "TEXT" [--force]` | new work on a finished track |
| `chatop checks [--accept] [--set N CMD] [--unset N]` | manage check commands |
| `chatop undo` | revert the last uncommitted apply (files and state) |
| `chatop status [--json]` · `chatop doctor` | where am I · environment |
| `chatop tui` · `chatop web [--port 8765]` | UIs |

## 8. Troubleshooting

* **"clipboard unavailable"**: install wl-clipboard or xclip, or use `CHATOP_CLIPBOARD=file` and the
  `.chatop/outbox.md` / `.chatop/inbox.md` files.
* **"reply looks truncated"**: ask the LLM to "re-emit the CHATOP block with fewer files", or to continue it.
* **"SEARCH text not found"**: the repair prompt asks the LLM to use `@@need file` or `@@file`. Paste it.
* **Symbol context is empty**: codegraph is missing or not indexed. Run `chatop doctor`; `codegraph init -i` runs
  on `chatop init` for existing code.
* **Wrong turn**: `chatop next` re-copies the current packet. Old packets are in `.chatop/packets/`.
