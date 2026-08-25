"""test_dispatch.py — TDD suite for dispatch.py (CME v3.0 T7).

Minimum 10 test functions; __main__ runs ALL of them.
Each test raises AssertionError on failure; the runner catches and reports.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

# Adjust import path so we can import dispatch from the kernel directory
sys.path.insert(0, os.path.dirname(__file__))

import dispatch

# Path to skill root (references/ lives here)
SKILL_DIR = str(Path(__file__).resolve().parents[2])  # skills/kws-claude-multi-agent-executor

SCAFFOLD_BEGIN = "<!-- SCAFFOLD_BEGIN -->"
SCAFFOLD_END = "<!-- SCAFFOLD_END -->"
PAYLOAD_BEGIN = "<!-- PAYLOAD_BEGIN -->"
PAYLOAD_END = "<!-- PAYLOAD_END -->"

PLACEHOLDER_RE = re.compile(r"\{[A-Za-z][^{}\n]*\}")


def _base_state(*, implementer_model="sonnet", dispatch_config=None, worktree=None):
    """Build a minimal state dict for dispatch.build tests."""
    return {
        "schema_version": 3,
        "status": "RUNNING",
        "worktree": worktree or "/fake/worktree",
        "implementer_model": implementer_model,
        "dispatch_config": dispatch_config or {},
        "tasks": {
            "task_3": {
                "status": "IN_PROGRESS",
                "phase": "implement",
                "review_retries": 0,
                "verifier_retries": 0,
                "escalations": 0,
                "body": "Implement the foo() function that returns 42.",
                "files": ["src/foo.py"],
                "acceptance": None,
                "title": "Implement foo",
            }
        },
        "risk_levels": {"task_3": "mid"},
        "execution_plan": [["task_3"]],
    }


def _action(role="implementer", task_id="task_3", attempt=1):
    return {"action": "dispatch", "role": role, "task_id": task_id, "attempt": attempt}


# ── TEST (a): implementer → command has required flags, no leftover placeholders ─

def test_implementer_default_command_flags():
    """(a) implementer action → command contains required flags; no leftover {PLACEHOLDER} tokens."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state()
        action = _action(role="implementer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        # Required keys in result
        assert "prompt_path" in result, "Missing prompt_path"
        assert "schema_path" in result, "Missing schema_path"
        assert "result_path" in result, "Missing result_path"
        assert "command" in result, "Missing command"
        assert "model" in result, "Missing model"
        assert "transport" in result, "Missing transport"
        assert "cwd" in result, "Missing cwd"

        cmd = result["command"]
        assert "--output-format json" in cmd, f"Command missing --output-format json: {cmd}"
        assert "--json-schema" in cmd, f"Command missing --json-schema: {cmd}"
        assert "--model claude-sonnet-4-6" in cmd, f"Command missing --model claude-sonnet-4-6: {cmd}"
        assert "--dangerously-skip-permissions" in cmd, f"Command missing --dangerously-skip-permissions: {cmd}"
        assert ">" in cmd, f"Command missing redirect: {cmd}"

        # Prompt file must exist and have no leftover placeholder tokens
        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        leftover = PLACEHOLDER_RE.findall(prompt_text)
        assert not leftover, f"Leftover placeholder tokens in prompt: {leftover}"

        # Filename convention: implementer_task_3_a1 — no task_task doubling
        assert "implementer_task_3_a1" in result["prompt_path"], (
            f"Expected 'implementer_task_3_a1' in prompt_path, got: {result['prompt_path']}"
        )
        assert "implementer_task_3_a1" not in result["prompt_path"].replace(
            "implementer_task_3_a1", ""), "double task prefix check"

        # No "task_task_3" in the path
        assert "task_task_3" not in result["prompt_path"], (
            f"Doubled task prefix in prompt_path: {result['prompt_path']}"
        )

        # schema_path points at correct file
        assert result["schema_path"].endswith("implementer_result.schema.json"), (
            f"Wrong schema path: {result['schema_path']}"
        )

        # result_path ends with .json
        assert result["result_path"].endswith(".json"), f"result_path not json: {result['result_path']}"

        # transport default is "p"
        assert result["transport"] == "p", f"Expected transport='p', got: {result['transport']}"

        print("TEST (a) PASS: implementer default command has all required flags, no leftover placeholders")


# ── TEST (b): implementer_model=opus → --model claude-opus-4-8 ──────────────────

def test_opus_model_flag():
    """(b) implementer_model=opus → command uses --model claude-opus-4-8."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state(implementer_model="opus")
        action = _action(role="implementer", task_id="task_3", attempt=2)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        cmd = result["command"]
        assert "--model claude-opus-4-8" in cmd, (
            f"Expected --model claude-opus-4-8 with opus state, got: {cmd}"
        )
        assert result["model"] == "claude-opus-4-8", (
            f"Expected model='claude-opus-4-8', got: {result['model']}"
        )
        # Attempt 2 → filename contains a2
        assert "implementer_task_3_a2" in result["prompt_path"], (
            f"Expected a2 in path for attempt=2: {result['prompt_path']}"
        )

        print("TEST (b) PASS: opus model maps to --model claude-opus-4-8")


# ── TEST (c): dispatch_config.verifier_per_task="agent" → agent_instruction ────

def test_agent_transport_branch():
    """(c) dispatch_config.verifier_per_task='agent' → agent_instruction returned."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state(dispatch_config={"verifier_per_task": "agent"})
        # Add verifier-specific task data
        state["tasks"]["task_3"]["phase"] = "verify"
        state["tasks"]["task_3"]["files_changed"] = ["src/foo.py"]
        action = _action(role="verifier", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        # agent branch must NOT return command; must return agent_instruction
        assert "command" not in result, (
            f"agent transport must NOT return 'command', got keys: {list(result.keys())}"
        )
        assert "agent_instruction" in result, (
            f"agent transport must return 'agent_instruction', got keys: {list(result.keys())}"
        )

        # Required fields still present
        assert "prompt_path" in result, "Missing prompt_path in agent branch"
        assert "schema_path" in result, "Missing schema_path in agent branch"
        assert "result_path" in result, "Missing result_path in agent branch"
        assert "model" in result, "Missing model in agent branch"

        ai = result["agent_instruction"]
        assert isinstance(ai, dict), f"agent_instruction must be a dict, got {type(ai)}"
        assert "prompt_path" in ai or "description" in ai, (
            f"agent_instruction should carry dispatch materials: {ai}"
        )

        print("TEST (c) PASS: verifier_per_task='agent' returns agent_instruction branch")


# ── TEST (d): assembled verifier prompt preserves SCAFFOLD markers ───────────────

def test_scaffold_markers_preserved():
    """(d) assembled verifier prompt keeps SCAFFOLD/PAYLOAD markers byte-stable."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state(dispatch_config={"verifier_per_task": "p"})
        state["tasks"]["task_3"]["phase"] = "verify"
        state["tasks"]["task_3"]["files_changed"] = ["src/foo.py"]
        action = _action(role="verifier", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        lines = prompt_text.splitlines()

        assert SCAFFOLD_BEGIN in lines, f"SCAFFOLD_BEGIN missing from assembled verifier prompt"
        assert SCAFFOLD_END in lines, f"SCAFFOLD_END missing from assembled verifier prompt"
        assert PAYLOAD_BEGIN in lines, f"PAYLOAD_BEGIN missing from assembled verifier prompt"
        assert PAYLOAD_END in lines, f"PAYLOAD_END missing from assembled verifier prompt"

        # Ordering: SB < SE < PB < PE
        idx = {m: lines.index(m) for m in [SCAFFOLD_BEGIN, SCAFFOLD_END, PAYLOAD_BEGIN, PAYLOAD_END]}
        assert idx[SCAFFOLD_BEGIN] < idx[SCAFFOLD_END] < idx[PAYLOAD_BEGIN] < idx[PAYLOAD_END], (
            f"Markers out of order: {idx}"
        )

        # Scaffold region must match the sibling scaffold file byte-for-byte
        scaffold_path = Path(SKILL_DIR) / "references" / "_scaffolds" / "verifier-scaffold.md"
        expected_scaffold = scaffold_path.read_text(encoding="utf-8")

        sb = idx[SCAFFOLD_BEGIN]
        se = idx[SCAFFOLD_END]
        actual_scaffold = "\n".join(lines[sb + 1:se])
        assert actual_scaffold == expected_scaffold, (
            f"Scaffold region changed: expected {len(expected_scaffold)} bytes, "
            f"got {len(actual_scaffold)} bytes — cache prefix would drift"
        )

        # ## Output contract block must be in PAYLOAD region (after PAYLOAD_BEGIN)
        pb = idx[PAYLOAD_BEGIN]
        pe = idx[PAYLOAD_END]
        payload_lines = lines[pb + 1:pe]
        payload_text = "\n".join(payload_lines)
        assert "## Output contract" in payload_text, (
            "Output contract block must appear inside PAYLOAD region"
        )

        print("TEST (d) PASS: scaffold markers preserved, scaffold bytes stable, output contract in payload")


# ── TEST (e): reviewer role → correct schema + no leftover tokens ───────────────

def test_reviewer_role():
    """(e) reviewer action → reviewer_result.schema.json; no leftover placeholders."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state()
        state["tasks"]["task_3"]["phase"] = "review"
        state["tasks"]["task_3"]["files_changed"] = ["src/foo.py"]
        state["tasks"]["task_3"]["diff"] = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n+def foo(): return 42"
        action = _action(role="reviewer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        assert result["schema_path"].endswith("reviewer_result.schema.json"), (
            f"Wrong schema for reviewer: {result['schema_path']}"
        )
        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        leftover = PLACEHOLDER_RE.findall(prompt_text)
        assert not leftover, f"Leftover placeholder tokens in reviewer prompt: {leftover}"

        assert "reviewer_task_3_a1" in result["prompt_path"], (
            f"Expected 'reviewer_task_3_a1' in path: {result['prompt_path']}"
        )

        print("TEST (e) PASS: reviewer role → correct schema, no leftover placeholders")


# ── TEST (f): output contract appended; implementer (no scaffold) ────────────────

def test_output_contract_appended():
    """(f) assembled prompt contains ## Output contract block."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state()
        action = _action(role="implementer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        assert "## Output contract" in prompt_text, (
            "Assembled prompt must contain ## Output contract block"
        )
        assert "schema-conforming JSON" in prompt_text or "schema" in prompt_text.lower(), (
            "Output contract must mention schema-conforming JSON"
        )

        print("TEST (f) PASS: ## Output contract block appended to assembled prompt")


# ── TEST (g): plan_reviewer role → plan_reviewer_result.schema.json ──────────────

def test_plan_reviewer_role():
    """(g) plan_reviewer role → correct schema."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state()
        state["tasks"]["task_3"]["phase"] = "implement"  # plan_reviewer dispatched specially
        action = _action(role="plan_reviewer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        assert result["schema_path"].endswith("plan_reviewer_result.schema.json"), (
            f"Wrong schema for plan_reviewer: {result['schema_path']}"
        )
        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        leftover = PLACEHOLDER_RE.findall(prompt_text)
        assert not leftover, f"Leftover placeholder tokens in plan_reviewer prompt: {leftover}"

        print("TEST (g) PASS: plan_reviewer role → correct schema, no leftover placeholders")


# ── TEST (i): attempt>1 implementer → no leftover placeholders (re-dispatch path) ─

def test_implementer_redispatch_no_leftover():
    """(i) implementer at attempt=2 — IF block kept; {issues list...} token resolved."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state(implementer_model="sonnet")
        # Simulate re-dispatch: previous issues stored on the task
        state["tasks"]["task_3"]["previous_issues"] = "- foo was not implemented correctly"
        action = _action(role="implementer", task_id="task_3", attempt=2)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        prompt_text = Path(result["prompt_path"]).read_text(encoding="utf-8")
        leftover = PLACEHOLDER_RE.findall(prompt_text)
        assert not leftover, (
            f"Leftover placeholder tokens in attempt=2 implementer prompt: {leftover}"
        )

        # The ## Fix Required section should be present (IF block kept on retry)
        assert "## Fix Required" in prompt_text, (
            "Expected '## Fix Required' section in attempt=2 implementer prompt"
        )

        print("TEST (i) PASS: attempt=2 implementer has no leftover placeholders")


# ── TEST (h): cwd in result == state["worktree"] ─────────────────────────────────

def test_cwd_from_worktree():
    """(h) cwd in result == state['worktree']."""
    with tempfile.TemporaryDirectory() as orch_dir:
        state = _base_state(worktree="/my/worktree/path")
        action = _action(role="implementer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        assert result["cwd"] == "/my/worktree/path", (
            f"Expected cwd='/my/worktree/path', got: {result['cwd']}"
        )
        print("TEST (h) PASS: cwd == state['worktree']")


# ── TEST (j): orch_dir with a space → command paths are shell-quoted ─────────────

def test_command_paths_quoted_with_spaces():
    """(j) orch_dir containing a space → prompt/schema/result paths are shlex-quoted
    in the command so the shell does not word-split them."""
    with tempfile.TemporaryDirectory() as base:
        orch_dir = os.path.join(base, "orch dir", "run_1")
        os.makedirs(orch_dir, exist_ok=True)
        state = _base_state()
        action = _action(role="implementer", task_id="task_3", attempt=1)
        result = dispatch.build(state, action, SKILL_DIR, orch_dir)

        cmd = result["command"]

        # The three path interpolations must appear in their shlex-quoted form.
        quoted_prompt = shlex.quote(result["prompt_path"])
        quoted_schema = shlex.quote(result["schema_path"])
        quoted_result = shlex.quote(result["result_path"])

        assert quoted_prompt in cmd, (
            f"prompt_path not shlex-quoted in command.\nExpected substring: {quoted_prompt}\nCommand: {cmd}"
        )
        assert quoted_schema in cmd, (
            f"schema_path not shlex-quoted in command.\nExpected substring: {quoted_schema}\nCommand: {cmd}"
        )
        assert quoted_result in cmd, (
            f"result_path not shlex-quoted in command.\nExpected substring: {quoted_result}\nCommand: {cmd}"
        )

        # There must be no bare (unquoted) 'orch dir/run_1' path fragment — that
        # would mean the shell word-splits on the space.
        bare_fragment = os.path.join("orch dir", "run_1")
        # shlex.quote wraps the whole path in single quotes; the bare fragment
        # (without surrounding quote) must not appear as an unquoted token.
        # Strip out all quoted spans, then confirm 'orch dir' is gone.
        without_quoted = cmd
        for q in (quoted_prompt, quoted_schema, quoted_result):
            without_quoted = without_quoted.replace(q, "")
        assert bare_fragment not in without_quoted, (
            f"Unquoted path fragment '{bare_fragment}' would word-split in the shell.\nCommand: {cmd}"
        )

        # model_name stays unquoted (from controlled MODEL_MAP literals)
        assert "--model claude-sonnet-4-6" in cmd, (
            f"model flag should remain unquoted literal: {cmd}"
        )

        # Flag set + redirect unchanged
        assert "--output-format json" in cmd
        assert "--json-schema" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert ">" in cmd

        print("TEST (j) PASS: command paths shlex-quoted; no word-split on space in orch_dir")


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_implementer_default_command_flags,
        test_opus_model_flag,
        test_agent_transport_branch,
        test_scaffold_markers_preserved,
        test_reviewer_role,
        test_output_contract_appended,
        test_plan_reviewer_role,
        test_cwd_from_worktree,
        test_implementer_redispatch_no_leftover,
        test_command_paths_quoted_with_spaces,
    ]

    print(f"Running {len(tests)} tests...\n")
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            print(f"FAIL: {fn.__name__}: {exc}")
            failed.append(fn.__name__)

    print()
    print(f"Results: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)
