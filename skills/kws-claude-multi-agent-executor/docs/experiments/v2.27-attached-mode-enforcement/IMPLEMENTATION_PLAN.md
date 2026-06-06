# v2.27 Attached-Mode Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two attached-mode enforcement gaps from the v2.27 design — silent hook-wiring loss when a repo ships its own `.claude/settings.json`, and WARN-only treatment of cost/timing bookkeeping drift — so a degraded `interactive_attached` run can no longer finish silently green.

**Architecture:** A new deterministic script `materialize_worktree_hooks.py` deep-merges the four safety hooks into any existing worktree settings.json and self-asserts the Stop gate is wired (write mode) or re-asserts without writing (`--check`, reused as the Phase-1 Task-1 preflight). `finalize_run.py` elevates `cost_dispatches_zero` and a new all-null-`timing.started` aggregate from WARN to blocking FAIL, each suppressible by an explicit waive flag, so the existing v2.26 Stop gate blocks the drift it currently passes.

**Tech Stack:** Python 3 (stdlib only; reuses `state_set._atomic_write_json`), pytest, bash hooks, Claude Code `settings.json`.

**Design source:** `docs/experiments/v2.27-attached-mode-enforcement/README.md` (ADRs D001, D002).

**Working dir:** all paths below are relative to `skills/kws-claude-multi-agent-executor/`.

**Commit convention:** reference ADRs, e.g. `feat(v2.27): ... (per D001)`. Two-phase is not needed here (no live state.json); normal commits.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `scripts/materialize_worktree_hooks.py` | **Create** | Build canonical hooks block; deep-merge into existing settings.json preserving all other keys; write atomically; assert 4 hooks + Stop gate wired; `--check` mode for preflight |
| `scripts/test_materialize_worktree_hooks.py` | **Create** | Unit tests incl. ReadMates-shape regression + idempotency + Stop-missing `--check` |
| `scripts/finalize_run.py` | Modify | `cost_dispatches_zero` WARN→FAIL (unless waived); new `timing_tracking_absent` aggregate FAIL (unless waived); keep per-task WARN |
| `scripts/test_finalize_run.py` | Modify | Update 2 existing assertions (cost now FAIL); add drift/waive/partial cases |
| `scripts/test_finalization_stop_gate.py` | Modify | Add `DRIFT_ONLY` (blocks) + `DRIFT_WAIVED` (allows) integration fixtures |
| `references/phases/phase-0-setup.md` | Modify | Step 2.5: replace hand-written JSON with script call + hard-halt |
| `references/phases/phase-1-task-cycle.md` | Modify | Add Task-1 `--check` preflight (hard halt) |
| `references/cross-cutting/safety-hooks.md` | Modify | Note settings.json is script-materialized + merged |
| `SKILL.md` | Modify | Guardrails rows; frontmatter version 2.27.0 |
| `HISTORY.md` | Modify | v2.27 timeline entry + §3 experiment index row |
| `ARCHITECTURE.md` | Modify | Hook materialization now script-driven; finalize severity |
| `docs/decision-log.md` | Modify | Index D001, D002 |
| `docs/experiments/README.md` | Modify | Add v2.27 row |
| `docs/experiments/v2.27-attached-mode-enforcement/findings/F01-close-out.md` | **Create** | The 구현문서: what shipped + real before/after replay output |

---

## Task 1: `materialize_worktree_hooks.py` — merge + assert + `--check`

**Files:**
- Create: `scripts/materialize_worktree_hooks.py`
- Test: `scripts/test_materialize_worktree_hooks.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_materialize_worktree_hooks.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/kws-claude-multi-agent-executor/scripts && python3 -m pytest test_materialize_worktree_hooks.py -q`
Expected: collection/import error — `ModuleNotFoundError: No module named 'materialize_worktree_hooks'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/materialize_worktree_hooks.py`:

