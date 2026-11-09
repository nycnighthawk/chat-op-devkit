"""Prompt templates and which documents each phase pulls into a packet."""

from __future__ import annotations

from importlib import resources
from string import Template

from chatop.domain.models import Phase, Track

PHASE_DOCS: dict[Phase, list[tuple[str, int]]] = {
    Phase.IDEA: [],
    Phase.REFINE: [("docs/IDEA.md", 1), ("docs/REFINEMENT.md", 1), ("docs/FEATURE.md", 1), ("docs/AS-BUILT.md", 4)],
    Phase.PRD: [("docs/REFINEMENT.md", 1), ("docs/IDEA.md", 3)],
    Phase.SPEC: [("docs/PRD.md", 1), ("docs/REFINEMENT.md", 3), ("docs/AS-BUILT.md", 2)],
    Phase.PLAN: [
        ("docs/SPEC.md", 1),
        ("docs/PRD.md", 2),
        ("docs/FEATURE.md", 1),
        ("docs/AUDIT.md", 1),
        ("docs/AS-BUILT.md", 3),
        ("docs/PLAN.md", 4),
    ],
    Phase.SLICE: [("docs/PRD.md", 3), ("docs/FEATURE.md", 3), ("docs/SPEC.md", 4), ("docs/PLAN.md", 5)],
    Phase.FEATURE: [("docs/AS-BUILT.md", 2), ("docs/SPEC.md", 2), ("docs/PRD.md", 3)],
    Phase.DELTA: [("docs/FEATURE.md", 1), ("docs/SPEC.md", 1), ("docs/PRD.md", 2), ("docs/AS-BUILT.md", 2)],
    Phase.RECON: [],
    Phase.AUDIT: [("docs/AS-BUILT.md", 1)],
    Phase.DONE: [],
}
TRACK_NOTES: dict[tuple[Track, Phase], str] = {
    (Track.NEW, Phase.PLAN): "- S0 is the walking skeleton: layout, dependency manifest, `.gitignore`, working check "
    "commands, one passing smoke test.",
    (Track.CONTINUE, Phase.PLAN): "- Slices implement `docs/FEATURE.md` only. Use IDs that do not collide with "
    "existing slices (for example F2-S1). Existing done slices are listed in *State*.",
    (Track.AUDIT, Phase.PLAN): "- This is a STABILISATION plan derived from `docs/AUDIT.md`. The first slices add "
    "characterization tests that pin current behavior around the riskiest hotspots (expected to PASS immediately). "
    "Then fix critical findings, one slice each. Never refactor untested code.",
    (Track.ADOPT, Phase.RECON): "This phase advances automatically. Next, the human adds features with "
    "`chatop feature`.",
    (Track.AUDIT, Phase.RECON): "This phase advances automatically to AUDIT. Note where quality looks weak.",
}


def template(name: str) -> Template:
    return Template(resources.files("chatop.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8"))
