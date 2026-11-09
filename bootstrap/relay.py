#!/usr/bin/env python3
"""relay: the stage-0 kernel. One file, standard library only (Python 3.11+, macOS or Linux, git).

It is the smallest tool that makes a chat-only relay safe: it builds a packet for a chat and applies the chat's
reply (the CHATOP envelope) with every problem reported at once, a red/green TDD check and an automatic commit.

  relay.py pack S2 [--chat c2] [--evidence FILE] [--cg "callers apply"] [--read PATH] [--print]
  relay.py pack --task "do X"     (a packet without a plan)
  relay.py apply [FILE|-]         (default: the clipboard)  [--no-red] [--no-commit]
  relay.py undo                   (undo the last apply)
  relay.py status                 (which chats owe you a reply)

Settings (environment): RELAY_TEST (default: <python> -m pytest -q), RELAY_CHECKS (shell commands separated by ';',
e.g. "ruff check src tests; mypy"), CODEGRAPH (default: codegraph).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

CONTRACT = """Your reply MUST contain exactly this envelope (copy the first line verbatim):

````chatop
<<<CHATOP chat=$CHAT turn=$TURN>>>
@@summary <one line: what this reply does>
...directives...
<<<END>>>
````

| Directive | Meaning |
|---|---|
| `@@test <path>` ... `@@end` | create/overwrite a **test** file. Applied and run first (the red step of TDD) |
| `@@file <path>` ... `@@end` | create/overwrite a whole file |
| `@@doc <path>` ... `@@end` | create/overwrite a document |
| `@@edit <path>` ... `@@end` | one or more SEARCH/REPLACE blocks (below) |
| `@@delete <path>` | delete a file |
| `@@decision <text>` | a durable decision (kept in the commit message) |

SEARCH/REPLACE syntax (SEARCH must match the current file exactly once; copy it verbatim from this packet):

```
@@edit src/pkg/module.py
<<<<<<< SEARCH
existing lines
=======
new lines
>>>>>>> REPLACE
@@end
```

