````chatop
<<<CHATOP turn=@TURN@>>>
@@summary F1: compute value with Decimal; update the pinned expectation
@@edit tests/test_characterize.py
<<<<<<< SEARCH
from pathlib import Path
=======
from decimal import Decimal
from pathlib import Path
>>>>>>> REPLACE
<<<<<<< SEARCH
def test_total_value_current_behavior() -> None:
    with pytest.raises(ValueError):  # pins the R1 bug on purpose: decimal price strings crash
        total_value(ITEMS)
=======
def test_total_value_is_exact() -> None:  # R1 fixed
    assert total_value(ITEMS) == Decimal("9.99") * 2 + Decimal("4.50") * 12
>>>>>>> REPLACE
@@end
@@edit inventory.py
<<<<<<< SEARCH
import json
import sys
=======
import json
import sys
from decimal import Decimal
>>>>>>> REPLACE
<<<<<<< SEARCH
    total = 0
    for it in items:
        total += int(it["price"]) * it["qty"]
=======
    total = Decimal("0")
    for it in items:
        total += Decimal(str(it["price"])) * it["qty"]
>>>>>>> REPLACE
@@end
<<<END>>>
````
