# CPE Run-State Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative CPE repair flow that converts read-only run-quality followups into an explicit dry-run repair plan and can mark one stale, impossible-to-resume run as blocked after validation.

**Architecture:** Keep `inspect_runs.py` read-only and add a separate `repair_runs.py` script that consumes the same CPE state layout. Dry-run scans recent runs, classifies repair candidates, and writes deterministic JSON or JSONL; apply reloads one run, verifies path and state invariants, validates before and after the patch, then atomically replaces only that run's `state.json`.

**Tech Stack:** Python 3 standard library, existing CPE state validator in `scripts/validate_state.py`, existing run-inspection helpers in `scripts/inspect_runs.py`, deterministic eval scripts under `evals/`, Markdown docs.

## Global Constraints

- Do not delete worktrees or run directories.
- Do not mutate finished successful runs.
- Do not repair arbitrary `validate_state.py` failures.
- Keep `inspect_runs.py` read-only.
- Default `repair_runs.py` mode is dry-run.
- `--apply` requires both `--run-id` and `--action`; broad apply is forbidden.
- Only `mark-blocked-stale` is apply-safe in this implementation.
- No mutation outside `~/.codex/orchestrator/<run_id>/state.json`.
- No mutation when `state.run_id` differs from the directory name.
- No mutation when the state path does not end with `.codex/orchestrator/<run_id>/state.json`.
- No mutation when pre-repair validation fails.
- No mutation when post-repair validation fails.
- Write state with temp-file plus atomic replace.
- Print a before/after summary and validation status after apply.
- Update CPE docs and deterministic evals in the same implementation branch.

---

## Source Contract

- Design spec: `docs/superpowers/specs/2026-06-23-cpe-repair-runs-design.md`
- Skill change protocol: `skills/kws-codex-plan-executor/references/change-protocol.md`
- Existing inspection script: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Existing state validator: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Existing eval patterns: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py` and `skills/kws-codex-plan-executor/evals/check_state_schema.py`

## File Structure

- Create `skills/kws-codex-plan-executor/scripts/repair_runs.py`
  - Owns CLI parsing, repair-plan classification, safe apply, JSON/JSONL rendering, output file writes, and atomic state replacement.
  - Imports `inspect_runs` for read-only scan helpers and `validate_state` for state validation.
- Create `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
  - Owns all deterministic repair-flow fixtures and assertions.
  - Uses temp `CODEX_HOME` directories and subprocess execution of `scripts/repair_runs.py`.
- Modify `skills/kws-codex-plan-executor/evals/run.sh`
  - Adds `check_repair_runs.py` to the deterministic eval list near `check_inspect_runs.py`.
- Modify `skills/kws-codex-plan-executor/SKILL.md`
  - Documents the repair flow as a follow-up to read-only inspection.
- Modify `skills/kws-codex-plan-executor/README.md`
  - Adds dry-run and single-action apply examples.
- Modify `skills/kws-codex-plan-executor/references/state-schema.md`
  - Documents blocked stale repair fields.
- Modify `skills/kws-codex-plan-executor/docs/state-and-logging.md`
  - Explains dry-run/apply safety and non-deletion boundary.
- Modify `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - Lists `check_repair_runs.py`.
- Modify `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
  - Replaces the v2.22 read-only limitation with the new safe-repair boundary.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`
  - Records the behavior change.
- Modify `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json`
  - Refresh after code/docs structure changes using `graphify update . --force`.

## Task Graph

```yaml waygent-task
id: T1
title: Add repair-flow eval coverage
dependencies: []
file_claims:
  - path: skills/kws-codex-plan-executor/evals/check_repair_runs.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/run.sh
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py
    expected: exits non-zero before repair_runs.py exists, then exits zero after T2 and T3
risks:
  - Fixture states must satisfy validate_state before repair so failures test repair policy, not invalid setup.
```

```yaml waygent-task
id: T2
title: Implement dry-run repair planning
dependencies: [T1]
file_claims:
  - path: skills/kws-codex-plan-executor/scripts/repair_runs.py
    mode: owned
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py
    expected: dry-run, schema-drift, no-candidate, and JSONL checks pass; apply checks still fail until T3
risks:
  - Classification must not depend on prose summaries when explicit followup markers exist.
```

```yaml waygent-task
id: T3
title: Implement validated single-run apply
dependencies: [T2]
file_claims:
  - path: skills/kws-codex-plan-executor/scripts/repair_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_repair_runs.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py
    expected: all repair eval checks pass
risks:
  - Dry-run output can become stale before apply, so apply must reload and reclassify the target run.