```python
#!/usr/bin/env python3
"""Materialize + verify the four worktree safety hooks in settings.json (v2.27).

Replaces the hand-written JSON block at Phase 0 Step 2.5. The hand-write had no
merge step, so a source repo that already shipped .claude/settings.json (e.g. a
permissions allowlist) silently lost all four hooks — including the v2.26 Stop
finalization gate (run readmates-host-prep-pace-20260606-003707). This script
deep-merges instead: every existing top-level key is preserved, and the four hook
events we own are injected (winning over any repo entry under those keys, while
other repo-defined hook events survive).

Modes:
  (write)  --worktree <p> --orch-dir <p> --skill-dir <p>
           Read <worktree>/.claude/settings.json (absent -> {}), deep-merge our
           hooks, atomic-write, then self-assert (same checks as --check).
  --check  --worktree <p>
           Assert the four events are present and Stop references
           finalization-stop-gate.sh. No write. Reused as the Phase-1 Task-1
           preflight (improvement #3).

Exit codes:
  0  success / wired
  1  assertion failure, IO error, or unparseable existing settings.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import state_set as ss  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state_set as ss  # type: ignore

REQUIRED_EVENTS = ("PreToolUse", "PostToolUse", "SubagentStop", "Stop")

_PRE_CMD = (
    "CMD=$(echo \"$CLAUDE_TOOL_INPUT\" | jq -r '.command // empty' 2>/dev/null); "
    "if [ -z \"$CMD\" ]; then CMD=\"$CLAUDE_TOOL_INPUT\"; fi; "
    "if echo \"$CMD\" | grep -qE "
    "'rm\\s+-rf\\s+/|git\\s+push\\s+--force\\s+(origin\\s+)?(main|master|trunk)"
    "|DROP\\s+(TABLE|DATABASE|SCHEMA)\\s'; "
    "then echo 'BLOCKED: dangerous command detected' >&2; exit 1; fi"
)


def build_hooks(orch_dir: str, skill_dir: str) -> dict[str, Any]:
    """The canonical four-event hooks block (matches safety-hooks.md)."""
    return {
        "PreToolUse": [{
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": _PRE_CMD}],
        }],
        "PostToolUse": [{
            "matcher": "Edit|Write",
            "hooks": [{"type": "command",
                       "command": f"{orch_dir}/hooks/scan-debug-artifacts.sh"}],
        }],
        "SubagentStop": [{
            "hooks": [{"type": "command",
                       "command": f"{orch_dir}/hooks/check-implementer-output.sh"}],
        }],
        "Stop": [{
            "hooks": [{"type": "command",
                       "command": (f"{orch_dir}/hooks/finalization-stop-gate.sh "
                                   f"{orch_dir}/state.json {skill_dir}/scripts")}],
        }],
    }


def merge_settings(existing: dict[str, Any], hooks_block: dict[str, Any]) -> dict[str, Any]:
    """Preserve every existing top-level key; our four hook events win."""
    merged = dict(existing)
    prior_hooks = existing.get("hooks")
    prior_hooks = prior_hooks if isinstance(prior_hooks, dict) else {}
    merged_hooks = dict(prior_hooks)
    merged_hooks.update(hooks_block)
    merged["hooks"] = merged_hooks
    return merged


def check_problems(settings: dict[str, Any]) -> list[str]:
    """Return a list of wiring problems; empty list means correctly wired."""
    problems: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return ["settings.json has no 'hooks' object"]
    for event in REQUIRED_EVENTS:
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            problems.append(f"missing or empty hook event: {event}")
    stop = hooks.get("Stop")
    if isinstance(stop, list) and stop:
        cmds = " ".join(
            h.get("command", "")
            for entry in stop
            for h in (entry.get("hooks") or [])
            if isinstance(h, dict)
        )
        if "finalization-stop-gate.sh" not in cmds:
            problems.append("Stop hook does not reference finalization-stop-gate.sh")
    return problems


def _settings_path(worktree: str) -> Path:
    return Path(worktree) / ".claude" / "settings.json"


def do_write(worktree: str, orch_dir: str, skill_dir: str) -> int:
    path = _settings_path(worktree)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"refusing to clobber unparseable {path}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(existing, dict):
            print(f"refusing to clobber non-object {path}", file=sys.stderr)
            return 1
    merged = merge_settings(existing, build_hooks(orch_dir, skill_dir))
    ss._atomic_write_json(path, merged)
    problems = check_problems(merged)
    if problems:
        print("post-write hook assertion failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def do_check(worktree: str) -> int:
    path = _settings_path(worktree)
    if not path.is_file():
        print(f"no settings.json at {path}", file=sys.stderr)
        return 1
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"unparseable {path}: {exc}", file=sys.stderr)
        return 1
    problems = check_problems(settings if isinstance(settings, dict) else {})
    if problems:
        print(f"worktree hooks not wired in {path}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="assert hooks are wired; no write")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--orch-dir")
    ap.add_argument("--skill-dir")
    args = ap.parse_args(argv)

    if args.check:
        return do_check(args.worktree)
    if not args.orch_dir or not args.skill_dir:
        ap.error("write mode requires --orch-dir and --skill-dir")
    return do_write(args.worktree, args.orch_dir, args.skill_dir)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd skills/kws-claude-multi-agent-executor/scripts && python3 -m pytest test_materialize_worktree_hooks.py -q`
