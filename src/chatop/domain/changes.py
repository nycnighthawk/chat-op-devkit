"""Turn a parsed Reply into a validated, fully-resolved change set (no disk writes here).

Everything is computed in memory first so that application is all-or-nothing.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch

from chatop.domain.models import Role
from chatop.domain.reply import Delete, Edit, Reply, Write, infer_role

Reader = Callable[[str], str | None]


@dataclass
class FileChange:
    path: str
    before: str | None  # None = file did not exist
    after: str | None  # None = delete
    role: Role


def safe_path(path: str, protected: list[str]) -> tuple[str | None, str | None]:
    """Return (normalised_path, error)."""
    p = path.strip().replace("\\", "/")
    if not p or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return None, f"{path}: absolute paths are not allowed"
    norm = posixpath.normpath(p)
    if norm == ".." or norm.startswith("../"):
        return None, f"{path}: path escapes the project root"
    for pat in protected:
        if fnmatch(norm, pat) or fnmatch(norm + "/", pat):
            return None, f"{path}: protected by config ({pat})"
    return norm, None


def apply_block(content: str, search: str, replace: str) -> tuple[str | None, str]:
    count = content.count(search)
    if count == 1:
        return content.replace(search, replace, 1), ""
    if count > 1:
        return None, f"ambiguous SEARCH (matches {count} times) - include more context lines"
    # Fallback: compare with trailing whitespace stripped per line.
    src = content.split("\n")
    pat = search.rstrip("\n").split("\n")
    stripped = [ln.rstrip() for ln in src]
    want = [ln.rstrip() for ln in pat]
    hits = [i for i in range(len(src) - len(pat) + 1) if stripped[i : i + len(pat)] == want]
    if len(hits) == 1:
        i = hits[0]
        rep = replace.rstrip("\n").split("\n") if replace else []
        return "\n".join(src[:i] + rep + src[i + len(pat) :]), ""
    if len(hits) > 1:
        return None, "ambiguous SEARCH (whitespace-insensitive) - include more context lines"
    return None, "SEARCH text not found - re-read the file (use @@need file) and resend the edit"


def plan_changes(reply: Reply, read: Reader, protected: list[str]) -> tuple[list[FileChange], list[str]]:
    errors: list[str] = []
    originals: dict[str, str | None] = {}
    current: dict[str, str | None] = {}
    roles: dict[str, Role] = {}

    for op in reply.ops:
        path, err = safe_path(op.path, protected)
        if path is None:
            errors.append(err or op.path)
            continue
        if path not in current:
            originals[path] = current[path] = read(path)
        existing = current[path]
        if isinstance(op, Write):
            current[path] = op.content
            roles[path] = op.role
        elif isinstance(op, Delete):
            if existing is None:
                errors.append(f"{path}: cannot delete, file does not exist")
            current[path] = None
        elif isinstance(op, Edit):
            if existing is None:
                errors.append(f"{path}: cannot edit, file does not exist (use @@file to create it)")
                continue
            content: str = existing
            for n, (search, replace) in enumerate(op.blocks, 1):
                new, msg = apply_block(content, search, replace)
                if new is None:
                    errors.append(f"{path}: edit block {n}: {msg}")
                    break
                content = new
            current[path] = content

    changes = [
        FileChange(p, originals[p], current[p], roles.get(p, infer_role(p)))
        for p in current
        if originals[p] != current[p]
    ]
    return changes, errors
