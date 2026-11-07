````chatop
<<<CHATOP turn=@TURN@>>>
@@summary S2 CLI: file or stdin
@@test tests/test_cli.py
import io
from pathlib import Path

import pytest

from csv2md.cli import main


def test_reads_stdin(capsys: pytest.CaptureFixture[str]) -> None:  # AC-2.1
    assert main([], stdin=io.StringIO("a,b\n1,2\n")) == 0
    assert capsys.readouterr().out.startswith("| a | b |")


def test_reads_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # AC-2.2
    f = tmp_path / "d.csv"
    f.write_text("x\n1\n")
    assert main([str(f)]) == 0
    assert "| 1 |" in capsys.readouterr().out


def test_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["/nope.csv"]) == 2
@@end
@@file src/csv2md/cli.py
"""Thin I/O shell around csv2md.convert."""

import csv
import sys
from typing import TextIO

from csv2md.convert import to_markdown


def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args:
            with open(args[0], newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
        else:
            rows = list(csv.reader(stdin or sys.stdin))
    except OSError as exc:
        print(f"csv2md: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(to_markdown(rows))
    return 0
@@end
<<<END>>>
````
