"""Preflight: lint every generated file in ONE shot, so one reply surfaces every syntax problem."""

from chatop.domain.preflight import (
    Diagnostic,
    check_all,
    check_syntax,
    parse_tool_output,
    render_command,
    select_files,
)


def test_python_syntax_error_has_location() -> None:
    d = check_syntax("src/a.py", "def f(:\n    pass\n")
    assert len(d) == 1 and d[0].path == "src/a.py" and d[0].line == 1 and d[0].message
    assert d[0].render().startswith("src/a.py:1")


def test_python_indentation_error_and_ok_file() -> None:
    assert check_syntax("a.py", "def f():\nreturn 1\n")  # IndentationError
    assert check_syntax("a.py", "x: int = 1\n") == []


def test_json_and_toml_and_unknown_extension() -> None:
    assert check_syntax("c.json", "{not json")[0].line == 1
    assert check_syntax("c.json", '{"a": 1}') == []
    assert check_syntax("c.toml", "a = = 1")[0].path == "c.toml"
    assert check_syntax("notes.txt", "def f(:") == []


def test_check_all_reports_every_file_at_once_sorted() -> None:
    files = {"b.py": "x = (\n", "a.py": "def f(:\n", "ok.py": "y = 1\n", "gone.py": None, "d.json": "{"}
    diags = check_all(files)
    assert [d.path for d in diags] == ["a.py", "b.py", "d.json"]


def test_select_files_and_render_command() -> None:
    paths = ["src/a.py", "src/b.ts", "tests/test_a.py", "README.md"]
    assert select_files("*.py", paths) == ["src/a.py", "tests/test_a.py"]
    assert select_files("src/*.ts", paths) == ["src/b.ts"]
    assert render_command("ruff check {files}", ["a b.py", "c.py"]) == "ruff check 'a b.py' c.py"
    assert render_command("tsc --noEmit", ["a.ts"]) == "tsc --noEmit a.ts"


def test_parse_tool_output_extracts_locations() -> None:
    out = "src/a.py:3:5: E999 SyntaxError: bad\nsrc/b.py:10: F821 undefined name 'x'\nFound 2 errors\n"
    d = parse_tool_output(out, source="ruff")
    assert [(x.path, x.line, x.col) for x in d] == [("src/a.py", 3, 5), ("src/b.py", 10, None)]
    assert d[0].source == "ruff" and "E999" in d[0].message


def test_parse_tool_output_falls_back_to_raw_text() -> None:
    d = parse_tool_output("tool exploded\nsecond line", source="lint")
    assert d == [Diagnostic("(lint)", None, None, "tool exploded second line", "lint")]
    assert parse_tool_output("", source="lint") == []
