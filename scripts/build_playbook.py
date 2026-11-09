"""Build docs/chatop-playbook.html: one self-contained page generated from the real sources.

Embeds: prompt templates (src/chatop/prompts), the markdown docs, the repo file list, and transcripts recorded by
replaying every lab through the real app. Run from an activated dev venv (labs call pytest/mypy):

    python scripts/build_playbook.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "playbook.template.html"
OUT = ROOT / "docs" / "chatop-playbook.html"
LABS = ["new-project", "continue-feature", "adopt", "audit", "parallel-relay"]
DOCS = ["PLAYBOOK.md", "DECISIONS.md", "GETTING-STARTED.md", "LABS.md", "ARCHITECTURE.md", "UX.md"]


def collect_data(record_labs: bool = True) -> dict[str, object]:
    sys.path.insert(0, str(ROOT / "src"))
    prompts_dir = ROOT / "src" / "chatop" / "prompts"
    order = [
        "system",
        "contract",
        "idea",
        "refine",
        "prd",
        "spec",
        "plan",
        "slice",
        "feature",
        "delta",
        "recon",
        "audit",
    ]
    prompts = {name: (prompts_dir / f"{name}.md").read_text() for name in order}
    docs = {name: (ROOT / "docs" / name).read_text() for name in DOCS}
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    labs: dict[str, object] = {}
    if record_labs:
        spec = importlib.util.spec_from_file_location("run_lab", ROOT / "labs" / "run_lab.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"
        for lab in LABS:
            transcript: list[dict[str, object]] = []
            with tempfile.TemporaryDirectory() as tmp:
                mod.run(lab, Path(tmp) / lab, verbose=False, record=transcript)
            for step in transcript:  # timings vary run to run; keep output stable and readable
                for key in ("output", "packet"):
                    if isinstance(step.get(key), str):
                        step[key] = re.sub(
                            r"\(\d+\.\d+s\)|, \d+\.\d+s\)",
                            lambda m: "(…s)" if m.group(0).startswith("(") else ", …s)",
                            str(step[key]),
                        )
            labs[lab] = transcript
    spec = importlib.util.spec_from_file_location("build_mock_ui", ROOT / "scripts" / "build_mock_ui.py")
    assert spec and spec.loader
    mock_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock_mod)
    return {"prompts": prompts, "docs": docs, "files": files, "labs": labs, "mock": mock_mod.build()}


def render(data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("/*__CHATOP_DATA__*/null", payload)


def main() -> None:
    OUT.write_text(render(collect_data()))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
