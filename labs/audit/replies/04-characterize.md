````chatop
<<<CHATOP turn=@TURN@>>>
@@summary C1: pin current behavior, including the crash bug (R1), before changing anything
@@file conftest.py
# Makes the repo root importable for tests.
@@end
@@test tests/test_characterize.py
from pathlib import Path

import pytest

from inventory import load, restock, total_value

ITEMS = [{"sku": "A-1", "price": "9.99", "qty": 2}, {"sku": "B-7", "price": "4.50", "qty": 12}]


def test_total_value_current_behavior() -> None:
    with pytest.raises(ValueError):  # pins the R1 bug on purpose: decimal price strings crash
        total_value(ITEMS)


def test_restock_threshold() -> None:
    assert restock(ITEMS) == ["A-1"]
    assert restock(ITEMS, threshold=20) == ["A-1", "B-7"]


def test_load_swallows_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load(str(bad)) == []  # pins R2
@@end
<<<END>>>
````
