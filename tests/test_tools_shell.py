from __future__ import annotations

from megachud.tools.shell_tool import ShellExecTool


def make_tool(workspace_root, allowlist=("python",), denylist=(), timeout=10):
    return ShellExecTool(
        workspace_root=workspace_root,
        allowlist=list(allowlist),
        denylist=list(denylist),
        timeout_seconds=timeout,
    )


def test_allowlisted_command_runs_and_captures_output(tmp_workspace):
    tool = make_tool(tmp_workspace)
    result = tool.run({"command": "python -c \"print(1)\""})
    assert result.success
    assert result.output.strip() == "1"
    assert result.metadata["exit_code"] == 0


def test_non_allowlisted_command_is_rejected_without_running(tmp_workspace):
    tool = make_tool(tmp_workspace, allowlist=["python"])
    result = tool.run({"command": "curl http://example.com"})
    assert not result.success
    assert "not in allowlist" in result.error


def test_denylisted_command_is_rejected(tmp_workspace):
    tool = make_tool(tmp_workspace, allowlist=["git"], denylist=["git push"])
    result = tool.run({"command": "git push origin main"})
    assert not result.success
    assert "denylisted" in result.error


def test_forbidden_metacharacter_is_rejected(tmp_workspace):
    tool = make_tool(tmp_workspace, allowlist=["python"])
    result = tool.run({"command": "python -c \"print(1)\" && python -c \"print(2)\""})
    assert not result.success
    assert "forbidden shell metacharacter" in result.error


def test_command_timeout_is_enforced(tmp_workspace):
    tool = make_tool(tmp_workspace, allowlist=["python"], timeout=1)
    result = tool.run({"command": "python -c \"import time; time.sleep(5)\""})
    assert not result.success
    assert "timed out" in result.error


def test_cwd_is_confined_to_workspace(tmp_workspace):
    tool = make_tool(tmp_workspace, allowlist=["python"])
    result = tool.run({"command": "python -c \"print(1)\"", "cwd": "../../"})
    assert not result.success
    assert "escapes workspace" in result.error
