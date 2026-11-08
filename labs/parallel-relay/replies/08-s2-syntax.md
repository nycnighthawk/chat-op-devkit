````chatop
<<<CHATOP chat=@CHAT:S2@ turn=@TURN:S2@>>>
@@summary S2 numeric column detection
@@test tests/test_align.py
from csv2md.align import numeric_columns

class TestNumeric(
    def test_detects(self) -> None:
        assert numeric_columns([["n"], ["1"]]) == {0}
@@end
@@file src/csv2md/align.py
def numeric_columns(rows:
    return set()
@@end
<<<END>>>
````
