"""The stage-0 kernel must agree with the real planner: same parse, same planned files, same syntax diagnostics."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from chatop.domain import changes as real_changes
from chatop.domain import preflight as real_preflight
from chatop.domain.reply import Edit, Write, parse_reply

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("relay", ROOT / "bootstrap" / "relay.py")
assert spec and spec.loader
relay = importlib.util.module_from_spec(spec)
sys.modules["relay"] = relay
spec.loader.exec_module(relay)

REPLIES = sorted((ROOT / "labs").glob("*/replies/*.md"))


def fill(text: str) -> str:
    return re.sub(r"@(?:CHAT|TURN):[\w-]+@", "c1", text).replace("@TURN@", "1")


def test_corpus_is_not_empty() -> None:
    assert len(REPLIES) > 30


@pytest.mark.parametrize("path", REPLIES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_parse_and_plan_agree_with_the_real_implementation(path: Path) -> None:
    text = fill(path.read_text())
    real, mine = parse_reply(text), relay.parse_reply(text)
    assert (mine.chat, mine.turn, mine.summary) == (real.chat, real.turn, real.summary)
    real_ops = [
        (
            "edit" if isinstance(o, Edit) else "write" if isinstance(o, Write) else "delete",
            o.path,
            getattr(o, "content", None),
            getattr(o, "role", None),
        )
        for o in real.ops
    ]
    my_ops = [
        (o.kind, o.path, o.content if o.kind == "write" else None, o.role if o.kind == "write" else None)
        for o in mine.ops
    ]
    # real stores edits with blocks and no content; compare the shared parts
    assert [(k, p) for k, p, *_ in my_ops] == [(k, p) for k, p, *_ in real_ops]
    assert [x[2:] for x in my_ops if x[0] == "write"] == [x[2:] for x in real_ops if x[0] == "write"]
    assert bool(mine.errors) == bool(real.errors) or any("Unknown directive" in e for e in real.errors)
    # planned files (edits against missing files fail the same way)
    reader = {}.get
    r_changes, r_err = real_changes.plan_changes(real, reader, relay.PROTECTED)
    m_changes, m_err = relay.plan_changes(mine.ops, reader)
    assert sorted((c.path, c.after) for c in m_changes) == sorted((c.path, c.after) for c in r_changes)
    assert len(m_err) == len(r_err)
    # one-shot syntax diagnostics: same files, same lines
    real_diag = real_preflight.check_all({c.path: c.after for c in r_changes})
    assert [d.split(":")[0] for d in relay.preflight(m_changes)] == [d.path for d in real_diag]


EDIT_CASES = [
    ("a = 1\nb = 2\n", "a = 1\n", "a = 9\n"),
    ("a = 1   \nb = 2\n", "a = 1\n", "a = 9\n"),  # trailing whitespace tolerated
    ("x\nx\n", "x\n", "y\n"),  # ambiguous
    ("a = 1\n", "zzz\n", "y\n"),  # missing
]


@pytest.mark.parametrize(("content", "search", "replace"), EDIT_CASES)
def test_edit_resolution_matches(content: str, search: str, replace: str) -> None:
    mine = relay.apply_block(content, search, replace)
    real = real_changes.apply_block(content, search, replace)
    assert mine[0] == real[0]  # same resulting text (None when the edit cannot apply)
    assert bool(mine[1]) == bool(real[1])  # an error message exactly when the real one has one


@pytest.mark.parametrize("path", ["../x", "/abs", ".git/config", ".env", "a/../../b", "ok/file.py", "docs/a.md"])
def test_path_safety_matches(path: str) -> None:
    mine, _ = relay.safe_path(path)
    real, _ = real_changes.safe_path(path, relay.PROTECTED)
    assert mine == real


def test_the_kernel_passes_its_own_black_box_acceptance() -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "bootstrap" / "relay_acceptance.py")], capture_output=True, text=True, timeout=300
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "kernel OK" in run.stdout


# --- accept.py: the generated conformance runner -------------------------------------------------------------


def test_accept_is_up_to_date() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_bootstrap.py"), "--check"])
    assert r.returncode == 0, "run: python scripts/build_bootstrap.py"


def test_accept_passes_all_labs_against_reference_app() -> None:
    chatop = Path(sys.executable).parent / "chatop"
    env = {**os.environ, "CHATOP": str(chatop)}
    r = subprocess.run(
        [sys.executable, str(ROOT / "bootstrap" / "accept.py"), "all"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "5/5 labs passed" in r.stdout


def test_accept_fails_loudly_on_a_broken_app(tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env = {**os.environ, "CHATOP": str(fake)}
    r = subprocess.run(
        [sys.executable, str(ROOT / "bootstrap" / "accept.py"), "lab1"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 1 and "FAIL new-project" in r.stdout


# --- the seed bundle ---------------------------------------------------------------------------------------------


def _git_repo(path: Path) -> None:
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_seed_replies_apply_with_the_kernel_and_the_plan_is_packable(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    relay = ROOT / "bootstrap" / "relay.py"
    for name in ("seed-design", "seed-prompts"):
        r = subprocess.run(
            [sys.executable, str(relay), "apply", str(ROOT / "bootstrap" / "seed" / f"{name}.reply.md")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stdout + r.stderr
    for doc in ("PRD", "DESIGN", "ARCHITECTURE", "DECISIONS", "UX", "BEHAVIOR", "PLAN"):
        assert (tmp_path / "docs" / f"{doc}.md").exists()
    # every prompt except the one that describes the envelope itself travels in the reply; that one is a raw copy
    sent = {p.name for p in (tmp_path / "src" / "chatop" / "prompts").glob("*.md")}
    raw = {p.name for p in (ROOT / "bootstrap" / "seed" / "raw").glob("*.md")}
    assert sent | raw == {p.name for p in (ROOT / "src" / "chatop" / "prompts").glob("*.md")}
    assert (ROOT / "bootstrap" / "seed" / "raw" / "contract.md").read_text() == (
        ROOT / "src" / "chatop" / "prompts" / "contract.md"
    ).read_text()


def test_reference_plan_is_consistent() -> None:
    text = (ROOT / "bootstrap" / "seed" / "PLAN.md").read_text()
    sections = re.findall(r"^## (S\d+): (.+)$", text, re.M)
    ids = [s for s, _ in sections]
    assert ids == [f"S{i}" for i in range(1, 12)]
    deps = {
        sid: [d.strip() for d in m.group(1).split(",") if d.strip() and d.strip() != "none"]
        for sid, m in ((sid, re.search(rf"## {sid}:.*?\n- depends: ([^\n]*)", text, re.S)) for sid in ids)
        if m
    }
    assert all(d in ids and int(d[1:]) < int(sid[1:]) for sid, ds in deps.items() for d in ds)
    # slices that run at the same time must not share a file
    touches = {
        sid: {t.strip() for t in re.search(rf"## {sid}:.*?\n- touches: ([^\n]*)", text, re.S).group(1).split(",")}  # type: ignore[union-attr]
        for sid in ids
    }
    for wave in (["S1", "S4"], ["S2", "S3", "S5"], ["S8", "S9"], ["S10", "S11"]):
        for i, a in enumerate(wave):
            for b in wave[i + 1 :]:
                shared = touches[a] & touches[b]
                assert not shared, f"{a} and {b} share {shared}"
