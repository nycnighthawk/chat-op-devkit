"""Generate bootstrap/accept.py (embedded labs) from labs/ and bootstrap/accept_template.py.

python scripts/build_bootstrap.py          # writes bootstrap/accept.py
python scripts/build_bootstrap.py --check  # exit 1 if it is out of date
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABS = ROOT / "labs"
ORDER = ["new-project", "continue-feature", "adopt", "audit", "parallel-relay"]


def collect() -> dict[str, object]:
    labs = {n: {"steps": (LABS / n / "steps.txt").read_text()} for n in ORDER}
    replies = {f"{n}/{p.name}": p.read_text() for n in ORDER for p in sorted((LABS / n / "replies").glob("*.md"))}
    seeds = {
        d.name: {str(f.relative_to(d)): f.read_text() for f in sorted(d.rglob("*")) if f.is_file()}
        for d in sorted((LABS / "seeds").iterdir())
        if d.is_dir()
    }
    return {"order": ORDER, "labs": labs, "replies": replies, "seeds": seeds}


def render() -> str:
    template = (ROOT / "bootstrap" / "accept_template.py").read_text()
    payload = json.dumps(collect(), sort_keys=True)
    return template.replace('"__DATA__"', repr(payload))


SEED = ROOT / "bootstrap" / "seed"
HEADER = "<<<CHATOP chat=c0 turn=0>>>"
DESIGN_DOCS = {
    "docs/ARCHITECTURE.md": ROOT / "docs" / "ARCHITECTURE.md",
    "docs/DECISIONS.md": ROOT / "docs" / "DECISIONS.md",
    "docs/UX.md": ROOT / "docs" / "UX.md",
    "docs/BEHAVIOR.md": SEED / "BEHAVIOR.md",
    "docs/PLAN.md": SEED / "PLAN.md",
}


def embeddable(body: str) -> bool:
    """False if a line would end the block or the envelope early (the documented @@end limitation)."""
    return not any(ln.strip() in ("@@end", "<<<END>>>") or ln.startswith("````") for ln in body.splitlines())


def reply(summary: str, blocks: list[tuple[str, str, str]]) -> str:
    """A ready-to-apply reply (chat=c0 turn=0: the kernel has no packet to compare it with)."""
    out = ["````chatop", HEADER, f"@@summary {summary}"]
    for kind, path, body in blocks:
        if not embeddable(body):
            raise SystemExit(f"{path} contains an envelope marker; cannot embed it in a reply")
        out += [f"@@{kind} {path}", body.rstrip("\n"), "@@end"]
    return "\n".join([*out, "<<<END>>>", "````", ""])


def raw_prompts() -> list[Path]:
    """Prompt files that talk about the envelope itself cannot travel inside one: they are copied as plain files."""
    return [p for p in sorted((ROOT / "src" / "chatop" / "prompts").glob("*.md")) if not embeddable(p.read_text())]


def seed_replies() -> dict[str, str]:
    docs = [("doc", dest, src.read_text()) for dest, src in DESIGN_DOCS.items()]
    prompts = [
        ("file", f"src/chatop/prompts/{p.name}", p.read_text())
        for p in sorted((ROOT / "src" / "chatop" / "prompts").glob("*.md"))
        if embeddable(p.read_text())
    ]
    return {
        "seed-design.reply.md": reply("seed: architecture, decisions, UX, behavior contract and reference plan", docs),
        "seed-prompts.reply.md": reply("seed: the prompt files chatop renders into packets", prompts),
    }


WAVES = [
    ("A", "models, parser, ports", ["S1", "S4"], "pytest, ruff and mypy --strict are green"),
    ("B", "changes, workflow, workspace", ["S2", "S3", "S5"], "pytest, ruff and mypy --strict are green"),
    ("C", "session and CLI", ["S6", "S7"], "accept.py lab1 and lab2 pass"),
    ("D", "recon and parallel lanes", ["S8", "S9"], "accept.py all: 5/5 labs"),
    ("E", "web UI and TUI", ["S10", "S11"], "built by chatop itself; the labs stay green"),
]
PLAYS_TEMPLATE = ROOT / "docs" / "bootstrap-plays.template.html"
PLAYS_OUT = ROOT / "docs" / "chatop-bootstrap-plays.html"
KIT = [  # (path inside the zip, source in the repo, role)
    ("bootstrap/relay.py", "bootstrap/relay.py", "stage-0 kernel: pack packets, apply replies (stdlib only)"),
    ("bootstrap/relay_acceptance.py", "bootstrap/relay_acceptance.py", "9 black-box checks for any relay.py"),
    ("bootstrap/accept.py", "bootstrap/accept.py", "conformance oracle: replays the 5 labs through the chatop CLI"),
    ("bootstrap/env.sh", "bootstrap/env.sh", "source it: the `relay` shell function and RELAY_CHECKS"),
    (
        "bootstrap/seed/seed-design.reply.md",
        "bootstrap/seed/seed-design.reply.md",
        "reply: architecture, decisions, UX, behavior contract, plan",
    ),
    ("bootstrap/seed/seed-prompts.reply.md", "bootstrap/seed/seed-prompts.reply.md", "reply: the prompt files"),
    ("bootstrap/seed/raw/contract.md", "bootstrap/seed/raw/contract.md", "the envelope prompt (copied, not applied)"),
    ("bootstrap/seed/BRIEF.md", "bootstrap/seed/BRIEF.md", "product brief (purist path)"),
    ("bootstrap/seed/features/ui.txt", "bootstrap/seed/features/ui.txt", "feature text for the web UI and TUI (act 4)"),
    ("pyproject.toml", "bootstrap/kit/pyproject.toml", "skeleton: pytest, ruff, mypy settings"),
    ("gitignore", "bootstrap/kit/gitignore", "rename to .gitignore"),
]


def parse_plan(text: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    wave_of = {sid: w for w, _, ids, _ in WAVES for sid in ids}
    for m in re.finditer(r"^## (S\d+): (.+)\n((?:(?!^## ).*\n?)*)", text, re.M):
        sid, title, body = m.group(1), m.group(2), m.group(3)

        def field(name: str, body: str = body) -> str:
            f = re.search(rf"^- {name}: (.*)$", body, re.M)
            return f.group(1).strip() if f else ""

        deps = [d.strip() for d in field("depends").split(",") if d.strip() and d.strip() != "none"]
        out.append(
            {
                "id": sid,
                "title": title,
                "chat": "c" + sid[1:],
                "wave": wave_of[sid],
                "depends": deps,
                "touches": [t.strip() for t in field("touches").split(",") if t.strip()],
                "goal": field("goal"),
                "acceptance": field("acceptance"),
            }
        )
    return out


def plays_html(files: dict[Path, str]) -> str:
    import bootstrap_plays as bp

    kit = [
        {"zip_path": z, "role": role, "text": files[ROOT / src] if (ROOT / src) in files else (ROOT / src).read_text()}
        for z, src, role in KIT
    ]
    data = {
        "acts": bp.ACTS,
        "slices": parse_plan((SEED / "PLAN.md").read_text()),
        "waves": [{"id": w, "title": t, "slices": ids, "gate": g} for w, t, ids, g in WAVES],
        "kit": kit,
        "prompts": {"KERNEL_PROMPT": bp.KERNEL_PROMPT, "BRIEF": bp.BRIEF, "FEATURE_UI": bp.FEATURE_UI},
        "backlog": bp.BACKLOG,
        "budget": bp.BUDGET,
        "failures": bp.FAILURES,
        "unverified": bp.UNVERIFIED,
    }
    payload = json.dumps(data, sort_keys=True).replace("</", "<\\/")
    return PLAYS_TEMPLATE.read_text().replace("/*__BOOTSTRAP_DATA__*/null", payload)


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import bootstrap_plays as bp

    wanted = {ROOT / "bootstrap" / "accept.py": render()}
    wanted |= {SEED / name: text for name, text in seed_replies().items()}
    wanted |= {SEED / "raw" / p.name: p.read_text() for p in raw_prompts()}
    wanted[SEED / "BRIEF.md"] = bp.BRIEF
    wanted[SEED / "features" / "ui.txt"] = bp.FEATURE_UI + "\n"
    wanted[PLAYS_OUT] = plays_html(wanted)
    if "--check" in sys.argv:
        return 0 if all(p.exists() and p.read_text() == t for p, t in wanted.items()) else 1
    for path, text in wanted.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
