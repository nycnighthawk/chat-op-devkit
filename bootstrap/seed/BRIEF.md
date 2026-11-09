# Brief: chatop

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
