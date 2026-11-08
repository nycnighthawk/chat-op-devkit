"""The standalone mock UI: the real page + fake backend. Built from sources, scenario verified with node."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _builder():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_mock_ui", ROOT / "scripts" / "build_mock_ui.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_mock_ui_is_current() -> None:
    mod = _builder()
    assert mod.OUT.read_text(encoding="utf-8") == mod.build(), "stale: run python scripts/build_mock_ui.py"


def test_mock_ui_embeds_the_real_page_and_the_api_seam() -> None:
    html = _builder().build()
    assert "window.CHATOP_API" in html and "chatop web UI" in html
    assert "Paste ANY chat reply here" in html  # the real page's relay box, not a re-implementation
    assert "http://" not in html.replace("http://www.w3.org", "")  # self-contained: nothing is fetched


def test_every_real_page_endpoint_is_served_by_the_mock_backend() -> None:
    page = (ROOT / "src/chatop/ui/static/index.html").read_text(encoding="utf-8")
    backend = (ROOT / "mock/backend.js").read_text(encoding="utf-8")
    import re

    used = set(re.findall(r'api\("([a-z/]+)"', page))
    served = set(re.findall(r'case "([a-z/]+)"', backend))
    assert used - served == set(), f"mock backend lacks endpoints used by the page: {used - served}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_mock_scenario_runs_under_node() -> None:
    run = subprocess.run(["node", str(ROOT / "mock/scenario.test.js")], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "mock scenario ok" in run.stdout
