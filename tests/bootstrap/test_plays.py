"""The bootstrap plays page: embedded files match the repo, the plays reference things that exist, the browser works."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "docs" / "chatop-bootstrap-plays.html"
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap_plays as bp  # noqa: E402
import build_bootstrap as bb  # noqa: E402


def embedded() -> dict:  # type: ignore[type-arg]
    m = re.search(r"const DATA = (\{.*?\});\nconst LS", HTML.read_text(), re.S)
    assert m, "DATA payload not found"
    return json.loads(m.group(1).replace("<\\/", "</"))  # type: ignore[no-any-return]


def test_page_is_up_to_date() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_bootstrap.py"), "--check"])
    assert r.returncode == 0, "run: python scripts/build_bootstrap.py"


def test_kit_files_match_the_repo_and_are_non_empty() -> None:
    data = embedded()
    assert [k["zip_path"] for k in data["kit"]] == [z for z, _, _ in bb.KIT]
    for k, (_, src, _) in zip(data["kit"], bb.KIT, strict=True):
        assert k["text"].strip(), k["zip_path"]
        assert k["text"] == (ROOT / src).read_text(), f"{src} drifted from the page"


def test_page_is_a_single_self_contained_file() -> None:
    text = HTML.read_text()
    assert not re.findall(r'(?:src|href)="https?://', text)
    assert "<script src=" not in text and "<link " not in text


def test_every_slice_has_a_pack_command_and_chat_numbers_match() -> None:
    data = embedded()
    cmds = "\n".join(c for a in data["acts"] for p in a["plays"] for _, c in p.get("cmds", []))
    for s in data["slices"]:
        assert s["chat"] == "c" + s["id"][1:]
        if s["id"] in ("S10", "S11"):  # built by chatop itself, from the feature text
            continue
        assert f"relay pack {s['id']} --chat {s['chat']}" in cmds, s["id"]


def test_plan_waves_cover_all_slices_once() -> None:
    plan_ids = [s["id"] for s in bb.parse_plan((ROOT / "bootstrap" / "seed" / "PLAN.md").read_text())]
    wave_ids = [i for _, _, ids, _ in bb.WAVES for i in ids]
    assert sorted(plan_ids, key=lambda x: int(x[1:])) == sorted(wave_ids, key=lambda x: int(x[1:]))
    assert len(set(wave_ids)) == len(wave_ids)


def test_plays_are_well_formed() -> None:
    ids: list[str] = []
    for act in bp.ACTS:
        for p in act["plays"]:
            ids.append(p["id"])
            assert p["mode"] in ("both", "seeded", "purist")
            assert p["do"] and p["where"], p["id"]
            assert p.get("expect") or p.get("checklist"), p["id"]
    assert len(set(ids)) == len(ids)
    assert {"1.1", "1.1p", "2.1", "2.1p"} <= set(ids)  # both paths exist for kernel and design
    assert len(bp.BACKLOG) == 6 and len(bp.FAILURES) >= 10 and bp.UNVERIFIED


def test_relay_commands_in_plays_parse_with_the_real_cli() -> None:
    """Every `relay pack ...` / `relay apply ...` line in the plays is accepted by the kernel's argument parser."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("relay", ROOT / "bootstrap" / "relay.py")
    assert spec and spec.loader
    relay = importlib.util.module_from_spec(spec)
    sys.modules["relay"] = relay  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(relay)
    import shlex

    checked = 0
    for act in bp.ACTS:
        for p in act["plays"]:
            for _, code in p.get("cmds", []):
                for line in code.replace("\\\n", " ").splitlines():
                    m = re.match(r"\s*relay (pack|apply|undo|status)\b(.*)", line)
                    if not m:
                        continue
                    argv = shlex.split(m.group(1) + " " + re.sub(r"\s+#.*$", "", m.group(2)).replace("| head -80", ""))
                    argv = [a for a in argv if a not in ("|", "head", "-80")]
                    try:
                        relay.build_parser().parse_args(argv)
                    except SystemExit as exc:  # argparse error
                        pytest.fail(f"play {p['id']}: `{line.strip()}` is not accepted by relay.py ({exc})")
                    checked += 1
    assert checked >= 15


