"""Change planner: validates paths and resolves edits in memory before anything touches disk."""

from chatop.domain.changes import plan_changes
from chatop.domain.reply import Reply, parse_reply

PROTECTED = [".git/**", ".chatop/**", ".env*"]


def reply(body: str) -> Reply:
    return parse_reply(f"<<<CHATOP turn=1>>>\n{body}\n<<<END>>>")


def test_write_and_edit_and_delete() -> None:
    disk = {"src/app.py": "a = 1\nb = 2\n", "old.py": "x\n"}
    r = reply(
        "@@file src/new.py\nn = 1\n@@end\n"
        "@@edit src/app.py\n<<<<<<< SEARCH\nb = 2\n=======\nb = 3\n>>>>>>> REPLACE\n@@end\n"
        "@@delete old.py"
    )
    changes, errors = plan_changes(r, disk.get, PROTECTED)
    assert errors == []
    by = {c.path: c for c in changes}
    assert by["src/new.py"].before is None and by["src/new.py"].after == "n = 1\n"
    assert by["src/app.py"].after == "a = 1\nb = 3\n"
    assert by["old.py"].after is None and by["old.py"].before == "x\n"


def test_edit_after_write_in_same_reply_uses_new_content() -> None:
    r = reply("@@file a.py\nv = 1\n@@end\n@@edit a.py\n<<<<<<< SEARCH\nv = 1\n=======\nv = 2\n>>>>>>> REPLACE\n@@end")
    changes, errors = plan_changes(r, {}.get, PROTECTED)
    assert errors == [] and changes[0].after == "v = 2\n"


def test_search_not_found_and_ambiguous() -> None:
    disk = {"a.py": "x = 1\nx = 1\n"}
    r = reply(
        "@@edit a.py\n<<<<<<< SEARCH\nx = 1\n=======\ny\n>>>>>>> REPLACE\n@@end\n"
        "@@edit b.py\n<<<<<<< SEARCH\nz\n=======\ny\n>>>>>>> REPLACE\n@@end"
    )
    _, errors = plan_changes(r, disk.get, PROTECTED)
    assert any("ambiguous" in e and "a.py" in e for e in errors)
    assert any("does not exist" in e and "b.py" in e for e in errors)


def test_search_whitespace_tolerant_fallback() -> None:
    disk = {"a.py": "def f():\n    return 1   \n"}
    r = reply("@@edit a.py\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n@@end")
    changes, errors = plan_changes(r, disk.get, PROTECTED)
    assert errors == [] and changes[0].after == "def f():\n    return 2\n"


def test_path_escape_and_protected_rejected() -> None:
    r = reply(
        "@@file ../evil.py\nx\n@@end\n@@file /etc/passwd\nx\n@@end\n"
        "@@file .chatop/state.json\n{}\n@@end\n@@file .env.local\nK=1\n@@end"
    )
    changes, errors = plan_changes(r, {}.get, PROTECTED)
    assert changes == []
    assert len(errors) == 4


def test_roles_carried() -> None:
    r = reply("@@test tests/test_a.py\nt\n@@end\n@@doc docs/X.md\nd\n@@end\n@@file src/a.py\nc\n@@end")
    changes, _ = plan_changes(r, {}.get, PROTECTED)
    assert {c.path: c.role for c in changes} == {
        "tests/test_a.py": "test",
        "docs/X.md": "doc",
        "src/a.py": "code",
    }
