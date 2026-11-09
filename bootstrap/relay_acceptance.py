#!/usr/bin/env python3
"""Black-box acceptance for the stage-0 kernel (relay.py). Whoever wrote the kernel (you, a chat, or this repo), it
must pass these before you rely on it:   python bootstrap/relay_acceptance.py [path/to/relay.py]

Each check runs relay.py as a subprocess in a throw-away git repository. Needs: python3.11+, git, pytest."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

RELAY = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("relay.py")).resolve()
PY = sys.executable
RESULTS: list[tuple[str, bool, str]] = []


def new_repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix="relay-accept-"))
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "a@b.c"],
        ["config", "user.name", "A"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *cmd], cwd=d, check=True, capture_output=True)
    (d / "README.md").write_text("# demo\n")
    (d / "pyproject.toml").write_text("[tool.pytest.ini_options]\npythonpath = ['src']\n")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True, capture_output=True)
    return d


def relay(repo: Path, *args: str, reply: str | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, "RELAY_TEST": f"{PY} -m pytest -q -p no:cacheprovider", **env}
    if reply is not None:
        (repo / "reply.txt").write_text(reply)
        args = (args[0], str(repo / "reply.txt"), *args[1:])
    return subprocess.run([PY, str(RELAY), *args], cwd=repo, capture_output=True, text=True, env=e)


def head(repo: Path) -> str:
    return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout.strip()


def tree_clean(repo: Path) -> bool:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    return all(ln[3:] in ("reply.txt", ".gitignore", ".relay/") for ln in out.splitlines())


def env_block(chat: str, turn: int, body: str) -> str:
    return f"````chatop\n<<<CHATOP chat={chat} turn={turn}>>>\n{body}\n<<<END>>>\n````\n"


GOOD = env_block(
    "c1",
    1,
    """@@summary add add()
@@test tests/test_calc.py
from calc import add


def test_add() -> None:
    assert add(2, 3) == 5
@@end
@@file src/calc.py
def add(a: int, b: int) -> int:
    return a + b
@@end""",
)


def check(name: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def deco(fn: Callable[[], None]) -> Callable[[], None]:
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as exc:
            RESULTS.append((name, False, str(exc)))
        return fn

    return deco


@check("tests first (red), then code (green), then an automatic commit")
def _() -> None:
    r = new_repo()
    p = relay(r, "apply", reply=GOOD)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "red proven" in p.stdout, p.stdout
    assert head(r) == "add add()", head(r)
    assert (r / "src/calc.py").exists() and (r / "tests/test_calc.py").exists()


@check("every problem in every file is reported at once, and nothing is changed")
def _() -> None:
    r = new_repo()
    (r / "a.py").write_text("x = 1\n")
    reply = env_block(
        "c1",
        1,
        """@@summary broken