```

```yaml waygent-task
id: T4
title: Update CPE docs and history
dependencies: [T3]
file_claims:
  - path: skills/kws-codex-plan-executor/SKILL.md
    mode: edit
  - path: skills/kws-codex-plan-executor/README.md
    mode: edit
  - path: skills/kws-codex-plan-executor/references/state-schema.md
    mode: edit
  - path: skills/kws-codex-plan-executor/docs/state-and-logging.md
    mode: edit
  - path: skills/kws-codex-plan-executor/docs/evals-and-verification.md
    mode: edit
  - path: skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md
    mode: edit
  - path: skills/kws-codex-plan-executor/HISTORY.md
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && rg 'repair_runs|mark-blocked-stale|stale blocked repair' SKILL.md README.md references docs HISTORY.md
    expected: every changed contract file contains the repair boundary
risks:
  - Docs must describe the non-deletion boundary clearly so operators do not infer cleanup behavior.
```

```yaml waygent-task
id: T5
title: Run full verification and refresh Graphify
dependencies: [T4]
file_claims:
  - path: graphify-out/GRAPH_REPORT.md
    mode: edit
  - path: graphify-out/graph.json
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && ./evals/run.sh
    expected: exits zero
  - command: cd /Users/kws/source/private/Archive && git diff --check
    expected: no output and exit zero
  - command: cd /Users/kws/source/private/Archive && python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --update-ran --output /tmp/cpe-repair-runs-graphify-audit.json
    expected: JSON reports fresh=true and no errors
risks:
  - Graphify output can change from source indexing rather than product behavior; review the diff before staging.
```

## Task 1: Add Repair-Flow Eval Coverage

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Read: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`
- Read: `skills/kws-codex-plan-executor/evals/check_state_schema.py`

**Interfaces:**
- Consumes: CLI contract for `scripts/repair_runs.py`.
- Produces: deterministic fixture helpers:
  - `write_state(codex_home: Path, run_id: str, *, outcome: str | None = None, create_worktree: bool = True, existing_blocker: bool = False, schema_drift: bool = False) -> Path`
  - `run_repair(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]`
  - `run_repair_jsonl(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]`

- [ ] **Step 1: Create the failing repair eval**

Add `skills/kws-codex-plan-executor/evals/check_repair_runs.py` with these concrete fixtures and assertions:

