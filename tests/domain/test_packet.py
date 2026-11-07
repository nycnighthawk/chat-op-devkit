"""Packet assembly: the single outbound boundary to the chat LLM, under a token budget."""

from chatop.domain.packet import Section, assemble, estimate_tokens


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_fits_without_truncation() -> None:
    text, notes = assemble([Section("A", "alpha", 0), Section("B", "beta", 2)], budget=1000)
    assert "## A" in text and "beta" in text and notes == []


def test_lowest_priority_truncated_first_required_kept() -> None:
    required = Section("Rules", "R" * 400, 0)
    docs = Section("Docs", "D" * 2000, 2)
    repo = Section("Repo map", "M" * 2000, 5)
    text, notes = assemble([required, docs, repo], budget=700)
    assert "R" * 400 in text
    assert any("Repo map" in n for n in notes)
    assert estimate_tokens(text) <= 700 + 60  # headers/notes overhead allowance
    assert text.index("## Rules") < text.index("## Docs")  # order preserved


def test_section_dropped_when_nothing_fits() -> None:
    text, notes = assemble([Section("Rules", "R" * 2800, 0), Section("Extra", "E" * 4000, 9)], budget=700)
    assert "## Extra" not in text
    assert any("dropped" in n for n in notes)


def test_empty_sections_skipped() -> None:
    text, _ = assemble([Section("A", "x", 0), Section("Empty", "  ", 1)], budget=100)
    assert "Empty" not in text
