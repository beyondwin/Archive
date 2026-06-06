"""Tests for materialize_worktree_hooks.py — worktree settings.json hook merge.

Covers the v2.27 run-2 regression: a source repo that already ships
.claude/settings.json (permissions allowlist + $schema) must keep those keys AND
gain all four safety hooks. Plus --check preflight, Stop-gate assertion,
idempotency, and refusal to clobber an unparseable existing file.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import materialize_worktree_hooks as mwh  # noqa: E402

ORCH = "/abs/orch/run-x"
SKILL = "/abs/skill"
REQUIRED = ("PreToolUse", "PostToolUse", "SubagentStop", "Stop")


def _settings(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def _write_existing(tmp_path, data):
    p = _settings(tmp_path)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# --- build_hooks -----------------------------------------------------------

def test_build_hooks_has_four_events_and_stop_gate():
    hooks = mwh.build_hooks(ORCH, SKILL)
    assert set(hooks) == set(REQUIRED)
    stop_cmd = hooks["Stop"][0]["hooks"][0]["command"]
    assert "finalization-stop-gate.sh" in stop_cmd
    assert f"{ORCH}/state.json" in stop_cmd
    assert f"{SKILL}/scripts" in stop_cmd
    assert hooks["PostToolUse"][0]["hooks"][0]["command"].endswith(
        "scan-debug-artifacts.sh")
    assert hooks["SubagentStop"][0]["hooks"][0]["command"].endswith(
        "check-implementer-output.sh")
    assert hooks["PreToolUse"][0]["matcher"] == "Bash"


# --- merge_settings (the run-2 regression) ---------------------------------

def test_merge_preserves_permissions_and_schema():
    existing = {
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "permissions": {"allow": ["Bash(pnpm:*)", "Bash(git:*)"]},
    }
    merged = mwh.merge_settings(existing, mwh.build_hooks(ORCH, SKILL))
    assert merged["$schema"] == existing["$schema"]
    assert merged["permissions"] == existing["permissions"]
    assert set(merged["hooks"]) == set(REQUIRED)


def test_merge_into_empty_settings_creates_hooks():
    merged = mwh.merge_settings({}, mwh.build_hooks(ORCH, SKILL))
    assert set(merged["hooks"]) == set(REQUIRED)


def test_merge_preserves_other_repo_hook_events_but_ours_win():
    existing = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "repo.sh"}]}],
            "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command",
                                                           "command": "repo-old.sh"}]}],
        }
    }
    merged = mwh.merge_settings(existing, mwh.build_hooks(ORCH, SKILL))
    # repo's unrelated event preserved
    assert merged["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "repo.sh"
    # our PostToolUse wins over the repo's
    assert merged["hooks"]["PostToolUse"][0]["hooks"][0]["command"].endswith(
        "scan-debug-artifacts.sh")


# --- check_problems --------------------------------------------------------

def test_check_problems_empty_when_wired():
    wired = {"hooks": mwh.build_hooks(ORCH, SKILL)}
    assert mwh.check_problems(wired) == []


def test_check_problems_flags_missing_stop():
    hooks = mwh.build_hooks(ORCH, SKILL)
    del hooks["Stop"]
    problems = mwh.check_problems({"hooks": hooks})
    assert any("Stop" in p for p in problems)


def test_check_problems_flags_stop_without_gate():
    hooks = mwh.build_hooks(ORCH, SKILL)
    hooks["Stop"] = [{"hooks": [{"type": "command", "command": "echo hi"}]}]
    problems = mwh.check_problems({"hooks": hooks})
    assert any("finalization-stop-gate.sh" in p for p in problems)


# --- CLI write mode --------------------------------------------------------

def test_write_mode_on_readmates_shape(tmp_path):
    _write_existing(tmp_path, {
        "$schema": "x",
        "permissions": {"allow": ["Bash(gradlew:*)"]},
    })
    rc = mwh.main(["--worktree", str(tmp_path), "--orch-dir", ORCH,
                   "--skill-dir", SKILL])
    assert rc == 0
    out = _read(_settings(tmp_path))
    assert out["permissions"] == {"allow": ["Bash(gradlew:*)"]}
    assert set(out["hooks"]) == set(REQUIRED)


def test_write_mode_no_existing_file(tmp_path):
    (tmp_path / ".claude").mkdir()
    rc = mwh.main(["--worktree", str(tmp_path), "--orch-dir", ORCH,
                   "--skill-dir", SKILL])
    assert rc == 0
    assert set(_read(_settings(tmp_path))["hooks"]) == set(REQUIRED)


def test_write_mode_creates_claude_dir(tmp_path):
    # .claude does not exist yet
    rc = mwh.main(["--worktree", str(tmp_path), "--orch-dir", ORCH,
                   "--skill-dir", SKILL])
    assert rc == 0
    assert _settings(tmp_path).is_file()


def test_write_mode_idempotent(tmp_path):
    args = ["--worktree", str(tmp_path), "--orch-dir", ORCH, "--skill-dir", SKILL]
    assert mwh.main(args) == 0
    first = _settings(tmp_path).read_text(encoding="utf-8")
    assert mwh.main(args) == 0
    second = _settings(tmp_path).read_text(encoding="utf-8")
    assert first == second


def test_write_mode_refuses_unparseable_existing(tmp_path):
    _settings(tmp_path).write_text("{not json", encoding="utf-8")
    rc = mwh.main(["--worktree", str(tmp_path), "--orch-dir", ORCH,
                   "--skill-dir", SKILL])
    assert rc == 1  # refuse to clobber; do not silently overwrite


# --- CLI --check mode ------------------------------------------------------

def test_check_mode_passes_after_write(tmp_path):
    write_args = ["--worktree", str(tmp_path), "--orch-dir", ORCH, "--skill-dir", SKILL]
    assert mwh.main(write_args) == 0
    assert mwh.main(["--check", "--worktree", str(tmp_path)]) == 0


def test_check_mode_fails_when_unwired(tmp_path):
    _write_existing(tmp_path, {"permissions": {"allow": []}})  # no hooks
    assert mwh.main(["--check", "--worktree", str(tmp_path)]) == 1


def test_check_mode_fails_when_no_settings(tmp_path):
    (tmp_path / ".claude").mkdir()
    assert mwh.main(["--check", "--worktree", str(tmp_path)]) == 1
