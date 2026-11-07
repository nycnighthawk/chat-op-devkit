"""Every lab replays end to end with its reference replies (real git, real pytest/mypy, file clipboard)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _runner():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("run_lab", ROOT / "labs" / "run_lab.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("lab", ["new-project", "continue-feature", "adopt", "audit"])
def test_lab_replays(lab: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + ":" + __import__("os").environ["PATH"])
    _runner().run(lab, tmp_path / lab, verbose=False)
