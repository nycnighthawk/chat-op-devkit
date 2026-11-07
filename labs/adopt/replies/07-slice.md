````chatop
<<<CHATOP turn=@TURN@>>>
@@summary D1: optional due date + overdue()
@@test tests/test_due.py
from datetime import date
from pathlib import Path

from todo import TodoStore


def test_due_persists(tmp_path: Path) -> None:  # AC-1.1
    TodoStore(tmp_path / "t.json").add("pay rent", due="2026-01-01")
    assert TodoStore(tmp_path / "t.json").items[0].due == "2026-01-01"


def test_overdue(tmp_path: Path) -> None:  # AC-1.2
    s = TodoStore(tmp_path / "t.json")
    late = s.add("late", due="2026-01-01")
    s.add("future", due="2026-12-31")
    s.add("undated")
    done = s.add("done-late", due="2025-01-01")
    s.complete(done.id)
    assert [t.id for t in s.overdue(date(2026, 1, 2))] == [late.id]
@@end
@@edit todo.py
<<<<<<< SEARCH
from dataclasses import asdict, dataclass
=======
from dataclasses import asdict, dataclass
from datetime import date
>>>>>>> REPLACE
<<<<<<< SEARCH
    done: bool = False
=======
    done: bool = False
    due: str | None = None  # ISO date YYYY-MM-DD
>>>>>>> REPLACE
<<<<<<< SEARCH
    def add(self, title: str) -> Todo:
        todo = Todo(id=len(self.items) + 1, title=title)
=======
    def add(self, title: str, due: str | None = None) -> Todo:
        todo = Todo(id=len(self.items) + 1, title=title, due=due)
>>>>>>> REPLACE
<<<<<<< SEARCH
    def _save(self) -> None:
=======
    def overdue(self, today: date) -> list[Todo]:
        return [t for t in self.open_items() if t.due is not None and date.fromisoformat(t.due) < today]

    def _save(self) -> None:
>>>>>>> REPLACE
@@end
<<<END>>>
````
