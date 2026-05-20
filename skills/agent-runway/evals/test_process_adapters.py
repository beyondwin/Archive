from __future__ import annotations

from pathlib import Path

from agentrunway.adapters.claude import ClaudeAdapter
from agentrunway.adapters.codex import CodexAdapter


def test_claude_adapter_builds_headless_command(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    cmd = ClaudeAdapter(model="opus").build_command("prompt text", tmp_path, artifact_dir)
    assert "claude" in cmd[0]
    assert "opus" in cmd
    assert "--permission-mode" in cmd
    assert "acceptEdits" in cmd
    assert "--add-dir" in cmd
    assert str(artifact_dir) in cmd
    assert "--allowedTools" in cmd
    assert "--cwd" not in cmd


def test_codex_adapter_builds_exec_command_with_reasoning(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    cmd = CodexAdapter(model="gpt-5.5", reasoning_effort="xhigh").build_command("prompt text", tmp_path, artifact_dir)
    assert cmd[:2] == ["codex", "exec"]
    assert "gpt-5.5" in cmd
    assert "--sandbox" in cmd
    assert "danger-full-access" in cmd
    assert "--add-dir" in cmd
    assert str(artifact_dir) in cmd
    assert "--skip-git-repo-check" in cmd
    assert 'model_reasoning_effort="xhigh"' in cmd
    assert "--cwd" not in cmd
    assert "--reasoning-effort" not in cmd
