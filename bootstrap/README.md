# bootstrap: build chatop with chat only

Everything needed to rebuild chatop from an empty folder without a coding agent. Start with the page
[`docs/chatop-bootstrap-plays.html`](../docs/chatop-bootstrap-plays.html) (it embeds all of this as a downloadable kit).

| File | Role |
|---|---|
| `relay.py` | stage-0 kernel (stdlib only): `pack` a packet for a chat, `apply` its reply with red/green TDD, commit |
| `relay_acceptance.py` | 9 black-box checks any `relay.py` must pass (so a chat can write the kernel too) |
| `accept.py` | **generated**; replays the five labs through the `chatop` CLI: `CHATOP=chatop python bootstrap/accept.py all` |
| `accept_template.py` | source of `accept.py`; labs are embedded by `scripts/build_bootstrap.py` |
| `env.sh` | the `relay` shell function and `RELAY_CHECKS` |
| `seed/` | behavior contract, 11-slice plan, ready-to-apply replies for the design docs and prompts, brief, feature text |
| `kit/` | skeleton `pyproject.toml` and `.gitignore` for the new repo |

`docs/SPEC-BUNDLE.md`, `docs/AGENT-PROMPTS.md` and `docs/BEHAVIOR.md` are generated too. `seed/*.reply.md`, `seed/raw/`, `seed/BRIEF.md`, `seed/features/` and `accept.py` are generated:
`python scripts/build_bootstrap.py` (and `--check`, which the tests run). Edit `seed/BEHAVIOR.md`, `seed/PLAN.md`,
`scripts/bootstrap_plays.py` (the plays) or `docs/bootstrap-plays.template.html`, then rebuild.

Not verified here: turn and time estimates, the real system clipboard, codegraph JSON shapes against a live index, and
a real chat-built run end to end. The labs are the oracle for any chat-built implementation.
