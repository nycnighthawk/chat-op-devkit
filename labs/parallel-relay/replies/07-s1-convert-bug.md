````chatop
<<<CHATOP chat=@CHAT:S1@ turn=@TURN:S1@>>>
@@summary S1 converter (first try)
@@test tests/test_convert.py
from csv2md.convert import to_markdown


def test_basic_table() -> None:  # AC-1.1
    assert to_markdown([["a", "b"], ["1", "2"]]) == "| a | b |\n| --- | --- |\n| 1 | 2 |\n"


def test_pipe_escaped() -> None:  # AC-1.2
    assert "x \\| y" in to_markdown([["h"], ["x | y"]])


def test_ragged_rows_padded() -> None:  # AC-1.3
    assert to_markdown([["a", "b"], ["1"]]).splitlines()[2] == "| 1 |  |"


def test_empty_input() -> None:
    assert to_markdown([]) == ""
@@end
@@file src/csv2md/convert.py
"""Pure conversion core (no I/O)."""


def _cell(value: str) -> str:
    return value.strip()


def to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in padded[1:]]
    return "\n".join(lines) + "\n"
@@end
<<<END>>>
````
