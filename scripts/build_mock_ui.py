"""Build docs/chatop-mock-ui.html: the REAL web page + an in-browser fake backend + simulated chat tabs.

    python scripts/build_mock_ui.py          # writes docs/chatop-mock-ui.html
    python scripts/build_mock_ui.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "chatop-mock-ui.html"


def build() -> str:
    page = (ROOT / "src" / "chatop" / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    backend = (ROOT / "mock" / "backend.js").read_text(encoding="utf-8")
    shell = (ROOT / "mock" / "shell.template.html").read_text(encoding="utf-8")
    assert "</script>" not in backend, "backend.js must not contain a closing script tag"
    literal = json.dumps(page).replace("</", "<\\/")  # the page is a JS string inside a <script>
    return shell.replace("/*__MOCK_BACKEND__*/", backend).replace('"__REAL_PAGE__"', literal)


if __name__ == "__main__":
    html = build()
    if "--check" in sys.argv:
        raise SystemExit(0 if OUT.exists() and OUT.read_text(encoding="utf-8") == html else 1)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html):,} bytes)")
