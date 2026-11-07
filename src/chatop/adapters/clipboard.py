"""Clipboard adapters: macOS (pbcopy), Wayland (wl-copy), X11 (xclip/xsel), file fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class CommandClipboard:
    def __init__(self, name: str, copy_cmd: list[str], paste_cmd: list[str]) -> None:
        self.name, self._copy, self._paste = name, copy_cmd, paste_cmd

    def copy(self, text: str) -> bool:
        try:
            subprocess.run(self._copy, input=text, text=True, check=True, timeout=10)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def paste(self) -> str | None:
        try:
            p = subprocess.run(self._paste, capture_output=True, text=True, timeout=10)
            return p.stdout if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None


class FileClipboard:
    """Headless fallback: copy -> .chatop/outbox.md, paste <- .chatop/inbox.md."""

    name = "file"

    def __init__(self, folder: Path) -> None:
        self.outbox, self.inbox = folder / "outbox.md", folder / "inbox.md"

    def copy(self, text: str) -> bool:
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        self.outbox.write_text(text, encoding="utf-8")
        return False  # not on the system clipboard

    def paste(self) -> str | None:
        return self.inbox.read_text(encoding="utf-8") if self.inbox.exists() else None


def detect_clipboard(state_dir: Path) -> CommandClipboard | FileClipboard:
    forced = os.environ.get("CHATOP_CLIPBOARD")
    if forced == "file":
        return FileClipboard(state_dir)
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        return CommandClipboard("pbcopy", ["pbcopy"], ["pbpaste"])
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return CommandClipboard("wl-clipboard", ["wl-copy"], ["wl-paste", "--no-newline"])
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            return CommandClipboard(
                "xclip", ["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]
            )
        if shutil.which("xsel"):
            return CommandClipboard("xsel", ["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"])
    return FileClipboard(state_dir)
