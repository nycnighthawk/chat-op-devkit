"""Runs configured check commands (test/typecheck/lint). Commands come from config.toml only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import ClassVar

from chatop.ports import RunResult


class ShellRunner:
    # Fast edit->check loops can rewrite a file within the same second at the same size; Python's
    # mtime+size .pyc validation then serves stale bytecode. Checks therefore never write bytecode.
    ENV: ClassVar[dict[str, str]] = {"PYTHONDONTWRITEBYTECODE": "1"}

    def run(self, name: str, cmd: str, cwd: Path, timeout: int) -> RunResult:
        start = time.monotonic()
        try:
            p = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **self.ENV},
            )
            code, out = p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            code, out = 124, f"timed out after {timeout}s"
        return RunResult(name, cmd, code, out, round(time.monotonic() - start, 2))