Expected: all PASS (14 tests).

- [ ] **Step 5: Make executable + commit**

```bash
cd skills/kws-claude-multi-agent-executor
chmod +x scripts/materialize_worktree_hooks.py
git add scripts/materialize_worktree_hooks.py scripts/test_materialize_worktree_hooks.py
git commit -m "feat(v2.27): script-materialized + deep-merged worktree settings.json (per D001)"
```

---

## Task 2: `finalize_run.py` — elevate cost/timing drift to blocking FAIL

**Files:**
- Modify: `scripts/finalize_run.py:45-67` (cost + timing checks)
- Modify: `scripts/test_finalize_run.py` (2 existing assertions + new cases)

- [ ] **Step 1: Update the existing tests + add new ones (write the failing tests)**

In `scripts/test_finalize_run.py`, **change** `test_source_matching_flags_pending_and_completed_at` so `cost_dispatches_zero` is asserted as a FAIL (no longer a WARN):

```python
def test_source_matching_flags_pending_and_completed_at(tmp_path):
    result = fr.evaluate(SOURCE_MATCHING_BAD)
    assert result["passed"] is False
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "verifier_pending_batch" in fails
    assert "completed_at_null" in fails
    assert "cost_dispatches_zero" in fails          # v2.27: WARN -> FAIL
    assert "timing_tracking_absent" in fails        # v2.27: all tasks null-started
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "timing_started_missing" in warns        # per-task WARN retained
```

**Change** `test_cost_waived_suppresses_dispatch_warning` to assert suppression at both levels:

```python
def test_cost_waived_suppresses_dispatch_warning(tmp_path):
    waived = dict(SOURCE_MATCHING_BAD, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    codes = {f["code"] for f in result["findings"]}
    assert "cost_dispatches_zero" not in codes      # suppressed entirely
```

**Append** the new v2.27 cases at the end of the file:

