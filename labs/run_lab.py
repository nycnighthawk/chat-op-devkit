"""Replay a lab offline with reference LLM replies, or print its steps to follow with a real LLM.

    python labs/run_lab.py new-project --workdir /tmp/lab1          # offline replay (verifies the toolchain)
    python labs/run_lab.py new-project --workdir /tmp/lab1 --show   # just print the steps

steps.txt grammar (one per line, '#' comments):
    chatop <args...>          run a chatop CLI command
    reply <file>              "the LLM answered": apply replies/<file> (@TURN@ is replaced with the current turn)
    seed <dir> <message>      copy labs/seeds/<dir> into the workdir and commit it with <message> (\\n allowed)
    expect key=value ...      assert on `chatop status --json` (phase, status, track, turn)
    expect-file <path>        assert that the file exists in the workdir
    run-lab <name>            replay another lab first, in the same workdir (prerequisite)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

LABS = Path(__file__).resolve().parent


def chatop(workdir: Path, *args: str) -> tuple[int, str]:
    from chatop.ui.cli import main

    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["-C", str(workdir), *args])
    return code, buf.getvalue()


def git(workdir: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workdir, check=True, capture_output=True)


def run(lab: str, workdir: Path, verbose: bool = True, record: list[dict[str, object]] | None = None) -> None:
    """Replay a lab. If `record` is given, append one transcript entry per step (used by the docs build)."""
    os.environ["CHATOP_CLIPBOARD"] = "file"  # deterministic, headless
    lab_dir = LABS / lab
    workdir.mkdir(parents=True, exist_ok=True)
    if not (workdir / ".git").exists():
        git(workdir, "init", "-q", "-b", "main")
        git(workdir, "config", "user.email", "lab@example.com")
        git(workdir, "config", "user.name", "Lab")
        git(workdir, "config", "commit.gpgsign", "false")
    for n, raw in enumerate((lab_dir / "steps.txt").read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        verb, *rest = shlex.split(line)
        if verbose:
            print(f"\n$ {line}")
        entry: dict[str, object] = {"line": line, "verb": verb, "comment": _comment_before(lab_dir, n - 1)}
        if record is not None:
            record.append(entry)
        if verb == "chatop":
            code, out = chatop(workdir, *rest)
            entry["output"] = out.replace(str(workdir), "~/project")
            if verbose:
                print(out.rstrip())
            if code != 0:
                raise SystemExit(f"step {n} failed (exit {code}): {line}")
        elif verb == "reply":
            status = json.loads(chatop(workdir, "status", "--json")[1])
            text = (lab_dir / "replies" / rest[0]).read_text().replace("@TURN@", str(status["turn"]))
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
                fh.write(text)
            entry["turn"] = status["turn"]
            entry["reply"] = text
            packet = workdir / ".chatop" / "packets" / f"turn-{status['turn']:04d}.md"
            entry["packet"] = packet.read_text() if packet.exists() else ""
            code, out = chatop(workdir, "apply", fh.name)
            entry["output"] = out.replace(str(workdir), "~/project")
            if verbose:
                print(out.rstrip())
            if code != 0:
                raise SystemExit(f"step {n}: reply {rest[0]} was rejected")
        elif verb == "seed":
            shutil.copytree(LABS / "seeds" / rest[0], workdir, dirs_exist_ok=True)
            git(workdir, "add", "-A")
            git(workdir, "commit", "-q", "-m", rest[1].replace("\\n", "\n"))
        elif verb == "expect":
            status = json.loads(chatop(workdir, "status", "--json")[1])
            for kv in rest:
                k, v = kv.split("=", 1)
                if str(status[k]) != v:
                    raise SystemExit(f"step {n}: expected {k}={v}, got {status[k]}")
        elif verb == "run-lab":
            run(rest[0], workdir, verbose=False, record=None)
            if verbose:
                print(f"(prerequisite lab '{rest[0]}' replayed)")
        elif verb == "expect-file":
            if not (workdir / rest[0]).exists():
                raise SystemExit(f"step {n}: expected file {rest[0]}")
        else:
            raise SystemExit(f"step {n}: unknown verb {verb}")
    if verbose:
        print(f"\nLab '{lab}' completed in {workdir}")


def _comment_before(lab_dir: Path, index: int) -> str:
    """The '#' comment lines directly above step line `index` (0-based): shown as narration in the docs."""
    lines = (lab_dir / "steps.txt").read_text().splitlines()
    i = index
    notes: list[str] = []
    while i > 0 and lines[i - 1].strip().startswith("#"):
        i -= 1
        notes.insert(0, lines[i].strip().lstrip("#").strip())
    return " ".join(notes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab", choices=sorted(p.name for p in LABS.iterdir() if (p / "steps.txt").exists()))
    ap.add_argument("--workdir", type=Path, default=None)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.show:
        print((LABS / a.lab / "steps.txt").read_text())
        return
    run(a.lab, a.workdir or Path(tempfile.mkdtemp(prefix=f"chatop-{a.lab}-")))


if __name__ == "__main__":
    sys.path.insert(0, str(LABS.parent / "src"))
    main()