def test_spec_documents_are_embedded_verbatim_and_extractable(tmp_path: Path) -> None:
    """The documented one-command extractor turns the page back into the exact markdown files."""
    out = tmp_path / "spec"
    r = subprocess.run(
        ["python3", "-c", "import sys;exec(sys.stdin.read())", str(HTML), str(out)],
        input=_extract_body(),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    for _, path, _, text in bb.spec_sources():
        assert (out / path).read_text().rstrip("\n") == text.rstrip("\n"), path
    assert len(list(out.rglob("*.md"))) == 6


def _extract_body() -> str:
    """The python between the heredoc markers of bp.EXTRACT_PY, run with sys.argv = [-c, html, out]."""
    lines = bp.EXTRACT_PY.splitlines()
    return "\n".join(lines[1:-1]).replace("sys.argv[1]", "sys.argv[1]")


def test_prd_ids_are_well_formed_and_fully_traced_in_the_design() -> None:
    prd = (ROOT / "docs" / "PRD.md").read_text()
    design = (ROOT / "docs" / "DESIGN.md").read_text()
    rows = re.findall(r"^\| (FR-\d+) \| .*? \| ([MSC]) \|", prd, re.M)
    ids = [i for i, _ in rows]
    assert len(ids) >= 40 and len(set(ids)) == len(ids)
    assert sorted(ids, key=lambda x: int(x[3:])) == ids, "FR ids must stay in ascending order"
    trace = design.split("## 4. Traceability")[1].split("## 5.")[0]
    traced = set(re.findall(r"^\| (FR-\d+) ", trace, re.M))
    assert traced == set(ids), f"untraced: {set(ids) - traced}; unknown: {traced - set(ids)}"
    for nfr in re.findall(r"^\| (NFR-\d+) ", prd, re.M):
        assert nfr in prd
    # every labs name the PRD cites exists
    labs = {p.name for p in (ROOT / "labs").iterdir() if p.is_dir()}
    assert set(re.findall(r"`((?:new-project|continue-feature|adopt|audit|parallel-relay))`", prd)) <= labs


HAVE_BROWSER = bool(os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium"))
NODE_PATH = os.environ.get("NODE_PATH") or "/opt/npm-tools/node_modules"


@pytest.mark.skipif(
    not (shutil.which("node") and HAVE_BROWSER and Path(NODE_PATH, "playwright").exists()), reason="no browser"
)
def test_browser_walkthrough_and_zip_download() -> None:
    env = {
        **os.environ,
        "NODE_PATH": NODE_PATH,
        "CHROME": os.environ.get("CHROME") or shutil.which("google-chrome") or "",
    }
    r = subprocess.run(
        ["node", str(ROOT / "bootstrap" / "plays.browser.test.js"), str(HTML)], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr
    zpath = Path(r.stdout.strip().rsplit("zip at ", 1)[1])
    spec_zip = Path(Path(os.environ.get("TMPDIR", "/tmp"), "plays-spec-path.txt").read_text())
    with zipfile.ZipFile(spec_zip) as sz:
        assert sz.testzip() is None
        assert set(sz.namelist()) == {
            "docs/PRD.md",
            "docs/DESIGN.md",
            "docs/ARCHITECTURE.md",
            "docs/BEHAVIOR.md",
            "docs/DECISIONS.md",
            "docs/UX.md",
            "docs/SPEC-BUNDLE.md",
            "docs/AGENT-PROMPTS.md",
        }
        assert sz.read("docs/PRD.md").decode() == (ROOT / "docs" / "PRD.md").read_text()
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert names == [k for k, _, _ in bb.KIT]
        assert z.read("bootstrap/relay.py").decode() == (ROOT / "bootstrap" / "relay.py").read_text()
        assert z.read("pyproject.toml").decode() == (ROOT / "bootstrap" / "kit" / "pyproject.toml").read_text()