```python
#!/usr/bin/env python3
"""Deterministic checks for conservative CPE run repair."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_runs.py"


def iso(index: int) -> str:
    return f"2026-06-23T00:00:{index:02d}Z"


def base_state(codex_home: Path, run_id: str, *, outcome: str | None = None, create_worktree: bool = True) -> dict:
    run_dir = codex_home / "orchestrator" / run_id
    worktree = codex_home / "worktrees" / run_id
    if create_worktree:
        worktree.mkdir(parents=True, exist_ok=True)
    return {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "workspace": str(worktree),
        "plan": "docs/plan.md",
        "branch": f"codex/{run_id}",
        "worktree": str(worktree),
        "execution_worktree": str(worktree),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "context_snapshot_path": str(run_dir / "context.json"),
        "context_basis_hash": "0" * 64,
        "spec_manifest_path": str(run_dir / "spec_manifest.json"),
        "task_packet_dir": str(run_dir / "task_packets"),
        "current_task_packet_path": str(run_dir / "task_packets" / "task_0.json"),
        "decisions_register": [],
        "preflight_warnings": [],
        "last_completed_task": None,
        "last_completed_at": None,
        "compaction": {"points": [], "last_compaction_after_task": None, "context_drop_count": 0},
        "current_task": "task_0",
        "current_phase": "task_loop",
        "lifecycle_outcome": outcome,
        "handoff_reason": "" if outcome is None else "Run ended by fixture.",
        "completion_audit": None,
        "subagents_requested": False,
        "subagent_runs": [],
        "tasks": {
            "task_0": {
                "status": "in_progress",
                "contract": {
                    "scope": "fixture",
                    "files_to_inspect": ["docs/plan.md"],
                    "allowed_edits": ["docs/example.md"],
                    "forbidden_edits": [".codex/**"],
                    "acceptance_command_or_honest_substitute": "python3 evals/check_repair_runs.py",
                },
            }
        },
        "risk_levels": {},
        "review_issue_keys": [],
        "verification": [],
        "cache_strategy": {
            "mode": "interactive-default",
            "stable_prefix_policy": "static-first-hot-tail",
            "provider_cache_control": "unavailable",
            "prompt_audit_version": "1",
        },
        "cache_observations": [],
        "prompt_audit": None,
        "graphify_audit": None,
        "dispatch_decisions": [],
        "session_owned_resources": [],
        "last_checkpoint": None,
        "timestamps": {"started_at": iso(0), "updated_at": iso(1), "completed_at": None},
        "context_health": {
            "status": "yellow",
            "next_action": "Continue task_0.",
            "handoff_ready": False,
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
        },
    }


def write_state(
    codex_home: Path,
    run_id: str,
    *,
    outcome: str | None = None,
    create_worktree: bool = True,
    existing_blocker: bool = False,
    schema_drift: bool = False,
) -> Path:
    state = base_state(codex_home, run_id, outcome=outcome, create_worktree=create_worktree)
    run_dir = codex_home / "orchestrator" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task_packets").mkdir(parents=True, exist_ok=True)
    if existing_blocker:
        state["current_blocker"] = {
            "category": "plan_contract_gap",
            "summary": "Existing operator blocker.",
            "recoverable": True,
            "next_action_kind": "operator_decision",
        }
    if outcome == "finished":
        state["current_phase"] = "complete"
        state["handoff_reason"] = ""
        state["completion_audit"] = {
            "passed": True,
            "prompt_to_artifact_checklist": ["fixture complete"],
            "verification_evidence": ["fixture evidence"],
        }
        state["tasks"]["task_0"]["status"] = "completed"
        state["tasks"]["task_0"]["unit_manifest"] = {
            "unit_type": "implementation",
            "context_mode": "sliced",
            "tool_policy": "implementation",
            "artifact_policy": "repo",
            "required_skills": [],
            "allowed_write_globs": ["docs/example.md"],
            "forbidden_write_globs": [".codex/**"],
            "max_context_chars": 1000,
        }
        state["timestamps"]["completed_at"] = iso(2)
        state["context_health"]["handoff_ready"] = True
        state["context_health"]["next_action"] = "No action."
    if schema_drift:
        state.pop("tasks")
    state_path = run_dir / "state.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps({"context_budget": {"status": "green"}}), encoding="utf-8")
    old_time = time.time() - 7200
    os.utime(state_path, (old_time, old_time))
    return state_path


def run_repair(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = codex_home / "repair-plan.json"
    cmd = [sys.executable, str(SCRIPT), "--codex-home", str(codex_home), "--recent", "20", "--stale-hours", "0", "--output", str(output), *extra]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def run_repair_jsonl(codex_home: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    output = codex_home / "repair-plan.jsonl"
    cmd = [sys.executable, str(SCRIPT), "--codex-home", str(codex_home), "--recent", "20", "--stale-hours", "0", "--jsonl", "--output", str(output), *extra]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()] if output.is_file() else []
    return result, rows


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "stale-missing", create_worktree=False)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["dry_run_stale_missing_worktree"] = (
            result.returncode == 0
            and data.get("dry_run") is True
            and data.get("summary", {}).get("candidate_count") == 1
            and candidate.get("recommended_action") == "mark-blocked-stale"
            and candidate.get("apply_safe") is True
            and "stale_non_terminal_run" in candidate.get("detected_followups", [])
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["dry_run_stale_missing_worktree"]:
            failures.append("dry-run should report one apply-safe stale missing-worktree candidate without mutating state")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "apply-stale", create_worktree=False)
        result, _ = run_repair(home, "--run-id", "apply-stale", "--action", "mark-blocked-stale", "--apply")
        repaired = json.loads(state_path.read_text(encoding="utf-8"))
        checks["apply_mark_blocked_stale"] = (
            result.returncode == 0
            and repaired.get("lifecycle_outcome") == "blocked"
            and repaired.get("current_phase") == "recover"
            and repaired.get("current_blocker", {}).get("category") == "state_integrity_drift"
            and repaired.get("current_blocker", {}).get("recoverable") is True
            and repaired.get("context_health", {}).get("handoff_ready") is True
            and repaired.get("timestamps", {}).get("completed_at") is not None
        )
        if not checks["apply_mark_blocked_stale"]:
            failures.append("apply should mark one stale missing-worktree run as blocked and handoff-ready")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "finished-cleaned", outcome="finished", create_worktree=False)
        result, data = run_repair(home, "--run-id", "finished-cleaned", "--action", "mark-blocked-stale", "--apply")
        candidate = (data.get("candidates") or [{}])[0]
        checks["finished_missing_worktree_not_applied"] = (
            result.returncode != 0
            and candidate.get("recommended_action") == "acknowledge-cleaned-worktree"
            and candidate.get("apply_safe") is False
        )
        if not checks["finished_missing_worktree_not_applied"]:
            failures.append("finished missing-worktree runs should be reported but never marked blocked")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "schema-drift", create_worktree=False, schema_drift=True)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["schema_drift_blocks_repair"] = (
            result.returncode == 0
            and candidate.get("recommended_action") == "manual-review-required"
            and candidate.get("apply_safe") is False
            and "state_schema_drift" in candidate.get("detected_followups", [])
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["schema_drift_blocks_repair"]:
            failures.append("schema drift should force manual review and no mutation")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "existing-blocker", create_worktree=False, existing_blocker=True)
        before = state_path.read_text(encoding="utf-8")
        result, data = run_repair(home)
        candidate = (data.get("candidates") or [{}])[0]
        checks["existing_blocker_blocks_overwrite"] = (
            result.returncode == 0
            and candidate.get("recommended_action") == "manual-review-required"
            and candidate.get("apply_safe") is False
            and "existing current_blocker" in candidate.get("reason", "")
            and state_path.read_text(encoding="utf-8") == before
        )
        if not checks["existing_blocker_blocks_overwrite"]:
            failures.append("existing current_blocker should not be overwritten")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        state_path = write_state(home, "unsafe-path", create_worktree=False)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["state_path"] = str(home / "outside" / "unsafe-path" / "state.json")
        state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result, _ = run_repair(home, "--run-id", "unsafe-path", "--action", "mark-blocked-stale", "--apply")
        current = json.loads(state_path.read_text(encoding="utf-8"))
        checks["unsafe_state_path_blocks_apply"] = result.returncode != 0 and current.get("lifecycle_outcome") is None
        if not checks["unsafe_state_path_blocks_apply"]:
            failures.append("unsafe state_path invariant should block apply")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "active-worktree", create_worktree=True)
        result, data = run_repair(home, "--stale-hours", "24")
        checks["no_candidates"] = (
            result.returncode == 0
            and data.get("candidates") == []
            and data.get("summary", {}).get("candidate_count") == 0
            and data.get("summary", {}).get("apply_safe_count") == 0
        )
        if not checks["no_candidates"]:
            failures.append("clean active non-stale runs should produce an empty repair plan")

    with tempfile.TemporaryDirectory(prefix="cpe-repair-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "jsonl-one", create_worktree=False)
        write_state(home, "jsonl-two", create_worktree=False, existing_blocker=True)
        result, rows = run_repair_jsonl(home)
        checks["jsonl_output"] = (
            result.returncode == 0
            and len(rows) == 2
            and {row.get("run_id") for row in rows} == {"jsonl-one", "jsonl-two"}
        )
        if not checks["jsonl_output"]:
            failures.append("jsonl output should emit one valid JSON object per candidate line")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the new eval to verify RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_repair_runs.py
```

