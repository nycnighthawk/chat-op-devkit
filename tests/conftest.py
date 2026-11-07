from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chatop.adapters.git import GitVcs
from chatop.adapters.runner import ShellRunner
from chatop.app.session import Session
from chatop.app.workspace import Workspace
from tests.fakes import FakeClipboard, FakeIndex

PYTEST = f"{sys.executable} -m pytest -q -p no:cacheprovider"


def git_init(root: Path) -> None:
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "Test"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True)


@pytest.fixture
def make_session(tmp_path: Path):  # type: ignore[no-untyped-def]
    def factory(root: Path | None = None, git: bool = True) -> tuple[Session, FakeClipboard, FakeIndex]:
        r = root or tmp_path
        if git:
            git_init(r)
        clip, index = FakeClipboard(), FakeIndex()
        session = Session(Workspace(r), index, clip, ShellRunner(), GitVcs(r))
        return session, clip, index

    return factory
