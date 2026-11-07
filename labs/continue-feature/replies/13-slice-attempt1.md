````chatop
<<<CHATOP turn=@TURN@>>>
@@summary F1-S1 alignment (attempt 1)
@@test tests/test_align.py
import io

import pytest

from csv2md.cli import main
from csv2md.convert import to_markdown


def test_right() -> None:  # AC-3.1
    assert to_markdown([["a"], ["1"]], "right").splitlines()[1] == "| ---: |"


def test_center_and_default() -> None:  # AC-3.2
    assert to_markdown([["a"], ["1"]], "center").splitlines()[1] == "| :---: |"
    assert to_markdown([["a"], ["1"]]).splitlines()[1] == "| --- |"


def test_cli_flag(capsys: pytest.CaptureFixture[str]) -> None:  # AC-3.3
    assert main(["--align", "center"], stdin=io.StringIO("a\n1\n")) == 0
    assert ":---:" in capsys.readouterr().out
@@end
@@edit src/csv2md/convert.py
<<<<<<< SEARCH
def to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
=======
_SEP = {"left": "---", "center": ":--:", "right": "---:"}


def to_markdown(rows: list[list[str]], align: str = "left") -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    sep = _SEP[align]
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |", "| " + " | ".join([sep] * width) + " |"]
>>>>>>> REPLACE
@@end
@@edit src/csv2md/cli.py
<<<<<<< SEARCH
    args = sys.argv[1:] if argv is None else argv
=======
    args = list(sys.argv[1:] if argv is None else argv)
    align = "left"
    if "--align" in args:
        i = args.index("--align")
        align = args[i + 1]
        del args[i : i + 2]
>>>>>>> REPLACE
<<<<<<< SEARCH
    sys.stdout.write(to_markdown(rows))
=======
    sys.stdout.write(to_markdown(rows, align))
>>>>>>> REPLACE
@@end
<<<END>>>
````