```python
# --- v2.27: cost/timing drift become blocking FAIL (D002) ------------------

# run-2 shape: no cost_ledger, all tasks null timing.started, not waived.
RUN2_DRIFT = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

# run-1 shape: cost waived (dispatches 0 ok), but timing all null -> still FAIL.
RUN1_DRIFT = {
    "status": "COMPLETE",
    "cost_tracking_waived": True,
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

# run-3 shape: dispatches + timing populated -> clean (no false positive).
RUN3_CLEAN = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "a", "completed_at": "b"},
    "cost_ledger": {"totals": {"dispatches": 9}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS",
                   "timing": {"started": "s", "completed": "c"}},
    },
}


def test_run2_drift_fails_on_cost_and_timing(tmp_path):
    result = fr.evaluate(RUN2_DRIFT)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert result["passed"] is False
    assert "cost_dispatches_zero" in fails
    assert "timing_tracking_absent" in fails


def test_run1_drift_fails_on_timing_only_cost_waived(tmp_path):
    result = fr.evaluate(RUN1_DRIFT)
    codes_by_level = {(f["level"], f["code"]) for f in result["findings"]}
    assert result["passed"] is False
    assert ("FAIL", "timing_tracking_absent") in codes_by_level
    assert "cost_dispatches_zero" not in {c for _, c in codes_by_level}  # waived


def test_run3_clean_no_false_positive(tmp_path):
    result = fr.evaluate(RUN3_CLEAN)
    assert result["passed"] is True
    assert [f for f in result["findings"] if f["level"] == "FAIL"] == []


def test_timing_waived_suppresses_aggregate(tmp_path):
    waived = dict(RUN2_DRIFT, timing_tracking_waived=True, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    codes = {f["code"] for f in result["findings"]}
    assert "timing_tracking_absent" not in codes
    assert result["passed"] is True


def test_partial_timing_is_warn_not_fail(tmp_path):
    partial = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 4}},
        "tasks": {
            "task_1": {"status": "COMPLETE", "verifier": "PASS",
                       "timing": {"started": "s", "completed": "c"}},
            "task_2": {"status": "COMPLETE", "verifier": "PASS",
                       "timing": {"completed": "c"}},  # missing started
        },
    }
    result = fr.evaluate(partial)
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "timing_tracking_absent" not in fails  # not ALL null -> no aggregate FAIL
    assert "timing_started_missing" in warns
    assert result["passed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/kws-claude-multi-agent-executor/scripts && python3 -m pytest test_finalize_run.py -q`
Expected: FAIL — `cost_dispatches_zero` still WARN; `timing_tracking_absent` not emitted yet.

- [ ] **Step 3: Implement the severity changes**

In `scripts/finalize_run.py`, replace the cost-ledger block (currently lines 45-50):

```python
    # Run-level: cost ledger dispatches. v2.27: blocking unless explicitly waived.
    if not state.get("cost_tracking_waived"):
        dispatches = ((state.get("cost_ledger") or {}).get("totals") or {}).get("dispatches", 0)
        if not dispatches:
            add("FAIL", "state", "cost_dispatches_zero",
                "cost_ledger.totals.dispatches == 0 (accumulate_cost.py never ran); "
                "set cost_tracking_waived to opt out")
```

In the per-tree loop, the per-task timing WARN stays as-is. **After** the
`for scope, tree in _active_trees(state):` loop body, add an aggregate timing
check. Replace the per-task timing WARN block + add aggregation by rewriting the
loop region (currently lines 52-67) as:

```python
    # Per-tree task checks.
    terminal_total = 0
    terminal_null_started = 0
    for scope, tree in _active_trees(state):
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        for task_id, task in tasks.items():
            status = task.get("status")
            if status not in ("COMPLETE", "SKIPPED"):
                add("FAIL", scope, "task_not_terminal",
                    f"{task_id}: status={status!r} (expected COMPLETE/SKIPPED)")
                continue
            if task.get("verifier") == "PENDING_BATCH":
                add("FAIL", scope, "verifier_pending_batch",
                    f"{task_id}: verifier still PENDING_BATCH (final LOW sweep never wrote back)")
            terminal_total += 1
            timing = task.get("timing") or {}
            if not timing.get("started"):
                terminal_null_started += 1
                add("WARN", scope, "timing_started_missing",
                    f"{task_id}: timing.started absent (per-task duration uncomputable)")

    # v2.27: systemic timing drift. Every terminal task missing timing.started is
    # an unambiguous skip of phase_boundary.py task-start, not a one-off. Blocking
    # unless explicitly waived. Partial misses stay per-task WARN above.
    if (terminal_total > 0 and terminal_null_started == terminal_total
            and not state.get("timing_tracking_waived")):
        add("FAIL", "state", "timing_tracking_absent",
            f"all {terminal_total} terminal tasks have null timing.started "
            "(phase_boundary.py task-start never ran); set timing_tracking_waived to opt out")
```