@@file b.py
def f(:
    pass
@@end
@@file c.json
{"a": 1,}
@@end
@@edit a.py
<<<<<<< SEARCH
not there
=======
y = 2
>>>>>>> REPLACE
@@end""",
    )
    p = relay(r, "apply", reply=reply)
    assert p.returncode == 1, p.stdout
    assert "3 problem(s)" in p.stdout, p.stdout
    assert "b.py" in p.stdout and "c.json" in p.stdout and "SEARCH text not found" in p.stdout, p.stdout
    assert not (r / "b.py").exists() and (r / "a.py").read_text() == "x = 1\n"


@check("unsafe paths, truncated replies and pasted packets are rejected")
def _() -> None:
    r = new_repo()
    p = relay(r, "apply", reply=env_block("c1", 1, "@@file ../evil.py\nx = 1\n@@end"))
    assert p.returncode == 1 and "escapes the project root" in p.stdout, p.stdout
    p = relay(r, "apply", reply="<<<CHATOP chat=c1 turn=1>>>\n@@file a.py\nx = 1\n@@end\n")
    assert p.returncode == 1 and "truncated" in p.stdout, p.stdout
    p = relay(r, "apply", reply="# CHATOP PACKET · relay kernel · chat c1 · turn 1\nstuff")
    assert p.returncode == 1 and "PACKET" in p.stdout, p.stdout


@check("tests that already pass prove nothing: RED not proven, and the tree is restored")
def _() -> None:
    r = new_repo()
    (r / "src").mkdir()
    (r / "src/calc.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    reply = env_block(
        "c1",
        1,
        """@@summary weak test
@@test tests/test_calc.py
from calc import add


def test_add() -> None:
    assert add(1, 1) == 2
@@end
@@file src/other.py
x = 1
@@end""",
    )
    p = relay(r, "apply", reply=reply)
    assert p.returncode == 1 and "RED not proven" in p.stdout, p.stdout
    assert not (r / "tests/test_calc.py").exists() and not (r / "src/other.py").exists()


@check("a failing green leaves the files in place with evidence; a code-only fix then commits")
def _() -> None:
    r = new_repo()
    bad = GOOD.replace("return a + b", "return a - b")
    p = relay(r, "apply", reply=bad)
    assert p.returncode == 3 and "CHECKS FAILED" in p.stdout and "assert" in p.stdout, p.stdout
    assert (r / "src/calc.py").exists() and head(r) == "init"
    fix = env_block(
        "c1",
        2,
        """@@summary fix add()
@@edit src/calc.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
@@end""",
    )
    p = relay(r, "apply", reply=fix)
    assert p.returncode == 0 and head(r) == "fix add()", p.stdout + p.stderr


@check("edits survive trailing-whitespace differences; ambiguous edits are rejected")
def _() -> None:
    r = new_repo()
    (r / "m.py").write_text("a = 1   \nb = 2\nb = 2\n")
    ok = env_block("c1", 1, "@@summary e\n@@edit m.py\n<<<<<<< SEARCH\na = 1\n=======\na = 10\n>>>>>>> REPLACE\n@@end")
    assert relay(r, "apply", "--no-commit", reply=ok).returncode == 0
    assert (r / "m.py").read_text().startswith("a = 10\n")
    amb = env_block("c1", 2, "@@summary e\n@@edit m.py\n<<<<<<< SEARCH\nb = 2\n=======\nb = 3\n>>>>>>> REPLACE\n@@end")
    p = relay(r, "apply", reply=amb)
    assert p.returncode == 1 and "ambiguous" in p.stdout, p.stdout


@check("documents are committed without running tests")
def _() -> None:
    r = new_repo()
    p = relay(
        r, "apply", reply=env_block("c1", 1, "@@summary spec\n@@doc docs/SPEC.md\n# Spec\n@@end"), RELAY_TEST="false"
    )
    assert p.returncode == 0 and head(r) == "spec", p.stdout + p.stderr


@check("pack: plan section, spec, touched files, repo tree, evidence, header to echo")
def _() -> None:
    r = new_repo()
    (r / "docs").mkdir()
    (r / "docs/SPEC.md").write_text("# Spec\nbe good\n")
    (r / "docs/PLAN.md").write_text(
        "# Plan\n\n## S1: first\n- touches: src/a.py\n- depends:\n\nDo a.\n\n## S2: second\n- reads: src/a.py\n"
    )
    (r / "src").mkdir()
    (r / "src/a.py").write_text("A = 1\n")
    (r / "ev.txt").write_text("FAILED test_x\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    p = relay(r, "pack", "S1", "--chat", "c4", "--evidence", "ev.txt", "--print")
    assert p.returncode == 0, p.stdout + p.stderr
    for needle in (
        "# CHATOP PACKET",
        "<<<CHATOP chat=c4 turn=1>>>",
        "Do a.",
        "be good",
        "A = 1",
        "src/a.py",
        "FAILED test_x",
    ):
        assert needle in p.stdout, needle
    assert "second" not in p.stdout
    status = relay(r, "status")
    assert "c4" in status.stdout and "WAITING" in status.stdout, status.stdout
    stale = relay(r, "apply", reply=env_block("c4", 9, "@@summary x\n@@file a.txt\nx\n@@end"))
    assert stale.returncode == 1 and "stale paste" in stale.stdout, stale.stdout


@check("undo restores the tree and the history")
def _() -> None:
    r = new_repo()
    assert relay(r, "apply", reply=GOOD).returncode == 0
    p = relay(r, "undo")
    assert p.returncode == 0 and head(r) == "init" and not (r / "src/calc.py").exists(), p.stdout + p.stderr


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, why in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}" + (f"\n      {why[-900:]}" if why else ""))
    bad = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\nkernel {'OK' if not bad else 'NOT OK'}: {len(RESULTS) - bad}/{len(RESULTS)} checks passed ({RELAY})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
