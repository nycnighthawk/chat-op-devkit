"""Session facade: the use cases, end to end, with fake index/clipboard and real git + pytest."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import PYTEST

from chatop.app.session import SessionError
from chatop.domain.models import Phase, Status, Track


def env(turn: int, body: str) -> str:
    return f"Sure! Here you go:\n````chatop\n<<<CHATOP turn={turn}>>>\n{body}\n<<<END>>>\n````\n"


# ---------------------------------------------------------------- use case 1: new project


def test_new_project_idea_to_slices_to_done(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = make_session()
    s.init(track=Track.NEW, idea="A tiny calculator library")
    s.set_check("test", PYTEST)
    assert s.state.phase == Phase.IDEA
    assert (tmp_path / "docs/IDEA.md").read_text().startswith("# Idea")

    p = s.build_packet()
    assert p.turn == 1 and "A tiny calculator library" in p.text and clip.text == p.text
    assert "<<<CHATOP turn=1>>>" in p.text  # contract shows the exact header to echo

    r = s.apply(
        env(
            1,
            "@@summary restated\n@@doc docs/REFINEMENT.md\n# R\n@@end\n"
            "@@ask q1\nWhich ops?\n- [x] add\n- [ ] sub\n@@end",
        )
    )
    assert r.ok and s.state.phase == Phase.REFINE and s.state.status == Status.AWAITING_ANSWERS
    with pytest.raises(SessionError):
        s.build_packet()
    s.accept_recommended()
    p = s.build_packet()
    assert "Which ops?" in p.text and "add" in p.text and p.turn == 2

    s.apply(env(2, "@@doc docs/REFINEMENT.md\n# R final\n@@end\n@@advance"))
    assert s.state.phase == Phase.PRD
    s.build_packet()
    s.apply(env(3, "@@doc docs/PRD.md\n# PRD\nAC1 add works\n@@end\n@@advance"))
    assert s.state.status == Status.AWAITING_APPROVAL
    s.approve()
    assert s.state.phase == Phase.SPEC
    s.build_packet()
    s.apply(env(4, "@@doc docs/SPEC.md\n# SPEC\n@@end\n@@decision pure functions\n@@advance"))
    s.approve()
    s.build_packet()
    slices = '[{"id":"S1","title":"add","acceptance":["AC1"],"touches":["calc.py"]}]'
    s.apply(env(5, f"@@doc docs/PLAN.md\n# Plan\n@@end\n@@slices\n{slices}\n@@end\n@@advance"))
    s.approve()
    assert s.state.phase == Phase.SLICE and s.state.current_slice == "S1"

    p = s.build_packet()
    assert "S1" in p.text and "calc.py" in p.text
    r = s.apply(
        env(
            6,
            "@@summary add()\n"
            "@@test test_calc.py\nfrom calc import add\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n@@end\n"
            "@@file calc.py\ndef add(a: int, b: int) -> int:\n    return a + b\n@@end",
        )
    )
    assert r.ok, r.errors
    assert r.red_ok is True and all(c.code == 0 for c in r.checks)
    assert s.state.phase == Phase.DONE and s.state.status == Status.DONE
    assert "S1" in s.vcs_log()
    assert "pure functions" in s.state.decisions


def test_slice_failure_feeds_evidence_into_next_packet(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    _jump_to_slice(s)
    s.build_packet()
    r = s.apply(
        env(
            s.state.turn,
            "@@test test_m.py\nfrom m import f\n\ndef test_f():\n    assert f() == 2\n@@end\n"
            "@@file m.py\ndef f():\n    return 1\n@@end",
        )
    )
    assert r.ok and not r.slice_done
    # auto_next: the follow-up packet (with the failure evidence) is already built and on the clipboard
    assert r.next_packet is not None and r.next_packet.turn == 2
    assert s.state.status == Status.AWAITING_REPLY and s.state.slice("S1").attempts == 1  # type: ignore[union-attr]
    p = s.build_packet()
    assert p.turn == 2  # rebuilding is idempotent
    assert "assert 1 == 2" in p.text or "AssertionError" in p.text


def test_red_not_proven_blocks_completion(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    _jump_to_slice(s)
    (s.ws.root / "m.py").write_text("def f():\n    return 2\n")
    s.build_packet()
    r = s.apply(
        env(
            s.state.turn,
            "@@test test_m.py\nfrom m import f\n\ndef test_f():\n    assert f() == 2\n@@end\n"
            "@@file m.py\ndef f():\n    return 2  # same\n@@end",
        )
    )
    assert r.red_ok is False and not r.slice_done
    assert "RED not proven" in s.state.evidence


def test_bad_reply_produces_repair_prompt(make_session) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    r = s.apply(env(1, "@@edit nope.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n@@end"))
    assert not r.ok and r.repair_prompt and clip.text == r.repair_prompt
    assert "turn=1" in r.repair_prompt and s.state.status == Status.AWAITING_REPLY


def test_stale_turn_rejected(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    r = s.apply(env(9, "@@summary hi"))
    assert not r.ok and "turn" in r.errors[0]


def test_needs_resolved_in_next_packet(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from chatop.ports import SymbolHit

    s, _, index = make_session()
    (tmp_path / "lib.py").write_text("x = 0\n\ndef helper():\n    return 42\n")
    index.hits["helper"] = [SymbolHit("helper", "function", "lib.py", 3, 4)]
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    s.apply(env(1, "@@need symbol helper\n@@need file lib.py"))
    p = s.build_packet()
    assert "def helper():" in p.text and "lib.py:3-4" in p.text


def test_undo_restores_files_and_state(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    s.apply(env(1, "@@doc docs/REFINEMENT.md\n# R\n@@end"))
    assert (tmp_path / "docs/REFINEMENT.md").exists()
    restored = s.undo()
    assert "docs/REFINEMENT.md" in restored and not (tmp_path / "docs/REFINEMENT.md").exists()
    assert s.state.phase == Phase.IDEA and s.state.status == Status.AWAITING_REPLY


# ---------------------------------------------------------------- use case 2: continue with a feature


def test_feature_on_existing_chatop_project(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    _jump_to_slice(s)
    s.state.slices[0].status = "done"
    from chatop.domain.workflow import complete_slice

    s._save(complete_slice(s.state))
    assert s.state.phase == Phase.DONE
    s.feature("Add subtraction")
    assert (s.state.track, s.state.phase) == (Track.CONTINUE, Phase.FEATURE)
    p = s.build_packet()
    assert "Add subtraction" in p.text and "S1" in p.text  # prior slices visible
    s.apply(env(p.turn, "@@doc docs/FEATURE.md\n# Sub\n@@end"))
    assert s.state.phase == Phase.REFINE


# ---------------------------------------------------------------- use cases 3+4: unknown projects


def test_adopt_unknown_project_recon(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("print('hi')\n")
    (tmp_path / "AGENTS.md").write_text("Use tabs. Run make test.\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    s, _, index = make_session()
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"], cwd=tmp_path, check=True
    )
    assert s.detect_track() == Track.AUDIT  # code exists, no tests -> safest default
    s.init(track=Track.ADOPT)
    assert index.synced == 1
    p = s.build_packet()
    assert "Use tabs" in p.text and "pyproject.toml" in p.text and "claude" in p.text.lower()
    s.apply(env(1, "@@doc docs/AS-BUILT.md\n# As built\n@@end"))
    assert s.state.phase == Phase.DONE


def test_audit_runs_checks_in_packet(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("print('hi')\n")
    s, _, _ = make_session()
    s.init(track=Track.AUDIT)
    s.set_check("test", "exit 3")
    s.build_packet()
    s.apply(env(1, "@@doc docs/AS-BUILT.md\n# AB\n@@end"))
    assert s.state.phase == Phase.AUDIT
    p = s.build_packet()
    assert "exit code 3" in p.text and "Risk register" in p.text


def _jump_to_slice(s) -> None:  # type: ignore[no-untyped-def]
    from chatop.domain.models import Slice

    s.init(track=Track.NEW, idea="x")
    s.set_check("test", PYTEST)
    st = s.state
    st.phase, st.status = Phase.SLICE, Status.READY
    st.slices = [Slice(id="S1", title="f", touches=["m.py"], status="active")]
    st.current_slice = "S1"
    s._save(st)


def test_proposed_checks_take_effect_only_on_approval(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    st = s.state
    st.phase = Phase.SPEC
    s._save(st)
    s.build_packet()
    s.apply(env(1, "@@doc docs/SPEC.md\n# S\n@@end\n@@check test python -m pytest -q\n@@advance"))
    assert "test" not in s.config.checks and s.state.proposed_checks == {"test": "python -m pytest -q"}
    s.approve()
    assert s.config.checks["test"] == "python -m pytest -q" and s.state.proposed_checks == {}


def test_reject_keeps_phase_and_sends_note(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    st = s.state
    st.phase = Phase.PRD
    s._save(st)
    s.build_packet()
    s.apply(env(1, "@@doc docs/PRD.md\n# P\n@@end\n@@advance"))
    s.reject("Add an offline mode story")
    p = s.build_packet()
    assert s.state.phase == Phase.PRD and "offline mode" in p.text


def test_watch_tick_applies_new_envelope(make_session) -> None:  # type: ignore[no-untyped-def]
    s, clip, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    last, res = s.watch_tick(None)
    assert res is None  # clipboard still holds our own packet (it contains no envelope header line)
    clip.text = env(1, "@@doc docs/REFINEMENT.md\n# R\n@@end")
    last, res = s.watch_tick(last)
    assert res is not None and res.ok and s.state.phase == Phase.REFINE
    assert clip.text is not None and "turn 2" in clip.text  # next packet auto-copied


def test_recon_stays_until_needs_served(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("def main():\n    pass\n")
    s, _, _ = make_session()
    s.init(track=Track.ADOPT)
    s.build_packet()
    s.apply(env(1, "@@doc docs/AS-BUILT.md\n# draft\n@@end\n@@need file app.py"))
    assert s.state.phase == Phase.RECON
    p = s.build_packet()
    assert "def main():" in p.text


def test_protected_paths_rejected(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    s.init(track=Track.NEW, idea="x")
    s.build_packet()
    r = s.apply(env(1, '@@file .chatop/config.toml\n[checks]\ntest = "rm -rf /"\n@@end'))
    assert not r.ok and any("protected" in e for e in r.errors)


def test_code_only_fix_allowed_after_red_was_proven(make_session) -> None:  # type: ignore[no-untyped-def]
    s, _, _ = make_session()
    _jump_to_slice(s)
    s.build_packet()
    r1 = s.apply(
        env(
            s.state.turn,
            "@@test test_m.py\nfrom m import f\n\ndef test_f():\n    assert f() == 2\n@@end\n"
            "@@file m.py\ndef f():\n    return 1\n@@end",
        )
    )
    assert r1.red_ok and not r1.slice_done
    r2 = s.apply(
        env(s.state.turn, "@@edit m.py\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n@@end")
    )
    assert r2.ok and r2.slice_done, s.state.evidence


def test_accepting_checks_during_audit_refreshes_evidence(make_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app.py").write_text("print('hi')\n")
    s, _, _ = make_session()
    s.init(track=Track.AUDIT)
    s.build_packet()
    s.apply(env(1, "@@doc docs/AS-BUILT.md\n# AB\n@@end\n@@check test exit 4"))
    assert s.state.phase == Phase.AUDIT and "exit code 4" not in s.state.evidence
    s.accept_checks()
    assert "exit code 4" in s.build_packet().text
