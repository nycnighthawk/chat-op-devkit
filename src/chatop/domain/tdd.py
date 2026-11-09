"""The TDD verdict for a slice, shared by the serial flow and parallel chats (pure)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verdict:
    done: bool
    notes: list[str]
    red_proven: bool


def judge_slice(
    *,
    strict: bool,
    red_ok: bool | None,
    red_already: bool,
    check_codes: list[int],
    has_tests: bool,
    has_code: bool,
    advance: bool,
    touched: bool,
) -> Verdict:
    notes: list[str] = []
    if red_ok is False:
        notes.append(
            "RED not proven: the new tests already passed before the implementation was applied. "
            "Strengthen the tests so they fail without the change, or add @@advance if this slice "
            "only pins existing behavior."
        )
    if not check_codes:
        notes.append("No checks configured, so the slice cannot be verified. Propose them with @@check.")
    red_proven = red_already or bool(red_ok)
    tdd_ok = red_ok is not False or advance or not strict
    if strict and has_code and not has_tests and not advance and not red_proven:
        tdd_ok = False
        notes.append("Code changed without tests. Add @@test files, or @@advance for a pure refactor.")
    all_green = bool(check_codes) and all(c == 0 for c in check_codes)
    return Verdict(touched and all_green and tdd_ok, notes, red_proven)