> Note: `verifier_pending_batch` previously did not `continue`; with the rewrite a
> non-terminal task is counted neither as terminal nor as null-started, and a
> PENDING_BATCH task is still terminal (it has a status of COMPLETE/SKIPPED). This
> preserves the existing `test_source_matching_flags_pending_and_completed_at` and
> `test_multi_plan_chain_checks_each_tree` behavior (both PENDING_BATCH tasks are
> COMPLETE-status, so they still count as terminal).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd skills/kws-claude-multi-agent-executor/scripts && python3 -m pytest test_finalize_run.py -q`
Expected: all PASS (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
cd skills/kws-claude-multi-agent-executor
git add scripts/finalize_run.py scripts/test_finalize_run.py
git commit -m "feat(v2.27): cost/timing drift -> blocking finalize FAIL with waive hatches (per D002)"
```

---

## Task 3: Stop-gate integration — drift now blocks, waive allows

**Files:**
- Modify: `scripts/test_finalization_stop_gate.py`

This proves the existing v2.26 Stop hook (`finalization-stop-gate.sh`, unchanged)
blocks a drift-only run once Task 2's severities land, and allows it when waived.

- [ ] **Step 1: Add the integration fixtures + tests (failing until Task 2 merged — run after Task 2)**

Append to `scripts/test_finalization_stop_gate.py`:

