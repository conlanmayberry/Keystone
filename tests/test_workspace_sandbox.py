from __future__ import annotations

import pytest

from megachud.workspace.sandbox import WorkspaceEscapeError, resolve_safe_path


def test_valid_relative_path_resolves_inside_root(tmp_workspace):
    resolved = resolve_safe_path(tmp_workspace, "notes/todo.txt")
    assert resolved == (tmp_workspace / "notes" / "todo.txt").resolve()


def test_parent_traversal_is_rejected(tmp_workspace):
    with pytest.raises(WorkspaceEscapeError):
        resolve_safe_path(tmp_workspace, "../../etc/passwd")


def test_absolute_path_outside_root_is_rejected(tmp_workspace):
    with pytest.raises(WorkspaceEscapeError):
        resolve_safe_path(tmp_workspace, str(tmp_workspace.parent / "outside.txt"))


def test_symlink_escape_is_rejected(tmp_workspace):
    outside = tmp_workspace.parent / "outside_dir"
    outside.mkdir()
    link = tmp_workspace / "escape_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(WorkspaceEscapeError):
        resolve_safe_path(tmp_workspace, "escape_link/secret.txt")


def test_root_itself_resolves(tmp_workspace):
    resolved = resolve_safe_path(tmp_workspace, ".")
    assert resolved == tmp_workspace.resolve()
