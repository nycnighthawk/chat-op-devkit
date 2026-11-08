````chatop
<<<CHATOP chat=@CHAT:S3@ turn=@TURN:S3@>>>
@@summary S3 CLI with --align, to_markdown gains right-aligned columns
@@test tests/test_cli.py
import io
from pathlib import Path

import pytest

from csv2md.cli import main
from csv2md.convert import to_markdown


def test_reads_stdin(capsys: pytest.CaptureFixture[str]) -> None:  # AC-2.1
    assert main([], stdin=io.StringIO("a,b\n1,2\n")) == 0
    assert capsys.readouterr().out.startswith("| a | b |")


def test_reads_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # AC-2.2
    f = tmp_path / "d.csv"
    f.write_text("x\n1\n")
    assert main([str(f)]) == 0
    assert "| 1 |" in capsys.readouterr().out


def test_missing_file() -> None:
    assert main(["/nope.csv"]) == 2


def test_align_flag_right_aligns_numbers(capsys: pytest.CaptureFixture[str]) -> None:  # AC-3.2
    assert main(["--align"], stdin=io.StringIO("n,t\n1,a\n22,b\n")) == 0
    assert "| ---: | --- |" in capsys.readouterr().out


def test_to_markdown_right_columns() -> None:
    assert to_markdown([["a", "b"], ["1", "x"]], {1}).splitlines()[1] == "| --- | ---: |"
@@end
@@edit src/csv2md/convert.py
<<<<<<< SEARCH
def to_markdown(rows: list[list[str]]) -> str:
=======
def to_markdown(rows: list[list[str]], right: set[int] | None = None) -> str:
>>>>>>> REPLACE
<<<<<<< SEARCH
    width = max(len(r) for r in rows)
=======
    width = max(len(r) for r in rows)
    right_cols = right or set()
>>>>>>> REPLACE
<<<<<<< SEARCH
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
=======
    sep = " | ".join("---:" if i in right_cols else "---" for i in range(width))
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |", "| " + sep + " |"]
>>>>>>> REPLACE
@@end
@@file src/csv2md/cli.py
"""Thin I/O shell around csv2md.convert."""

import csv
import sys
from typing import TextIO

from csv2md.align import numeric_columns
from csv2md.convert import to_markdown


def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    align = "--align" in args
    paths = [a for a in args if a != "--align"]
    try:
        if paths:
            with open(paths[0], newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
        else:
            rows = list(csv.reader(stdin or sys.stdin))
    except OSError as exc:
        print(f"csv2md: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(to_markdown(rows, numeric_columns(rows) if align else None))
    return 0
@@end
<<<END>>>
````
