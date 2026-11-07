"""Assemble an outbound packet from prioritised sections under a token budget.

Priority 0 = required (never cut). Higher numbers are cut first.
"""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4


@dataclass
class Section:
    title: str
    body: str
    priority: int = 0


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _render(sections: list[Section]) -> str:
    return "\n\n".join(f"## {s.title}\n\n{s.body.rstrip()}" for s in sections) + "\n"


def assemble(sections: list[Section], budget: int) -> tuple[str, list[str]]:
    live = [Section(s.title, s.body, s.priority) for s in sections if s.body.strip()]
    notes: list[str] = []
    cut_order = sorted((s for s in live if s.priority > 0), key=lambda s: -s.priority)
    for victim in cut_order:
        over = estimate_tokens(_render(live)) - budget
        if over <= 0:
            break
        keep_tokens = estimate_tokens(victim.body) - over - 40
        if keep_tokens < 200:
            live.remove(victim)
            notes.append(f"dropped section '{victim.title}' (budget)")
        else:
            cut = estimate_tokens(victim.body) - keep_tokens
            victim.body = (
                victim.body[: keep_tokens * CHARS_PER_TOKEN]
                + f"\n\n[... truncated ~{cut} tokens by budget; use @@need to request specifics]"
            )
            notes.append(f"truncated section '{victim.title}' by ~{cut} tokens")
    return _render(live), notes