Rules: paths are relative to the repo root. File content is literal (no line numbers, no extra indentation).
Write the tests first and complete: every test the task needs, in one reply, together with the code that makes them
pass. Run your own mental linter: every file must be syntactically valid. Use @@edit only for files you have seen.
If you are near your output limit, finish fewer files cleanly and still end with <<<END>>>. A cut-off reply is rejected.
"""

START_RE = re.compile(r"^<<<CHATOP((?:\s+[a-z]+=[\w-]+)*)\s*>>>\s*$")
ATTR_RE = re.compile(r"([a-z]+)=([\w-]+)")
END_MARK = "<<<END>>>"
PACKET_MARK = "# CHATOP PACKET"
BLOCKS = {"file", "test", "doc", "edit", "ask", "slices"}
INLINE = {"summary", "delete", "decision", "need", "check", "run", "advance"}
PROTECTED = [".git/**", ".git", ".relay/**", ".codegraph/**", ".venv/**", ".env", ".env.*", "**/*.pem", "**/id_rsa*"]
TEST_PATTERNS = (
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.(py|go)$"),
    re.compile(r"\.(test|spec)\.[jt]sx?$"),
)


# ------------------------------------------------------------------------------------------------ parsing
@dataclass
class Op:
    kind: str  # write | edit | delete
    path: str
    content: str = ""
    role: str = "code"
    blocks: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Reply:
    chat: str | None = None
    turn: int | None = None
    summary: str = ""
    decisions: list[str] = field(default_factory=list)
    ops: list[Op] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def infer_role(path: str) -> str:
    if path.startswith("docs/") or path.endswith(".md"):
        return "doc"
    return "test" if any(p.search(path) for p in TEST_PATTERNS) else "code"


def is_packet(text: str) -> bool:
    return text.lstrip().startswith(PACKET_MARK) or f"\n{PACKET_MARK}" in text[:2000]


def parse_edit_blocks(body: list[str]) -> list[tuple[str, str]] | None:
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(body):
        if not body[i].strip():
            i += 1
            continue
        if not body[i].startswith("<<<<<<< SEARCH"):
            return None
        try:
            mid = next(k for k in range(i + 1, len(body)) if body[k].rstrip() == "=======")
            end = next(k for k in range(mid + 1, len(body)) if body[k].startswith(">>>>>>> REPLACE"))
        except StopIteration:
            return None
        blocks.append(("".join(x + "\n" for x in body[i + 1 : mid]), "".join(x + "\n" for x in body[mid + 1 : end])))
        i = end + 1
    return blocks or None


def parse_reply(text: str) -> Reply:
    reply = Reply()
    if is_packet(text):
        reply.errors.append("This is a PACKET, not a reply. Paste it into the chat, then copy the chat's answer.")
        return reply
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if START_RE.match(ln.strip())), None)
    if start is None:
        reply.errors.append("No <<<CHATOP ...>>> block found. Copy the whole reply, or ask the chat to re-emit it.")
        return reply
    attrs = dict(ATTR_RE.findall(START_RE.match(lines[start].strip()).group(1)))  # type: ignore[union-attr]
    reply.chat = attrs.get("chat")
    reply.turn = int(attrs["turn"]) if attrs.get("turn", "").isdigit() else None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == END_MARK), None)
    if end is None:
        reply.errors.append("Reply looks truncated (missing <<<END>>>). Ask the chat: 'continue the CHATOP block'.")
        end = len(lines)
    i = start + 1
    while i < end:
        line = lines[i]
        if not line.startswith("@@"):
            i += 1
            continue
        head, _, arg = line[2:].partition(" ")
        name, arg = head.strip(), arg.strip()
        if name in BLOCKS:
            j = next((k for k in range(i + 1, end) if lines[k].rstrip() == "@@end"), None)
            if j is None:
                reply.errors.append(f"@@{name} {arg}: block not closed with @@end")
                break
            body = lines[i + 1 : j]
            content = "\n".join(body) + "\n" if body else ""
            if name in ("file", "test", "doc"):
                if not arg:
                    reply.errors.append(f"@@{name} needs a path")
                else:
                    role = "test" if name == "test" else "doc" if name == "doc" else infer_role(arg)
                    reply.ops.append(Op("write", arg, content, role))
            elif name == "edit":
                blocks = parse_edit_blocks(body)
                if blocks is None:
                    reply.errors.append(f"@@edit {arg}: malformed SEARCH/REPLACE block")
                else:
                    reply.ops.append(Op("edit", arg, blocks=blocks))
            i = j + 1
            continue
        if name == "summary":
            reply.summary = arg
        elif name == "delete":
            reply.ops.append(Op("delete", arg))
        elif name == "decision":
            reply.decisions.append(arg)
        elif name not in INLINE and name != "end":
            reply.errors.append(f"Unknown directive @@{name}")
        i += 1
    return reply


# ------------------------------------------------------------------------------------------------ planning
def safe_path(path: str) -> tuple[str | None, str | None]:
    p = path.strip().replace("\\", "/")
    if not p or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return None, f"{path}: absolute paths are not allowed"
    norm = posixpath.normpath(p)
    if norm == ".." or norm.startswith("../"):
        return None, f"{path}: path escapes the project root"
    for pat in PROTECTED:
        if fnmatch(norm, pat) or fnmatch(norm + "/", pat):
            return None, f"{path}: protected ({pat})"
    return norm, None


def apply_block(content: str, search: str, replace: str) -> tuple[str | None, str]:
    count = content.count(search)
    if count == 1:
        return content.replace(search, replace, 1), ""
    if count > 1:
        return None, f"ambiguous SEARCH (matches {count} times): include more context lines"
    src, pat = content.split("\n"), search.rstrip("\n").split("\n")
    stripped, want = [x.rstrip() for x in src], [x.rstrip() for x in pat]
    hits = [i for i in range(len(src) - len(pat) + 1) if stripped[i : i + len(pat)] == want]
    if len(hits) == 1:
        i = hits[0]
        rep = replace.rstrip("\n").split("\n") if replace else []
        return "\n".join(src[:i] + rep + src[i + len(pat) :]), ""
    if hits:
        return None, "ambiguous SEARCH (ignoring trailing spaces): include more context lines"
    return None, "SEARCH text not found: re-read the file and resend the edit (or rewrite it with @@file)"


@dataclass
class Change:
    path: str
    before: str | None
    after: str | None
    role: str


def plan_changes(ops: list[Op], read) -> tuple[list[Change], list[str]]:  # type: ignore[no-untyped-def]
    errors: list[str] = []
    original: dict[str, str | None] = {}
    current: dict[str, str | None] = {}
    roles: dict[str, str] = {}
    for op in ops:
        path, err = safe_path(op.path)
        if path is None:
            errors.append(err or op.path)
            continue
        if path not in current:
            original[path] = current[path] = read(path)
        existing = current[path]
        if op.kind == "write":
            current[path], roles[path] = op.content, op.role
        elif op.kind == "delete":
            if existing is None:
                errors.append(f"{path}: cannot delete, file does not exist")
            current[path] = None
        else:
            if existing is None:
                errors.append(f"{path}: cannot edit, file does not exist (use @@file to create it)")
                continue
            content = existing
            for n, (search, replace) in enumerate(op.blocks, 1):
                new, msg = apply_block(content, search, replace)
                if new is None:
                    errors.append(f"{path}: edit block {n}: {msg}")
                    break
                content = new
            current[path] = content
    return [
        Change(p, original[p], current[p], roles.get(p, infer_role(p))) for p in current if original[p] != current[p]
    ], errors


def preflight(changes: list[Change]) -> list[str]:
    """Every syntax problem in every file, in one pass (Python via ast, JSON, TOML)."""
    out: list[str] = []
    for c in sorted(changes, key=lambda c: c.path):
        if c.after is None:
            continue
        suffix = PurePosixPath(c.path).suffix.lower()
        try:
            if suffix == ".py":
                ast.parse(c.after, filename=c.path)
            elif suffix == ".json":
                json.loads(c.after)
            elif suffix == ".toml":
                tomllib.loads(c.after)
        except SyntaxError as exc:
            out.append(f"{c.path}:{exc.lineno or 0}: {type(exc).__name__}: {exc.msg}")
        except (ValueError, tomllib.TOMLDecodeError) as exc:
            out.append(f"{c.path}: invalid {suffix[1:].upper()}: {exc}")
    return out


# ------------------------------------------------------------------------------------------------ environment
def sh(cmd: str, cwd: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        # no .pyc files: two writes inside one second with equal size would otherwise be served stale bytecode
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {cmd}"
    return p.returncode, (p.stdout + p.stderr).strip()


def git(root: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def repo_root() -> Path:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit("relay: run this inside a git repository (git init first)")
    return Path(p.stdout.strip())


def python_for(root: Path) -> str:
    venv = root / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


CLIP_COPY = [["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]]
CLIP_PASTE = [["pbpaste"], ["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]]


def clip_copy(text: str) -> bool:
    for cmd in CLIP_COPY:
        if shutil.which(cmd[0]):
            try:
                return subprocess.run(cmd, input=text, text=True, timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError):
                continue
    return False


def clip_paste() -> str:
    for cmd in CLIP_PASTE:
        if shutil.which(cmd[0]):
            try:
                return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.SubprocessError):
                continue
    return ""


class Mem:
    """.relay/: state.json (turn counter, packets by chat), packets/, replies/, undo/ (git-ignored)."""

    def __init__(self, root: Path) -> None:
        self.dir = root / ".relay"
        self.dir.mkdir(exist_ok=True)
        gi = root / ".gitignore"
        lines = gi.read_text().splitlines() if gi.exists() else []
        if ".relay/" not in lines:
            gi.write_text("\n".join([*lines, ".relay/"]) + "\n")
        self.file = self.dir / "state.json"
        self.state = json.loads(self.file.read_text()) if self.file.exists() else {"turn": 0, "packets": {}, "undo": []}

    def save(self) -> None:
        self.file.write_text(json.dumps(self.state, indent=1))

    def put(self, sub: str, name: str, text: str) -> Path:
        d = self.dir / sub
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return d / name


# ------------------------------------------------------------------------------------------------ pack
def plan_section(root: Path, slice_id: str) -> tuple[str, dict[str, list[str]]]:
    plan = root / "docs" / "PLAN.md"
    if not plan.exists():
        sys.exit("relay: docs/PLAN.md does not exist yet (use --task, or apply a plan first)")
    lines = plan.read_text().splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^##\s+{re.escape(slice_id)}\b(?![\w-])", ln)), None)
    if start is None:
        sys.exit(f"relay: no section '## {slice_id}' in docs/PLAN.md")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = "\n".join(lines[start:end]).strip()
    meta: dict[str, list[str]] = {}
    for ln in lines[start:end]:
        m = re.match(r"^\s*[-*]\s*(depends|touches|reads)\s*:\s*(.*)$", ln, re.I)
        if m:
            meta[m.group(1).lower()] = [x.strip().strip("`") for x in m.group(2).split(",") if x.strip().strip("`")]
    return section, meta


def fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def build_packet(root: Path, mem: Mem, args: argparse.Namespace) -> tuple[str, str, int]:
    meta: dict[str, list[str]] = {}
    if args.slice:
        task, meta = plan_section(root, args.slice)
        label = f"slice {args.slice}"
    elif args.task:
        task, label = args.task, "task"
    else:
        sys.exit("relay: give a slice id (relay.py pack S2) or --task TEXT")
    mem.state["turn"] += 1
    turn, chat = mem.state["turn"], args.chat
    contract = CONTRACT.replace("$CHAT", chat).replace("$TURN", str(turn))
    reads = [*meta.get("reads", []), *meta.get("touches", []), *args.read]
    docs = ["docs/SPEC.md", *[r for r in reads if r.startswith("docs/") and r != "docs/SPEC.md"]]
    files = [r for r in dict.fromkeys(reads) if not r.startswith("docs/") and (root / r).is_file()]
    out = [f"{PACKET_MARK} · relay kernel · chat {chat} · turn {turn} · {label}", "", contract, "## Task", "", task, ""]
    for d in dict.fromkeys(docs):
        if (root / d).is_file():
            body = (root / d).read_text()
            f = fence(body)
            out += [f"## Document: {d}", "", f"{f}md", body.rstrip("\n"), f, ""]
    for p in files:
        body = (root / p).read_text()
        f = fence(body)
        out += [f"## File: {p}", "", f, body.rstrip("\n"), f, ""]
    rc, tracked = git(root, "ls-files")
    out += ["## Repository files", "", "```", tracked if rc == 0 else "(git ls-files failed)", "```", ""]
    cg = os.environ.get("CODEGRAPH", "codegraph")
    for q in args.cg:
        if shutil.which(cg):
            code, res = sh(f"{shlex.quote(cg)} {q}", root, 120)
            out += [
                f"## Code graph: codegraph {q}",
                "",
                "```",
                res[:12000] if res else f"(exit {code}, no output)",
                "```",
                "",
            ]
        else:
            out += [f"## Code graph: codegraph {q}", "", "(codegraph is not installed; skipped)", ""]
    if args.evidence:
        ev = Path(args.evidence).read_text().splitlines()[-200:]
        out += ["## Evidence from the last run: fix this", "", "```", *ev, "```", ""]
    out += [f"Reply now with exactly one CHATOP envelope. First line: <<<CHATOP chat={chat} turn={turn}>>>", ""]
    text = "\n".join(out)
    mem.state["packets"][chat] = {"turn": turn, "label": label, "applied": False}
    return text, chat, turn


def cmd_pack(a: argparse.Namespace) -> int:
    root = repo_root()
    mem = Mem(root)
    text, chat, turn = build_packet(root, mem, a)
    path = mem.put("packets", f"{chat}-turn-{turn:04d}.md", text)
    mem.save()
    tokens = len(text) // 4
    copied = (not a.print) and clip_copy(text)
    if a.print:
        print(text)
    print(
        f"packet for chat {chat}, turn {turn}: ~{tokens:,} tokens; saved {path.relative_to(root)}"
        + ("; copied to the clipboard" if copied else ("" if a.print else "; no clipboard tool found: use --print"))
    )
    if tokens > 100_000:
        print("warning: this packet is large; trim 'reads' in the plan or use --cg for targeted context")
    return 0


# ------------------------------------------------------------------------------------------------ apply
def repair_prompt(chat: str | None, turn: int | None, problems: list[str], title: str) -> str:
    bullet = "\n".join(f"- {p}" for p in problems)
    return (
        f"relay could not accept your reply for chat {chat or '?'} turn {turn or '?'}. {title}\n\n"
        f"Problems:\n{bullet}\n\n"
        "Resend the COMPLETE corrected reply as one block starting with the same `<<<CHATOP ...>>>` header and ending "
        "with `<<<END>>>`, inside a ````chatop fence. For SEARCH mismatches use @@file to rewrite the whole file."
    )


def write_changes(root: Path, changes: list[Change], only: set[str] | None = None) -> None:
    for c in changes:
        if only is not None and c.path not in only:
            continue
        p = root / c.path
        if c.after is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c.after, encoding="utf-8")


def restore(root: Path, changes: list[Change], only: set[str] | None = None) -> None:
    for c in changes:
        if only is not None and c.path not in only:
            continue
        p = root / c.path
        if c.before is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c.before, encoding="utf-8")


def tail(text: str, n: int = 60) -> str:
    return "\n".join(text.splitlines()[-n:])


def reject(chat: str | None, turn: int | None, problems: list[str], title: str = "Nothing was changed.") -> int:
    print(f"REJECTED. {title} ({len(problems)} problem(s), all reported at once):")
    for p in problems:
        print(f"  - {p}")
    repair = repair_prompt(chat, turn, problems, title)
    print(
        "repair prompt "
        + ("copied to the clipboard: paste it into the SAME chat" if clip_copy(repair) else "below:\n" + repair)
    )
    return 1


def cmd_apply(a: argparse.Namespace) -> int:
    root = repo_root()
    mem = Mem(root)
    text = clip_paste() if a.file is None else sys.stdin.read() if a.file == "-" else Path(a.file).read_text()
    if not text.strip():
        sys.exit("relay: nothing to apply (empty clipboard or file)")
    reply = parse_reply(text)
    problems = list(reply.errors)
    known = mem.state["packets"].get(reply.chat or "")
    if reply.chat and known and reply.turn is not None and reply.turn != known["turn"]:
        problems.insert(
            0,
            f"reply is for turn {reply.turn} but the packet sent to {reply.chat} was turn {known['turn']} "
            "(stale paste?)",
        )
    if reply.chat and not known:
        print(f"note: chat {reply.chat} has no packet from this repo; applying anyway")
    changes, perr = plan_changes(reply.ops, lambda p: (root / p).read_text() if (root / p).is_file() else None)
    problems += perr + preflight(changes)
    if problems:
        mem.put("replies", f"rejected-{mem.state['turn']:04d}.md", text)
        return reject(reply.chat, reply.turn, problems)
    if not changes:
        print("nothing to change: the reply did not alter any file")
        return 0
    seq = len(list((mem.dir / "undo").glob("*.json"))) + 1 if (mem.dir / "undo").exists() else 1
    mem.put("replies", f"{reply.chat or 'c0'}-turn-{reply.turn or 0:04d}.md", text)
    tests = [c for c in changes if c.role == "test"]
    code = [c for c in changes if c.role == "code"]
    py = python_for(root)
    test_cmd = os.environ.get("RELAY_TEST", f"{shlex.quote(py)} -m pytest -q")
    checks = [x.strip() for x in os.environ.get("RELAY_CHECKS", "").split(";") if x.strip()]
    undo = {"files": {c.path: c.before for c in changes}, "commit": None}

    if tests and code and not a.no_red:  # RED: tests first, code held back
        held = {c.path for c in code}
        write_changes(root, changes, only={c.path for c in changes} - held)
        rc, out = sh(f"{test_cmd} " + " ".join(shlex.quote(c.path) for c in tests), root)
        if rc == 0:
            restore(root, changes)
            return reject(
                reply.chat,
                reply.turn,
                [
                    "RED not proven: the new tests passed before the implementation was applied. "
                    "Strengthen them so they fail without the change."
                ],
                "Nothing was changed.",
            )
        print(f"red proven: the new tests fail without the code (exit {rc})")
    write_changes(root, changes)
    (mem.dir / "undo").mkdir(exist_ok=True)

    failures: list[str] = []
    if tests or code:
        for cmd in [test_cmd, *checks]:
            rc, out = sh(cmd, root)
            if rc == 5 and cmd == test_cmd:  # pytest: no tests collected yet (early scaffolding): not a failure
                rc = 0
                print("note: no tests collected yet")
            print(f"$ {cmd}  -> {'ok' if rc == 0 else f'FAILED (exit {rc})'}")
            if rc != 0:
                failures.append(f"$ {cmd} (exit {rc})\n{tail(out)}")
    (mem.dir / "undo" / f"{seq:04d}.json").write_text(json.dumps(undo))
    mem.state["undo"] = [*mem.state.get("undo", []), seq]
    if failures:
        mem.save()
        print("CHECKS FAILED. The files are in place (uncommitted); the evidence is below and on the clipboard.")
        evidence = "\n\n".join(failures)
        print(evidence)
        clip_copy(
            f"The checks failed after your reply (chat {reply.chat}, turn {reply.turn}). Fix it; the files you "
            f"wrote are in place, so edits apply on top.\n\n{evidence}"
        )
        return 3
    msg = reply.summary or f"relay: turn {reply.turn}"
    body = "".join(f"\ndecision: {d}" for d in reply.decisions)
    if not a.no_commit:
        git(root, "add", "-A")
        rc, out = git(root, "commit", "-q", "-m", f"{msg}\n{body}\n\nrelay: chat {reply.chat} turn {reply.turn}")
        if rc != 0:
            print(f"commit failed (set git user.name / user.email?): {out}")
            return 4
        undo["commit"] = git(root, "rev-parse", "HEAD")[1]
        (mem.dir / "undo" / f"{seq:04d}.json").write_text(json.dumps(undo))
    if reply.chat in mem.state["packets"]:
        mem.state["packets"][reply.chat]["applied"] = True
    mem.save()
    print(f"OK: {len(changes)} file(s) changed" + ("" if a.no_commit else f", committed: {msg}"))
    return 0


def cmd_undo(_: argparse.Namespace) -> int:
    root = repo_root()
    mem = Mem(root)
    if not mem.state.get("undo"):
        sys.exit("relay: nothing to undo")
    seq = mem.state["undo"].pop()
    rec = json.loads((mem.dir / "undo" / f"{seq:04d}.json").read_text())
    if rec["commit"]:
        if git(root, "rev-parse", "HEAD")[1] != rec["commit"] or git(root, "status", "--porcelain")[1]:
            mem.state["undo"].append(seq)
            sys.exit("relay: HEAD moved or the tree is dirty; refusing to undo (commit or stash first)")
        git(root, "reset", "-q", "--hard", "HEAD~1")
    else:
        for path, before in rec["files"].items():
            p = root / path
            if before is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(before, encoding="utf-8")
    (mem.dir / "undo" / f"{seq:04d}.json").unlink()
    mem.save()
    print(f"undone: {len(rec['files'])} file(s) restored")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    mem = Mem(repo_root())
    if not mem.state["packets"]:
        print("no packets yet")
    for chat, p in sorted(mem.state["packets"].items()):
        print(
            f"  {chat}  turn {p['turn']:<3} {p['label']:<12} {'applied' if p['applied'] else 'WAITING for its reply'}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="relay.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("slice", nargs="?")
    p.add_argument("--task")
    p.add_argument("--chat", default="c1")
    p.add_argument("--evidence")
    p.add_argument("--cg", action="append", default=[], metavar="ARGS", help='e.g. "callers apply" or "query Session"')
    p.add_argument("--read", action="append", default=[])
    p.add_argument("--print", action="store_true")
    p.set_defaults(fn=cmd_pack)
    q = sub.add_parser("apply")
    q.add_argument("file", nargs="?")
    q.add_argument("--no-red", action="store_true")
    q.add_argument("--no-commit", action="store_true")
    q.set_defaults(fn=cmd_apply)
    sub.add_parser("undo").set_defaults(fn=cmd_undo)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
