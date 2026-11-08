# chat-op-devkit · `chatop`

**Turn any chat LLM (Claude.ai, ChatGPT, Gemini) into a disciplined, TDD-driven engineer, using nothing
but copy and paste.** No coding harness or agent runtime is needed. The development machine is macOS or Linux,
and all code search goes through the [`codegraph`](https://github.com/colbymchenry/codegraph) CLI.

```
           ┌──────────── one turn = 2 clipboard hops ────────────┐
 chatop next ──► packet on clipboard ──► paste into chat ──► LLM replies with ONE ````chatop block
      ▲                                                                       │
      └── next packet auto-copied ◄── checks run ◄── applied atomically ◄── copy reply (chatop watch picks it up)
```

* **Playbook and design (interactive HTML):** [`docs/chatop-playbook.html`](docs/chatop-playbook.html). Download it
  and open it in a browser. It covers architecture, decisions, the kit, setup, prompts, use-case walkthroughs and labs.
* Markdown versions: [Getting started](docs/GETTING-STARTED.md) · [Playbook](docs/PLAYBOOK.md) ·
  [Mock UI](docs/chatop-mock-ui.html) · [Labs](docs/LABS.md) · [Architecture](docs/ARCHITECTURE.md) · [Decisions (ADRs)](docs/DECISIONS.md)

## Why

Without a harness, chat-based development wastes turns on three things: re-explaining context, guessing which files
matter, and hand-applying code that was never run. `chatop` removes all three:

| Waste | chatop's answer |
|---|---|
| Re-explaining state every chat | Project memory lives in the repo (`.chatop/state.json`, `docs/*.md`). Every packet is self-contained, so a fresh chat works. |
| "Paste me file X" round-trips | Slices declare `touches`; chatop pre-loads those files and symbols through codegraph (`query`, `callers`, `impact`, `affected`). Leftover gaps are batched with `@@need`. |
| Manually applying code | The LLM answers in one machine-applicable envelope. chatop validates paths, applies atomically, runs the checks, and feeds the evidence back. |
| Waiting on one chat at a time | **Parallel relay**: the plan becomes issues; several chats work at once, each issue goes to the chat that already holds its files, replies are routed by header in any order, and a failing chat never blocks another. |
| TDD on the honour system | Two-stage apply: tests are written alone and must **fail**, then the code is applied and everything must **pass**. Both in one turn. |
| Lost questions | `@@ask` questions arrive as multi-select forms with the recommended options pre-checked, plus free-text "other". One key accepts all. |

## Install

```bash
# prerequisites: Python ≥3.11, git, Node (for codegraph)
npm i -g @colbymchenry/codegraph            # code search engine (required)
git clone https://github.com/nycnighthawk/chat-op-devkit && cd chat-op-devkit
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
chatop --help
# Linux clipboard: install wl-clipboard (Wayland) or xclip/xsel (X11). macOS uses pbcopy/pbpaste.
# Headless? CHATOP_CLIPBOARD=file → packets go to .chatop/outbox.md; replies are read from .chatop/inbox.md.
```

## 60-second tour

```bash
mkdir my-app && cd my-app && git init
chatop init --track new --idea "Personal finance CLI that imports bank CSVs and flags anomalies"
chatop watch            # clipboard ping-pong: now only copy/paste between terminal-free chat and clipboard
#   paste packet into chat → click "copy" on the LLM's ````chatop block → chatop applies it and copies the next packet
#   questions? → chatop accept (recommended) or chatop answer
#   gates (PRD/SPEC/PLAN)? → review docs/ → chatop approve  |  chatop reject "why"
chatop tui              # or the full-screen terminal UI
chatop web              # or http://127.0.0.1:8765
```

Existing code: `chatop init --track adopt` (sane code by other agents) or `--track audit` (unknown quality; the default
for code with no passing tests). Finished project, new work: `chatop feature "Add OFX import"`.

## Parallel relay

```bash
chatop init --parallel 3 --idea "…"     # or: chatop config --set max_parallel 3
chatop board                              # chats, issues, events;  web UI: the board is the main view
```
The approved plan becomes **issues** (`depends`, `touches`). Each ready issue goes to a chat: new chats get a full
packet, continuing chats a small **delta**. Paste any reply anywhere: its `chat=` header routes it. Generated files
are linted **all at once**; a chat's failing code stays in its own overlay. Try it without installing anything:
[`docs/chatop-mock-ui.html`](docs/chatop-mock-ui.html) (the real page on a scripted backend).

## Tracks

| Track | Phases | Use when |
|---|---|---|
| `new` | idea → refine ⟲ → **prd** → **spec** → **plan** → slice ⟲ → done | greenfield from a vague idea |
| `continue` | feature → refine ⟲ → **delta** → **plan** → slice ⟲ → done | adding to a chatop-managed (or adopted) project |
| `adopt` | recon → done (then `feature`) | unknown code that seems healthy (tests pass) |
| `audit` | recon → **audit** → **plan** (stabilise) → slice ⟲ → done | unknown code of unknown quality |

**Bold** = human approval gate (configurable).

## Architecture in one picture

```
 ui/cli.py   ui/tui.py   ui/web.py       ← thin shells, no logic
        └───────┬───────┘
          app/session.py (Session facade = the ONLY API the UIs use)
        ┌───────┼───────────────────────────────┐
  domain/ (pure: reply parser, change planner,   ports.py (Protocols)
  packet budgeter, workflow state machine)        ├ CodeIndex ← adapters/codegraph.py
                                                  ├ Clipboard ← adapters/clipboard.py
                                                  ├ Runner    ← adapters/runner.py
                                                  └ Vcs       ← adapters/git.py
```

The import rule (enforced by review and by the test layout): `domain` imports nothing from chatop except `domain`.
`app` imports `domain` and `ports`. `adapters` import `ports` only. `ui` imports `app` only (and `domain.models` enums).
`app/wiring.py` is the single composition root.

## Develop chatop itself (TDD)

```bash
pytest -q            # 126 tests: domain unit, adapter contract, session + lane use cases (real git + pytest), UI shells, labs, mock UI (node)
mypy                 # --strict
ruff check src tests
```

Write the failing test first, in the layer you are changing: `tests/domain` for pure logic, `tests/adapters` for
adapters, `tests/app/test_session.py` for use cases, and `tests/ui` for the shells.

## License

MIT
