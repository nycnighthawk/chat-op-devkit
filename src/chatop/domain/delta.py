"""Delta context: a chat that already holds a document or file should not be sent it again."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


@dataclass
class Delta:
    changed: list[str]  # keys that are new or whose content differs from what the chat has
    unchanged: list[str]  # keys the chat already holds
    new_seen: dict[str, str]  # what the chat holds once the packet is delivered


def plan_delta(seen: dict[str, str], current: dict[str, str]) -> Delta:
    changed: list[str] = []
    unchanged: list[str] = []
    new_seen: dict[str, str] = {}
    for key, text in current.items():
        d = digest(text)
        new_seen[key] = d
        (unchanged if seen.get(key) == d else changed).append(key)
    return Delta(changed, unchanged, new_seen)
