````chatop
<<<CHATOP chat=@CHAT:S2@ turn=@TURN:S2@>>>
@@summary S2 numeric column detection (syntax fixed, full suite)
@@test tests/test_align.py
from csv2md.align import numeric_columns


def test_detects_numeric_columns() -> None:  # AC-3.1
    assert numeric_columns([["n", "t"], ["1", "a"], ["2,5", "b"]]) == {0}


def test_header_is_ignored() -> None:
    assert numeric_columns([["1", "x"], ["a", "2"]]) == {1}


def test_empty_and_header_only() -> None:
    assert numeric_columns([]) == set()
    assert numeric_columns([["a"]]) == set()


def test_ragged_rows_are_not_numeric() -> None:
    assert numeric_columns([["a", "b"], ["1"]]) == {0}
@@end
@@file src/csv2md/align.py
"""Which columns hold numbers (so they can be right-aligned)."""


def _is_number(cell: str) -> bool:
    try:
        float(cell.replace(",", ""))
    except ValueError:
        return False
    return True


def numeric_columns(rows: list[list[str]]) -> set[int]:
    body = rows[1:]
    if not body:
        return set()
    width = max(len(r) for r in rows)
    return {i for i in range(width) if all(i < len(r) and _is_number(r[i]) for r in body)}
@@end
<<<END>>>
````
