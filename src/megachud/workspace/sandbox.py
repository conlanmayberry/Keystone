from __future__ import annotations

from pathlib import Path


class WorkspaceEscapeError(Exception):
    """Raised when a requested path resolves outside the workspace root."""


def resolve_safe_path(root: Path, user_path: str) -> Path:
    """Resolve `user_path` (relative or absolute) against `root`, refusing
    anything that escapes the workspace — via `..` traversal, an absolute
    path pointing elsewhere, or a symlink leading outside the root.

    `.resolve()` collapses `..` components and follows symlinks, so the
    containment check below catches all three cases uniformly.
    """
    root_resolved = root.resolve()
    candidate = (root / user_path).resolve()

    if not candidate.is_relative_to(root_resolved):
        raise WorkspaceEscapeError(f"path escapes workspace root: {user_path!r}")

    return candidate
