"""The published playbook must embed the CURRENT prompts and docs (rebuild with scripts/build_playbook.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_playbook_embeds_current_sources() -> None:
    html = (ROOT / "docs" / "chatop-playbook.html").read_text()
    m = re.search(r"const DATA = (\{.*?\});\nconst \$", html, re.S)
    assert m, "DATA payload missing"
    data = json.loads(m.group(1).replace("<\\/", "</"))
    for name, text in data["prompts"].items():
        assert text == (ROOT / "src/chatop/prompts" / f"{name}.md").read_text(), f"stale prompt {name}: rebuild"
    for name, text in data["docs"].items():
        assert text == (ROOT / "docs" / name).read_text(), f"stale doc {name}: rebuild"
    assert set(data["labs"]) == {"new-project", "continue-feature", "adopt", "audit", "parallel-relay"}
    mock = (ROOT / "docs" / "chatop-mock-ui.html").read_text()
    assert data["mock"] == mock, "stale mock inside the playbook: rebuild"
