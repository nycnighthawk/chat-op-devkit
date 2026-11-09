"""Preflight inside Session.apply: all generated files linted in one shot; any problem rejects atomically."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from tests.conftest import PYTEST

from chatop.domain.models import Phase, Slice, Status, Track


def env(turn: int, body: str) -> str:
    return f"<<<CHATOP turn={turn}>>>\n{body}\n<<<END>>>\n"


def to_slice(s) -> None:  # type: ignore[no-untyped-def]
    s.init(track=Track.NEW, idea="x")
    s.set_check("test", PYTEST)
    st = s.state
    st.phase, st.status = Phase.SLICE, Status.READY
    st.slices = [Slice(id="S1", title="f", touches=["m.py"], status="active")]
    st.current_slice = "S1"
    s._save(st)
    s.build_packet()


def test_every_syntax_error_in_every_file_reported_in_one_rejection(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = make_session()
    to_slice(s)
    body = (
        "@@test test_a.py\ndef test_a(:\n    pass\n@@end\n"
        "@@file m.py\ndef f():\nreturn 1\n@@end\n"
        "@@file cfg.json\n{oops\n@@end\n"
        "@@file fine.py\nx = 1\n@@end"
    )
    r = s.apply(env(s.state.turn, body))
    assert not r.ok
    joined = "\n".join(r.errors)
    for path in ("test_a.py", "m.py", "cfg.json"):
        assert path in joined, joined
    assert "fine.py" not in joined
    assert clip.text is not None and "test_a.py" in clip.text and "m.py" in clip.text  # one repair prompt
    assert not (tmp_path / "m.py").exists() and not (tmp_path / "test_a.py").exists()  # nothing written
    assert s.state.status == Status.AWAITING_REPLY and s.state.slices[0].attempts == 0


def test_syntax_errors_reported_together_with_edit_mismatches(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    to_slice(s)
    body = "@@file m.py\ndef f(:\n@@end\n@@edit missing.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n@@end"
    r = s.apply(env(s.state.turn, body))
    assert not r.ok and len(r.errors) == 2


LINTER = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
    "import sys\n"
    "bad=[f for f in sys.argv[1:] if 'bad' in f]\n"
    "[print(f + ':2:1: E501 external lint says no') for f in bad]\n"
    "sys.exit(1 if bad else 0)"
)


def test_external_linter_runs_once_over_all_files_and_rolls_back(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    to_slice(s)
    s.config.preflight = {"*.py": LINTER}
    s.ws.save_config(s.config)
    body = "@@file bad_one.py\nx = 1\n@@end\n@@file bad_two.py\ny = 2\n@@end\n@@file good.py\nz = 3\n@@end"
    r = s.apply(env(s.state.turn, body))
    assert not r.ok
    assert sum("external lint says no" in e for e in r.errors) == 2  # both files in one linter run
    assert not any((tmp_path / f).exists() for f in ("bad_one.py", "bad_two.py", "good.py"))  # rolled back


def test_external_linter_passing_lets_the_slice_proceed(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    to_slice(s)
    s.config.preflight = {"*.py": LINTER}
    body = (
        "@@test test_m.py\nfrom m import f\n\ndef test_f():\n    assert f() == 1\n@@end\n"
        "@@file m.py\ndef f():\n    return 1\n@@end"
    )
    r = s.apply(env(s.state.turn, body))
    assert r.ok and r.red_ok is True and r.slice_done