```python
# v2.27: canonical + finalized EXCEPT bookkeeping drift (dispatches 0, all tasks
# null timing.started, not waived). Today this finalizes green; after the v2.27
# finalize severities it must block.
DRIFT_ONLY = {
    "status": "COMPLETE",
    "schema_version": "2",
    "mode": "interactive_attached",
    "timestamps": {"started_at": "2026-06-06T10:00:00Z",
                   "completed_at": "2026-06-06T11:00:00Z"},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "dispatch_config": {"mode": "interactive_attached"},
    "risk_levels": {"task_1": "low", "task_2": "low"},
    "execution_plan": [["task_1"], ["task_2"]],
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
        "task_2": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "c"}},
    },
}

DRIFT_WAIVED = dict(
    DRIFT_ONLY, cost_tracking_waived=True, timing_tracking_waived=True,
)


def test_drift_only_blocks_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, DRIFT_ONLY))
    assert r.returncode == 2, r.stdout
    assert "finalization gate" in r.stderr.lower()


def test_drift_waived_allows_stop(tmp_path):
    r = _run(_hook(tmp_path), _state(tmp_path, DRIFT_WAIVED))
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 2: Run the stop-gate suite**

Run: `cd skills/kws-claude-multi-agent-executor/scripts && python3 -m pytest test_finalization_stop_gate.py -q`
Expected: all PASS (existing 8 + 2 new). `test_drift_only_blocks_stop` confirms the
gate now blocks pure drift; `test_drift_waived_allows_stop` confirms the waive
hatches reach through the gate.

- [ ] **Step 3: Commit**

```bash
cd skills/kws-claude-multi-agent-executor
git add scripts/test_finalization_stop_gate.py
git commit -m "test(v2.27): stop gate blocks bookkeeping drift, honors waive hatches"
```

---

## Task 4: Prose wiring — Step 2.5 script call + Task-1 preflight

**Files:**
- Modify: `references/phases/phase-0-setup.md` (Step 2.5, ~lines 141-174)
- Modify: `references/phases/phase-1-task-cycle.md` (before Task-1 dispatch)
- Modify: `references/cross-cutting/safety-hooks.md`

- [ ] **Step 1: Replace the hand-written JSON in phase-0-setup.md Step 2.5**

Replace the block from **"Write `<worktree_path>/.claude/settings.json`"** through the
JSON fence and the "Substitute …" sentence (lines 141-174) with:

````markdown
   **Materialize + verify `<worktree_path>/.claude/settings.json`** via the
   deterministic script (v2.27 — replaces the prior hand-written JSON, which had
   no merge step and silently dropped hooks when the source repo already shipped a
   `.claude/settings.json`; see D001):
   ```bash
   python3 <skill_dir>/scripts/materialize_worktree_hooks.py \
     --worktree <worktree_path> --orch-dir <orch_dir> --skill-dir <skill_dir>
   ```
   The script reads any existing `<worktree_path>/.claude/settings.json`,
   **deep-merges** the four hook events (preserving the repo's `permissions`,
   `$schema`, and any other hook events), atomic-writes, and self-asserts the four
   events are present with `Stop` wired to `finalization-stop-gate.sh`. **A
   non-zero exit is a hard halt** — do not proceed to Phase 1 with unwired hooks.
   The canonical settings.json shape it emits is documented in
   `references/cross-cutting/safety-hooks.md`.
````

Leave the "What each hook does" bullets (lines 176-180) and the "Why this layering
matters" paragraph (line 182) unchanged.

- [ ] **Step 2: Add the Task-1 preflight in phase-1-task-cycle.md**

Open `references/phases/phase-1-task-cycle.md` and locate the start of Step 1
(Dispatch Implementer). Immediately before the **first** task's dispatch, insert:

````markdown
> **Attached-mode hook preflight (v2.27, improvement #3).** Before dispatching the
> very first task, re-assert the worktree hooks are wired (a cheap belt-and-suspenders
> for the case where Step 2.5 was skipped or the settings.json was tampered):
> ```bash
> python3 <skill_dir>/scripts/materialize_worktree_hooks.py --check --worktree <worktree_path>
> ```
> Non-zero exit → hard halt: re-run the Phase 0 Step 2.5 materialize command, then
> retry. This runs once per run, before Task 1 only.
````

- [ ] **Step 3: Note the script in safety-hooks.md**

In `references/cross-cutting/safety-hooks.md`, under the "## `settings.json` shape"
heading, append after the existing "Substitute …" paragraph:

````markdown
As of v2.27 this file is **not hand-written** — Phase 0 Step 2.5 runs
`scripts/materialize_worktree_hooks.py`, which deep-merges the four events into any
pre-existing repo settings.json (preserving `permissions`/`$schema`/other hook
events) and self-asserts the Stop gate. `--check` re-runs the assertion without
writing and is reused as the Phase-1 Task-1 preflight. The shape above is exactly
what the script emits, so this remains the single source of truth for the shape.
The sub-worktree byte-identical copy (Parallel Sub-Flow P.1) is unchanged — it
copies the already-materialized file.
````

- [ ] **Step 4: Sanity-check the prose references resolve**

Run: `cd skills/kws-claude-multi-agent-executor && grep -rn "materialize_worktree_hooks.py" references/ SKILL.md`
Expected: matches in phase-0-setup.md, phase-1-task-cycle.md, safety-hooks.md (and SKILL.md after Task 5).

- [ ] **Step 5: Commit**

```bash
cd skills/kws-claude-multi-agent-executor
git add references/phases/phase-0-setup.md references/phases/phase-1-task-cycle.md references/cross-cutting/safety-hooks.md
git commit -m "feat(v2.27): wire materialize_worktree_hooks.py into Phase 0/1 prose (per D001)"
```

---

## Task 5: Bookkeeping — version, Guardrails, HISTORY, ARCHITECTURE, indexes, close-out

**Files:**
- Modify: `SKILL.md` (frontmatter + Guardrails table)
- Modify: `HISTORY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/decision-log.md`
- Modify: `docs/experiments/README.md`
- Modify: `docs/experiments/v2.27-attached-mode-enforcement/README.md` (Phase status → done)
- Create: `docs/experiments/v2.27-attached-mode-enforcement/findings/F01-close-out.md`

- [ ] **Step 1: Bump version + Guardrails in SKILL.md**

In `SKILL.md` frontmatter set `version: "2.27.0"` and `updated_at: "2026-06-06"`.

In the Guardrails table, update the **"PostToolUse hook is the only debug-artifact
gate"** neighborhood by adding two rows (after the "Stop hook forces finalization
(v2.26)" row):

```markdown
| **Worktree settings.json is script-materialized + merged (v2.27)** | Phase 0 Step 2.5 runs `scripts/materialize_worktree_hooks.py` (never a hand-written JSON). It deep-merges the four hook events into any pre-existing repo `.claude/settings.json`, preserving `permissions`/`$schema`/other hook events, and self-asserts `Stop` → `finalization-stop-gate.sh`. Non-zero exit = hard halt. `--check` mode re-asserts without writing and runs as the Task-1 preflight. Resolves the run-2 hook-wiring loss (D001). |
| **Cost/timing drift is a blocking finalize FAIL (v2.27)** | `finalize_run.py` treats `cost_ledger.totals.dispatches == 0` (unless `cost_tracking_waived`) and all-terminal-tasks-`timing.started`-null (unless `timing_tracking_waived`) as FAIL, not WARN. The Stop gate then blocks a drifted attached run from finishing silently green. Partial timing misses stay per-task WARN. Blocking forces fix-or-explicit-waive; it does not recover lost data (D002). |
```

- [ ] **Step 2: Add the HISTORY.md v2.27 timeline entry**

At the top of `## §1 Version timeline` (above the v2.26 entry), add:

```markdown
### v2.27.0 — Attached-mode enforcement gaps (2026-06-06)

Two `interactive_attached` runs on 2026-06-06 exposed gaps the v2.26 gates did not
close. **(1) Hook-wiring loss:** Phase 0 Step 2.5 hand-wrote settings.json with no
merge, so `readmates-host-prep-pace-20260606-003707` (repo ships its own
permissions allowlist) wired *zero* hooks — including the v2.26 Stop gate. Replaced
with `scripts/materialize_worktree_hooks.py`, a deterministic deep-merge + Stop-gate
self-assert + `--check` preflight (D001). **(2) Bookkeeping drift:** `dispatches==0`
and all-null `timing.started` were WARN, so `per-role-confidence-calibration-20260606-005019`
finished green despite no cost/timing data. Elevated both to blocking finalize FAIL
with `cost_tracking_waived` / `timing_tracking_waived` escape hatches (D002); the
Stop gate now blocks drift. Experiment: `docs/experiments/v2.27-attached-mode-enforcement/`.
```

Also add a row to the §3 experiment index table:

```markdown
| v2.27 | attached-mode-enforcement | hook-merge script + blocking cost/timing FAIL | shipped |
```

(Match the exact column layout of the existing §3 table.)

- [ ] **Step 3: Sync ARCHITECTURE.md**

Find the section describing the worktree hooks / Phase 0 Step 2.5 (grep
`scan-debug-artifacts` / `finalization-stop-gate` / "settings.json"). Add a sentence
that settings.json is materialized by `scripts/materialize_worktree_hooks.py` (deep
-merge, not hand-write) and that `finalize_run.py` treats cost/timing drift as
blocking FAIL (v2.27). Keep it to 2-3 sentences; do not restructure the doc.

- [ ] **Step 4: Index the ADRs in docs/decision-log.md**

