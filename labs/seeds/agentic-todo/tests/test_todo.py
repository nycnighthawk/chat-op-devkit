from pathlib import Path

from todo import TodoStore


def test_add_complete_persist(tmp_path: Path) -> None:
    store = TodoStore(tmp_path / "t.json")
    a = store.add("write docs")
    store.add("ship")
    store.complete(a.id)
    again = TodoStore(tmp_path / "t.json")
    assert [t.title for t in again.open_items()] == ["ship"]
