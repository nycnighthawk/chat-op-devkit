"""Git adapter (VCS port)."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path


class GitVcs:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str) -> tuple[int, str]:
        try:
            p = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)

    def is_repo(self) -> bool:
        return self._git("rev-parse", "--is-inside-work-tree")[0] == 0

    def commit_all(self, message: str) -> str | None:
        if not self.is_repo():
            return None
        self._git("add", "-A")
        code, _ = self._git("commit", "-q", "-m", message)
        if code != 0:
            return None
        return self._git("rev-parse", "--short", "HEAD")[1].strip()

    def tracked_files(self) -> list[str]:
        code, out = self._git("ls-files", "--cached", "--others", "--exclude-standard")
        return [ln for ln in out.splitlines() if ln] if code == 0 else []

    def churn(self, limit: int = 15) -> list[tuple[str, int]]:
        code, out = self._git("log", "--name-only", "--pretty=format:", "-n", "500")
        if code != 0:
            return []
        counts = Counter(ln for ln in out.splitlines() if ln.strip())
        return counts.most_common(limit)

    def log_summary(self, limit: int = 200) -> str:
        code, out = self._git("log", f"-n{limit}", "--pretty=format:%h %ad %an | %s%n%b", "--date=short")
        return out if code == 0 else ""