Add two lines (match the file's existing format):

```markdown
- D001 (v2.27) — Script-materialized + deep-merged worktree settings.json — `docs/experiments/v2.27-attached-mode-enforcement/decisions/D001-script-materialized-settings.md`
- D002 (v2.27) — Cost/timing drift elevated to blocking finalize FAIL — `docs/experiments/v2.27-attached-mode-enforcement/decisions/D002-blocking-drift-severity.md`
```

- [ ] **Step 5: Add the v2.27 row to docs/experiments/README.md**

Match the existing index format; link to `v2.27-attached-mode-enforcement/`.

- [ ] **Step 6: Write findings/F01-close-out.md (the 구현문서) with the real replay**

First capture the real before/after (one-off, not committed as a test):

```bash
cd skills/kws-claude-multi-agent-executor/scripts
for d in per-role-confidence-calibration-20260606-005019 \
         readmates-host-prep-pace-20260606-003707 \
         plan-20260604-234058; do
  echo "== $d =="
  python3 finalize_run.py --state "$HOME/.claude/orchestrator/$d/state.json" --check \
    | python3 -c "import sys,json;r=json.load(sys.stdin);print('finalize passed:',r['passed'],sorted({f['level']+':'+f['code'] for f in r['findings']}))"
done
```

Expected AFTER: run-1 `passed: False` (`FAIL:timing_tracking_absent`; cost suppressed
by waive), run-2 `passed: False` (`FAIL:cost_dispatches_zero`, `FAIL:timing_tracking_absent`),
run-3 `passed: True`. Paste the actual output into the close-out.

Create `docs/experiments/v2.27-attached-mode-enforcement/findings/F01-close-out.md`:

```markdown
# F01 — Close-out: attached-mode enforcement gaps (v2.27)

**Date**: 2026-06-06
**Decision**: SHIP

## What shipped

- `scripts/materialize_worktree_hooks.py` (+ 14 tests) — deep-merge worktree
  settings.json hooks, preserve repo keys, self-assert Stop gate, `--check`
  preflight. Closes the run-2 hook-wiring loss (D001).
- `finalize_run.py` — `cost_dispatches_zero` and new `timing_tracking_absent`
  are blocking FAIL unless `cost_tracking_waived` / `timing_tracking_waived`.
  Closes the run-1 silent-green drift (D002).
- Phase 0 Step 2.5 + Phase 1 Task-1 preflight + safety-hooks.md wired to the
  script; SKILL.md Guardrails + version 2.27.0; HISTORY/ARCHITECTURE synced.

## Proof — real before/after replay

Ran today's vs new `finalize_run.py --check` against the three actual runs:

| Run | before | after | gate effect |
|-----|--------|-------|-------------|
| per-role-confidence-…005019 | passed:true | <PASTE> | <PASTE> |
| readmates-host-prep-…003707 | passed:true (schema already FAIL) | <PASTE> | <PASTE> |
| plan-20260604-234058 (clean) | passed:true | <PASTE> | no false positive |

Stop-gate integration (`test_finalization_stop_gate.py`): `DRIFT_ONLY` → exit 2
(blocks), `DRIFT_WAIVED` → exit 0.

## Remaining risk

At Stop time lost timing/cost data is unrecoverable; the gate forces fix-or-waive,
not recovery (D002). The preflight and Step 2.5 are still prose-invoked in attached
mode — the residual "orchestrator skips both" case is bounded by the Stop gate
(which, once hooks are wired, blocks a degraded finish), but a run that skips Step
2.5 entirely wires no Stop gate at all. Mitigation accepted: `--check` preflight +
loud hard-halt is the cheapest non-hook backstop available in attached mode.

## advisor

advisor tool unavailable in the execution environment; recorded per AGENTS.md.
```

- [ ] **Step 7: Update the experiment README Phase status table to done + run full suites**

Set every row of the README's Phase status table to `done`. Then:

```bash
cd skills/kws-claude-multi-agent-executor
python3 -m pytest scripts/ -q
./evals/run.sh
git diff --check
```
Expected: pytest all green; evals pass; `git diff --check` clean.

- [ ] **Step 8: Commit**

```bash
cd skills/kws-claude-multi-agent-executor
git add SKILL.md HISTORY.md ARCHITECTURE.md docs/decision-log.md docs/experiments/README.md docs/experiments/v2.27-attached-mode-enforcement/
git commit -m "docs(v2.27): version bump 2.27.0 + Guardrails/HISTORY/ARCHITECTURE/close-out (per D001,D002)"
```

---

## Self-Review

**Spec coverage:**
- #1 merge + assert → Task 1 (`materialize_worktree_hooks.py`, `merge_settings`, `check_problems`, ReadMates regression test).
- #3 preflight → Task 1 `--check` mode + Task 4 Step 2 Phase-1 wiring.
- #2 severity → Task 2 (`finalize_run.py`) + Task 3 (stop-gate integration).
- Prose wiring → Task 4. Bookkeeping/docs → Task 5. Real replay proof → Task 5 Step 6.

**Placeholder scan:** `<PASTE>` cells in F01 are intentional — they are filled with
real command output captured in Task 5 Step 6, not left blank. All code steps show
complete code.

**Type/name consistency:** `build_hooks(orch_dir, skill_dir)`, `merge_settings(existing,
hooks_block)`, `check_problems(settings)`, `do_write`/`do_check`, `main(argv)`,
`REQUIRED_EVENTS` — used identically across Task 1 code and tests. Finding codes
`cost_dispatches_zero`, `timing_tracking_absent`, `timing_started_missing` and flags
`cost_tracking_waived`, `timing_tracking_waived` match across finalize_run.py, its
tests, the stop-gate tests, and the Guardrails rows.