Expected: non-zero exit with stderr containing a Python message that `scripts/repair_runs.py` cannot be opened, because the implementation script does not exist yet.

- [ ] **Step 3: Wire the eval into the deterministic harness**

In `skills/kws-codex-plan-executor/evals/run.sh`, insert this line immediately after `python3 "$EVAL_DIR/check_inspect_runs.py" >/dev/null`:

```bash
python3 "$EVAL_DIR/check_repair_runs.py" >/dev/null
```

- [ ] **Step 4: Commit Task 1**

Run:

```bash
git add skills/kws-codex-plan-executor/evals/check_repair_runs.py skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test(cpe): cover run repair flow"
```

## Task 2: Implement Dry-Run Repair Planning

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/repair_runs.py`
- Read: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Read: `skills/kws-codex-plan-executor/scripts/validate_state.py`

**Interfaces:**
- Consumes:
  - `inspect_runs.inspect_all_runs(codex_home: Path, recent: int | None, quality_report: bool, stale_hours: float, validate: bool) -> dict`
  - `inspect_runs.load_state(path: Path) -> dict | None`
  - `inspect_runs.redacted(path_text: object, codex_home: Path) -> str`
  - `validate_state.validate(data: dict) -> list[str]`
- Produces:
  - `build_plan(codex_home: Path, recent: int | None, stale_hours: float) -> dict[str, Any]`
  - `classify_record(record: dict[str, Any], codex_home: Path) -> dict[str, Any] | None`
  - `render_plan(plan: dict[str, Any], jsonl: bool) -> str`

- [ ] **Step 1: Add the script skeleton and dry-run model**

Create `skills/kws-codex-plan-executor/scripts/repair_runs.py` with this structure:

```python
#!/usr/bin/env python3
"""Plan and apply conservative repairs for stale kws-cpe run state."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import inspect_runs
import validate_state


SAFE_ACTIONS = {"mark-blocked-stale"}
FINISHED_OUTCOMES = inspect_runs.FINISHED_OUTCOMES


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path_for_run(codex_home: Path, run_id: str) -> Path:
    return codex_home / "orchestrator" / run_id / "state.json"


def state_path_is_safe(codex_home: Path, run_id: str, state_path: Path, state: dict[str, Any]) -> tuple[bool, str]:
    expected = state_path_for_run(codex_home, run_id).resolve(strict=False)
    actual = state_path.resolve(strict=False)
    if actual != expected:
        return False, f"state file must be {expected}"
    if state.get("run_id") != run_id:
        return False, "state.run_id must match the orchestrator directory name"
    state_path_field = state.get("state_path")
    if not isinstance(state_path_field, str) or Path(state_path_field).resolve(strict=False) != expected:
        return False, "state.state_path must equal .codex/orchestrator/<run_id>/state.json"
    run_dir_field = state.get("run_dir")
    if not isinstance(run_dir_field, str) or Path(run_dir_field).resolve(strict=False) != expected.parent:
        return False, "state.run_dir must equal .codex/orchestrator/<run_id>"
    return True, ""
```

- [ ] **Step 2: Add candidate classification**

Add these functions below `state_path_is_safe`:

```python
def validation_errors(state: dict[str, Any] | None) -> list[str]:
    if state is None:
        return ["state file is unreadable"]
    return validate_state.validate(state)


def candidate(
    *,
    run_id: str,
    state_path: str,
    followups: list[str],
    action: str,
    apply_safe: bool,
    reason: str,
    patch_preview: dict[str, Any] | None = None,
    validation_errors_value: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "run_id": run_id,
        "state_path": state_path,
        "detected_followups": sorted(followups),
        "recommended_action": action,
        "apply_safe": apply_safe,
        "reason": reason,
        "state_patch_preview": patch_preview or {},
    }
    if validation_errors_value:
        item["validation_errors"] = validation_errors_value
    return item


def classify_record(record: dict[str, Any], codex_home: Path) -> dict[str, Any] | None:
    run_id = str(record.get("run_id") or "")
    if not run_id:
        return None
    state_path = state_path_for_run(codex_home, run_id)
    state = inspect_runs.load_state(state_path)
    quality = record.get("run_quality") if isinstance(record.get("run_quality"), dict) else {}
    followups = list(quality.get("open_followups") or [])
    validation_status = quality.get("validation_status")
    terminal_state = quality.get("terminal_state")
    missing_worktree = record.get("missing_worktree") is True or "missing_execution_worktree" in followups
    redacted_state_path = inspect_runs.redacted(str(state_path), codex_home)

    safe_path, path_reason = state_path_is_safe(codex_home, run_id, state_path, state or {})
    if not safe_path:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason=path_reason,
        )
    if validation_status == "failed":
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="state validation failed before repair",
            validation_errors_value=list(quality.get("schema_drift") or []),
        )
    if state is None or validation_status == "unreadable":
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="state file is unreadable",
        )
    if isinstance(state.get("current_blocker"), dict):
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="manual-review-required",
            apply_safe=False,
            reason="existing current_blocker must be reviewed before repair",
        )
    if terminal_state == "finished" and missing_worktree:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="acknowledge-cleaned-worktree",
            apply_safe=False,
            reason="finished state should not be rewritten without cleanup acknowledgement support",
        )
    if terminal_state in FINISHED_OUTCOMES:
        return None
    if "stale_non_terminal_run" in followups and missing_worktree:
        return candidate(
            run_id=run_id,
            state_path=redacted_state_path,
            followups=followups,
            action="mark-blocked-stale",
            apply_safe=True,
            reason="non-terminal stale run cannot resume because execution worktree is missing",
            patch_preview={
                "lifecycle_outcome": "blocked",
                "current_phase": "recover",
                "current_blocker.category": "state_integrity_drift",
            },
        )
    return None
```

- [ ] **Step 3: Add dry-run plan rendering**

Add these functions:

```python
def summarize(candidates: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "candidate_count": len(candidates),
        "apply_safe_count": sum(1 for item in candidates if item.get("apply_safe") is True),
        "manual_review_count": sum(1 for item in candidates if item.get("recommended_action") == "manual-review-required"),
    }


def build_plan(codex_home: Path, recent: int | None, stale_hours: float, *, dry_run: bool = True) -> dict[str, Any]:
    report = inspect_runs.inspect_all_runs(
        codex_home,
        recent,
        quality_report=True,
        stale_hours=stale_hours,
        validate=True,
    )
    records = report.get("runs") if isinstance(report.get("runs"), list) else []
    candidates = []
    for record in records:
        item = classify_record(record, codex_home)
        if item is not None:
            candidates.append(item)
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "dry_run": dry_run,
        "summary": summarize(candidates),
        "candidates": candidates,
    }


def render_plan(plan: dict[str, Any], jsonl: bool) -> str:
    if jsonl:
        rows = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
        return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for row in rows)
    return json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_output(text: str, output: str | None) -> None:
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        print(output_path)
    else:
        print(text, end="")
```

- [ ] **Step 4: Add CLI for dry-run**

Add `parse_args` and `main`:

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--output")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--action")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.recent is not None and args.recent < 0:
        die("--recent must be non-negative")
    if args.stale_hours < 0:
        die("--stale-hours must be non-negative")
    if args.apply and (not args.run_id or not args.action):
        die("--apply requires --run-id and --action")
    if args.action and args.action not in SAFE_ACTIONS:
        die(f"--action must be one of {sorted(SAFE_ACTIONS)}")
    return args


def main() -> int:
    args = parse_args()
    codex_home = Path(args.codex_home).expanduser().resolve()
    if args.apply:
        die("apply mode is implemented in Task 3")
    plan = build_plan(codex_home, args.recent, args.stale_hours, dry_run=True)
    write_output(render_plan(plan, args.jsonl), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run targeted eval and capture GREEN/known RED split**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_repair_runs.py
```

Expected: dry-run, schema-drift, existing-blocker, no-candidate, and JSONL checks pass; apply checks fail because Task 3 is not implemented.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add skills/kws-codex-plan-executor/scripts/repair_runs.py
git commit -m "feat(cpe): add repair run dry-run planner"
```

## Task 3: Implement Validated Single-Run Apply

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/repair_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_repair_runs.py`

**Interfaces:**
- Consumes:
  - `classify_record(record, codex_home)` from Task 2.
  - `state_path_is_safe(codex_home, run_id, state_path, state)` from Task 2.
- Produces:
  - `build_blocked_state(state: dict[str, Any], run_id: str, checked_at: str) -> dict[str, Any]`
  - `atomic_write_json(path: Path, payload: dict[str, Any]) -> None`
  - `apply_action(codex_home: Path, run_id: str, action: str, stale_hours: float) -> tuple[int, dict[str, Any]]`

- [ ] **Step 1: Add state patch and atomic write helpers**

Append these functions before `parse_args` in `repair_runs.py`:

```python
def build_blocked_state(state: dict[str, Any], run_id: str, checked_at: str) -> dict[str, Any]:
    patched = copy.deepcopy(state)
    timestamps = patched.setdefault("timestamps", {})
    timestamps["updated_at"] = checked_at
    if timestamps.get("completed_at") is None:
        timestamps["completed_at"] = checked_at
    patched["lifecycle_outcome"] = "blocked"
    patched["current_phase"] = "recover"
    patched["handoff_reason"] = (
        f"Run {run_id} is stale and cannot resume because its execution worktree is missing."
    )
    patched["current_blocker"] = {
        "category": "state_integrity_drift",
        "summary": f"Run {run_id} is stale and its execution worktree is missing.",
        "recoverable": True,
        "next_action_kind": "operator_decision",
    }
    health = patched.setdefault("context_health", {})
    health["status"] = "yellow"
    health["handoff_ready"] = True
    health["next_action"] = (
        "Inspect the blocked state and start a fresh CPE run if implementation should continue."
    )
    return patched


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
```

- [ ] **Step 2: Add apply implementation**

Add this function:

```python
def apply_action(codex_home: Path, run_id: str, action: str, stale_hours: float) -> tuple[int, dict[str, Any]]:
    if action != "mark-blocked-stale":
        die(f"unsupported action: {action}")
    state_path = state_path_for_run(codex_home, run_id)
    state = inspect_runs.load_state(state_path)
    if state is None:
        die(f"state is not readable JSON: {state_path}")
    safe_path, path_reason = state_path_is_safe(codex_home, run_id, state_path, state)
    if not safe_path:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": {"candidate_count": 1, "apply_safe_count": 0, "manual_review_count": 1},
            "candidates": [
                candidate(
                    run_id=run_id,
                    state_path=inspect_runs.redacted(str(state_path), codex_home),
                    followups=[],
                    action="manual-review-required",
                    apply_safe=False,
                    reason=path_reason,
                )
            ],
        }
        return 1, plan
    pre_errors = validate_state.validate(state)
    if pre_errors:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": {"candidate_count": 1, "apply_safe_count": 0, "manual_review_count": 1},
            "candidates": [
                candidate(
                    run_id=run_id,
                    state_path=inspect_runs.redacted(str(state_path), codex_home),
                    followups=["state_schema_drift"],
                    action="manual-review-required",
                    apply_safe=False,
                    reason="state validation failed before repair",
                    validation_errors_value=pre_errors,
                )
            ],
        }
        return 1, plan
    record = inspect_runs.state_record(
        state,
        state_path,
        codex_home,
        include_quality=True,
        stale_hours=stale_hours,
        validate=True,
    )
    classified = classify_record(record, codex_home)
    if not classified or classified.get("recommended_action") != action or classified.get("apply_safe") is not True:
        plan = {
            "schema_version": "1",
            "checked_at": now_iso(),
            "dry_run": False,
            "summary": summarize([classified] if classified else []),
            "candidates": [classified] if classified else [],
        }
        return 1, plan
    checked_at = now_iso()
    patched = build_blocked_state(state, run_id, checked_at)
    post_errors = validate_state.validate(patched)
    if post_errors:
        failed = dict(classified)
        failed["apply_safe"] = False
        failed["recommended_action"] = "manual-review-required"
        failed["reason"] = "repaired state failed validation"
        failed["validation_errors"] = post_errors
        plan = {
            "schema_version": "1",
            "checked_at": checked_at,
            "dry_run": False,
            "summary": summarize([failed]),
            "candidates": [failed],
        }
        return 1, plan
    atomic_write_json(state_path, patched)
    applied = dict(classified)
    applied["applied"] = True
    applied["before"] = {
        "lifecycle_outcome": state.get("lifecycle_outcome"),
        "current_phase": state.get("current_phase"),
        "validation_status": "passed",
    }
    applied["after"] = {
        "lifecycle_outcome": patched.get("lifecycle_outcome"),
        "current_phase": patched.get("current_phase"),
        "validation_status": "passed",
    }
    plan = {
        "schema_version": "1",
        "checked_at": checked_at,
        "dry_run": False,
        "summary": summarize([applied]),
        "candidates": [applied],
    }
    return 0, plan
```

- [ ] **Step 3: Wire apply mode into `main`**

Replace the apply branch in `main` with:

```python
    if args.apply:
        code, plan = apply_action(codex_home, args.run_id, args.action, args.stale_hours)
        write_output(render_plan(plan, args.jsonl), args.output)
        if code == 0:
            item = (plan.get("candidates") or [{}])[0]
            print(
                "applied mark-blocked-stale: "
                f"{item.get('run_id')} "
                f"{item.get('before', {}).get('lifecycle_outcome')} -> "
                f"{item.get('after', {}).get('lifecycle_outcome')}; "
                f"validation={item.get('after', {}).get('validation_status')}"
            )
        return code
```

- [ ] **Step 4: Run the targeted repair eval**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_repair_runs.py
```

Expected: JSON output with `"passed": true` and zero failures.

- [ ] **Step 5: Run compile checks for changed Python**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/repair_runs.py evals/check_repair_runs.py
```

Expected: no output and exit zero.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add skills/kws-codex-plan-executor/scripts/repair_runs.py skills/kws-codex-plan-executor/evals/check_repair_runs.py
git commit -m "feat(cpe): apply stale run blocked repair"
```

## Task 4: Update CPE Docs And History

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: `repair_runs.py` CLI from Tasks 2 and 3.
- Produces: operator-facing docs that explain:
  - dry-run first
  - single-run apply only
  - `mark-blocked-stale` is the only safe mutation
  - no file deletion
  - validate-before-write and validate-after-patch safety

- [ ] **Step 1: Update `SKILL.md` core invariant**

Add one bullet after the existing `run_quality.open_followups` bullet:

```markdown
- When read-only inspection reports stale non-terminal runs with missing
  execution worktrees, use `scripts/repair_runs.py` to produce a dry-run repair
  plan before any operator action. The only safe mutation is explicit
  `--apply --run-id <id> --action mark-blocked-stale`, which validates before
  and after the state patch and never deletes files.
```

- [ ] **Step 2: Update `README.md` validation section**

Add `python3 evals/check_repair_runs.py` immediately after `python3 evals/check_inspect_runs.py`.

Add this operator example after the inspection paragraph:

````markdown
Run-state repair is separate from inspection and defaults to dry-run:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --recent 20 \
  --stale-hours 24 \
  --output /tmp/cpe-repair-plan.json
```

Apply is intentionally narrow:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --run-id <run_id> \
  --action mark-blocked-stale \
  --apply
```

The first repair action only marks one stale non-terminal run as blocked when
its execution worktree is missing and state validation passes before and after
the patch. It does not delete worktrees, run directories, or finished states.
````

- [ ] **Step 3: Update `references/state-schema.md`**

Append this section after the `run_quality.open_followups` paragraph:

````markdown
## Stale Blocked Repair

`scripts/repair_runs.py --apply --run-id <id> --action mark-blocked-stale`
may change a validated non-terminal stale run with a missing execution worktree
into a blocked run. The patch sets:

```json
{
  "lifecycle_outcome": "blocked",
  "current_phase": "recover",
  "handoff_reason": "Run <id> is stale and cannot resume because its execution worktree is missing.",
  "current_blocker": {
    "category": "state_integrity_drift",
    "summary": "Run <id> is stale and its execution worktree is missing.",
    "recoverable": true,
    "next_action_kind": "operator_decision"
  },
  "context_health": {
    "status": "yellow",
    "handoff_ready": true,
    "next_action": "Inspect the blocked state and start a fresh CPE run if implementation should continue."
  }
}
```

The repair also refreshes `timestamps.updated_at` and sets
`timestamps.completed_at` when it is absent. The script validates the original
state, validates the patched state, and writes only
`~/.codex/orchestrator/<run_id>/state.json`.
````

- [ ] **Step 4: Update `docs/state-and-logging.md`**

Add this paragraph to the `Failure, Recovery, And Progress` section:

```markdown
`scripts/repair_runs.py` is the operator repair path for stale CPE runs. Its
default mode emits a dry-run plan from recent `run_quality.open_followups`.
The apply mode requires one `--run-id`, one `--action`, and `--apply`; the only
mutating action is `mark-blocked-stale`. It rewrites only the selected
`state.json`, validates before and after the patch, and does not delete
worktrees or run directories.
```

- [ ] **Step 5: Update verification docs and risks**

In `docs/evals-and-verification.md`, insert:

```markdown
python3 evals/check_repair_runs.py
```

after `python3 evals/check_inspect_runs.py`.

Replace the v2.22 run-quality limitation in `docs/risks-limitations-deferrals.md` with:

```markdown
- Run-quality inspection remains read-only, but v2.23 adds a separate
  `scripts/repair_runs.py` operator flow. It can mark exactly one validated
  stale non-terminal run with a missing execution worktree as blocked after
  explicit `--apply --run-id <id> --action mark-blocked-stale`. Cleanup,
  deletion, finished-state rewrites, and arbitrary schema repairs remain
  deferred.
```

- [ ] **Step 6: Update `HISTORY.md`**

Add a top entry:

```markdown
## 2.24.0 - 2026-06-23

- Added `scripts/repair_runs.py` for dry-run CPE repair planning and explicit
  single-run `mark-blocked-stale` apply.
- Added deterministic repair-flow eval coverage in `evals/check_repair_runs.py`.
- Documented the stale blocked repair state fields and non-deletion safety
  boundary.
```

- [ ] **Step 7: Verify docs references**

Run:

```bash
cd skills/kws-codex-plan-executor
rg 'repair_runs|mark-blocked-stale|stale blocked repair' SKILL.md README.md references docs HISTORY.md
```

Expected: matches in every changed docs target.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/HISTORY.md
git commit -m "docs(cpe): document run repair boundary"
```

## Task 5: Full Verification And Graphify Refresh

**Files:**
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`
- Read: `skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py`

**Interfaces:**
- Consumes: final implementation diff from Tasks 1-4.
- Produces: verified branch with current Graphify evidence.

- [ ] **Step 1: Run targeted deterministic checks**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_repair_runs.py
python3 evals/check_inspect_runs.py
python3 evals/check_state_schema.py
```

Expected: each command exits zero. `check_repair_runs.py` prints `"passed": true`.

- [ ] **Step 2: Run full CPE eval harness**

Run:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: exits zero.

- [ ] **Step 3: Run syntax and shell checks**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Expected: both commands exit zero with no output.

- [ ] **Step 4: Run repository whitespace check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: no output and exit zero.

- [ ] **Step 5: Refresh Graphify**

Run:

```bash
cd /Users/kws/source/private/Archive
graphify update . --force
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root /Users/kws/source/private/Archive \
  --update-ran \
  --output /tmp/cpe-repair-runs-graphify-audit.json
```

Expected: the audit JSON contains `"fresh": true` and `"errors": []`.

- [ ] **Step 6: Review final diff**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --stat
git diff -- skills/kws-codex-plan-executor/scripts/repair_runs.py
git diff -- skills/kws-codex-plan-executor/evals/check_repair_runs.py
git diff -- skills/kws-codex-plan-executor/SKILL.md skills/kws-codex-plan-executor/README.md
git diff -- graphify-out/GRAPH_REPORT.md graphify-out/graph.json
```

Expected: diff contains only the repair script, repair eval, CPE docs/history, eval harness insertion, and Graphify refresh.

- [ ] **Step 7: Commit final verification artifacts**

Run:

```bash
git add graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "chore(cpe): refresh graphify after repair flow"
```

## Final Acceptance

Run all commands from a clean implementation branch:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_repair_runs.py
python3 evals/check_inspect_runs.py
python3 evals/check_state_schema.py
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
graphify update . --force
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --update-ran --output /tmp/cpe-repair-runs-graphify-audit.json
```

The work is complete when:

- `repair_runs.py` defaults to dry-run and emits deterministic JSON.
- `repair_runs.py --jsonl` emits one JSON object per candidate line.
- `repair_runs.py --apply` fails unless `--run-id` and `--action` are present.
- `mark-blocked-stale` applies only to one validated stale non-terminal run with missing execution worktree and no existing blocker.
- Finished runs with missing worktrees are reported as `acknowledge-cleaned-worktree` with `apply_safe=false`.
- Schema drift, unreadable JSON, existing blockers, unsafe paths, and terminal states do not mutate state.
- The apply path validates before and after patch construction.
- The apply path writes only `~/.codex/orchestrator/<run_id>/state.json` with atomic replace.
- All CPE docs and history describe the new repair boundary.
- Graphify freshness audit reports `fresh=true`.

## Self-Review

- Spec coverage: Tasks 1-3 cover the repair model, classification rules, safety rules, dry-run, JSONL, and single-run apply. Task 4 covers every requested docs target. Task 5 covers full verification and Graphify refresh.
- Placeholder scan: this plan intentionally avoids open-ended placeholders and gives concrete paths, commands, snippets, and expected outcomes.
- Type consistency: task interfaces use `dict[str, Any]`, `Path`, `tuple[int, dict[str, Any]]`, and list-returning validator contracts consistently across tasks.
