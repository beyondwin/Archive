# Executor Finalization + Schema Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two standalone state.json validators (schema + finalization) to `kws-claude-multi-agent-executor`, wire them as Phase 2 gates, and lock the behavior with tests built from two real 2026-06-04 bad-run states.

**Architecture:** Two self-contained Python CLI scripts under `scripts/` mirroring the existing `validate_method_audit.py` contract (`--state`, JSON output, exit 0/1/2). `validate_state_schema.py` is check-only; `finalize_run.py` adds `--fix` that only stamps `completed_at`. Prose wiring in `references/phases/phase-2-finalization.md` + a SKILL.md Guardrails row makes them mandatory gates; `evals/check_skill_contract.py` asserts the wiring so it can't rot.

**Tech Stack:** Python 3 stdlib (argparse, json, pathlib, datetime), pytest, bash eval harness.

All paths below are relative to `skills/kws-claude-multi-agent-executor/` unless absolute. Run all `pytest`/`python3` commands from that directory.

---

## File Structure

- Create `scripts/validate_state_schema.py` — canonical-shape validator (check-only)
- Create `scripts/test_validate_state_schema.py` — its tests + 1 regression fixture (readmates shape)
- Create `scripts/finalize_run.py` — finalization-consistency gate (`--check`/`--fix`)
- Create `scripts/test_finalize_run.py` — its tests + 1 regression fixture (source-matching shape)
- Modify `references/phases/phase-2-finalization.md` — Step 1.5 schema gate, Step 2 finalize gate
- Modify `SKILL.md` — one Guardrails row + version bump
- Modify `evals/check_skill_contract.py` — helper-exists + wiring checks
- Modify `ARCHITECTURE.md`, `HISTORY.md` — sync new scripts + `cost_tracking_waived` field
- Create `docs/experiments/v2.26-finalization-enforcement/` — experiment record

---

## Task 1: `validate_state_schema.py` (check-only validator)

**Files:**
- Create: `scripts/validate_state_schema.py`
- Test: `scripts/test_validate_state_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_validate_state_schema.py`:

```python
"""Tests for validate_state_schema.py — canonical state.json shape checks."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import validate_state_schema as vss  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


CANONICAL_SINGLE = {
    "schema_version": "2",
    "mode": "interactive_attached",
    "dispatch_config": {"final_sweep": "agent"},
    "cost_ledger": {"totals": {"dispatches": 3}},
    "risk_levels": {"task_1": "low", "task_2": "mid"},
    "execution_plan": [{"wave": 0, "parallel_groups": [["task_1"]]}],
    "tasks": {
        "task_1": {"status": "COMPLETE"},
        "task_2": {"status": "COMPLETE"},
    },
}

# The actual readmates-member-reading-experience-20260604 divergence.
READMATES_BAD = {
    "schema_version": "2",
    "mode": "interactive_attached",
    "risk_levels": {"task_A1": "low", "task_B2": "high", "task_D1": "verify"},
    "execution_order": ["task_A1", "task_B2", "task_D1"],
    "tasks": {},
    "task_summaries": {
        "task_A1": {"status": "DONE"},
        "task_B2": {"status": "DONE"},
        "task_D1": {"status": "DONE"},
    },
}


def test_canonical_single_plan_passes(tmp_path):
    p = _write(tmp_path, CANONICAL_SINGLE)
    result = vss.validate(json.loads(p.read_text()))
    assert result["passed"] is True
    assert result["violations"] == []


def test_readmates_shape_flags_empty_tasks(tmp_path):
    result = vss.validate(READMATES_BAD)
    assert result["passed"] is False
    codes = {v["code"] for v in result["violations"]}
    assert "tasks_empty_but_declared" in codes
    assert "execution_order_without_plan" in codes
    assert "risk_value_invalid" in codes


def test_readmates_missing_runlevel_fields(tmp_path):
    result = vss.validate(READMATES_BAD)
    codes = {v["code"] for v in result["violations"]}
    assert "missing_dispatch_config" in codes
    assert "missing_cost_ledger" in codes


def test_invalid_mode_flagged(tmp_path):
    bad = dict(CANONICAL_SINGLE, mode="nonsense_mode")
    result = vss.validate(bad)
    codes = {v["code"] for v in result["violations"]}
    assert "mode_invalid" in codes


def test_multi_plan_chain_per_tree(tmp_path):
    multi = {
        "schema_version": "2",
        "mode": "plan_chain_running",
        "dispatch_config": {}, "cost_ledger": {"totals": {"dispatches": 1}},
        "active_plan": 0,
        "plan_chain": [
            {"risk_levels": {"t1": "low"}, "execution_plan": [], "tasks": {"t1": {"status": "COMPLETE"}}},
            {"risk_levels": {"t2": "mid"}, "execution_order": ["t2"], "tasks": {},
             "task_summaries": {"t2": {"status": "DONE"}}},
        ],
    }
    result = vss.validate(multi)
    assert result["passed"] is False
    # the violation must be attributed to plan_chain[1]
    assert any(v["scope"] == "plan_chain[1]" and v["code"] == "tasks_empty_but_declared"
               for v in result["violations"])


def test_exit_code_broken_state(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert vss.main(["--state", str(p)]) == 2


def test_exit_code_pass_and_fail(tmp_path):
    good = _write(tmp_path, CANONICAL_SINGLE)
    assert vss.main(["--state", str(good)]) == 0
    bad = _write(tmp_path, READMATES_BAD)
    assert vss.main(["--state", str(bad)]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/test_validate_state_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'validate_state_schema'`

- [ ] **Step 3: Write the implementation**

Create `scripts/validate_state_schema.py`:

```python
#!/usr/bin/env python3
"""Validate the canonical shape of a kws-claude-multi-agent-executor state.json.

Catches the non-canonical / improvised schemas observed in attached-mode runs
(e.g. empty tasks{} with per-task data in task_summaries{}, execution_order
without execution_plan, risk values outside low/mid/high).

Exit 0: canonical (no violations; warnings allowed).
Exit 1: at least one violation.
Exit 2: validator could not parse state.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VALID_RISK = {"low", "mid", "high"}
VALID_MODES = {
    "interactive_session", "interactive_attached", "headless_pending",
    "headless_running", "headless_chained", "plan_chain_running", "plan2_running",
}


def _active_trees(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    chain = state.get("plan_chain")
    if isinstance(chain, list):
        return [(f"plan_chain[{i}]", entry) for i, entry in enumerate(chain)]
    return [("state", state)]


def _declared_count(tree: dict[str, Any]) -> int:
    rl = tree.get("risk_levels")
    if isinstance(rl, dict):
        return len(rl)
    eo = tree.get("execution_order")
    if isinstance(eo, list):
        return len(eo)
    return 0


def validate(state: dict[str, Any]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def viol(scope: str, code: str, detail: str) -> None:
        violations.append({"scope": scope, "code": code, "detail": detail})

    def warn(scope: str, code: str, detail: str) -> None:
        warnings.append({"scope": scope, "code": code, "detail": detail})

    if str(state.get("schema_version")) != "2":
        warn("state", "schema_version_not_2",
             f"schema_version={state.get('schema_version')!r} (expected '2')")

    mode = state.get("mode")
    if mode not in VALID_MODES:
        viol("state", "mode_invalid", f"mode={mode!r} not in allowed enum")

    trees = _active_trees(state)
    any_tasks = any(_declared_count(t) > 0 for _, t in trees)

    if any_tasks:
        if "dispatch_config" not in state:
            viol("state", "missing_dispatch_config", "run-level dispatch_config absent")
        if "cost_ledger" not in state:
            viol("state", "missing_cost_ledger", "run-level cost_ledger absent")

    for scope, tree in trees:
        declared = _declared_count(tree)
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        summaries = tree.get("task_summaries")
        summaries = summaries if isinstance(summaries, dict) else {}

        if declared > 0 and not tasks:
            if summaries:
                viol(scope, "tasks_empty_but_declared",
                     f"{declared} tasks declared but tasks{{}} empty; "
                     f"{len(summaries)} records improvised into task_summaries")
            else:
                viol(scope, "tasks_empty_but_declared",
                     f"{declared} tasks declared but tasks{{}} empty")

        if tree.get("execution_order") is not None and tree.get("execution_plan") is None:
            viol(scope, "execution_order_without_plan",
                 "execution_order present without canonical execution_plan")

        rl = tree.get("risk_levels")
        if isinstance(rl, dict):
            for task_id, level in rl.items():
                if level not in VALID_RISK:
                    viol(scope, "risk_value_invalid",
                         f"{task_id}: risk={level!r} not in {sorted(VALID_RISK)}")

        if tasks and summaries:
            warn(scope, "task_summaries_alongside_tasks",
                 "both tasks{} and task_summaries{} populated (legacy mirror)")

    return {
        "passed": violations == [],
        "scopes_checked": [s for s, _ in trees],
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--active-plan", default="auto")  # accepted for contract parity
    args = ap.parse_args(argv)

    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — broken state is exit 2 by contract
        print(json.dumps({"passed": False, "error": f"unparseable state.json: {exc}"}))
        return 2

    result = validate(state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_validate_state_schema.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/validate_state_schema.py \
        skills/kws-claude-multi-agent-executor/scripts/test_validate_state_schema.py
git commit -m "feat(v2.26): add validate_state_schema.py canonical-shape gate"
```

---

## Task 2: `finalize_run.py` (finalization gate with `--fix`)

**Files:**
- Create: `scripts/finalize_run.py`
- Test: `scripts/test_finalize_run.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_finalize_run.py`:

```python
"""Tests for finalize_run.py — finalization-consistency gate + safe --fix."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finalize_run as fr  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


CLEAN = {
    "status": "COMPLETE",
    "timestamps": {"started_at": "2026-06-04T12:00:00Z", "completed_at": "2026-06-04T14:00:00Z"},
    "cost_ledger": {"totals": {"dispatches": 5}},
    "tasks": {
        "task_1": {"status": "COMPLETE", "verifier": "PASS", "timing": {"started": "x", "completed": "y"}},
    },
}

# The actual source-matching-refinement-20260604 unfinalized shape.
SOURCE_MATCHING_BAD = {
    "status": "COMPLETE",
    "last_completed_at": "2026-06-04T23:04:22.658323",
    "timestamps": {"started_at": "2026-06-04T12:06:54Z", "completed_at": None},
    "cost_ledger": {"totals": {"dispatches": 0}},
    "tasks": {
        "task_9": {"status": "COMPLETE", "verifier": "PASS", "timing": {"completed": "z"}},
        "task_10": {"status": "COMPLETE", "verifier": "PENDING_BATCH", "timing": {"completed": "z"}},
    },
}


def test_clean_run_passes(tmp_path):
    result = fr.evaluate(CLEAN)
    assert result["passed"] is True
    assert [f for f in result["findings"] if f["level"] == "FAIL"] == []


def test_source_matching_flags_pending_and_completed_at(tmp_path):
    result = fr.evaluate(SOURCE_MATCHING_BAD)
    assert result["passed"] is False
    fails = {f["code"] for f in result["findings"] if f["level"] == "FAIL"}
    assert "verifier_pending_batch" in fails
    assert "completed_at_null" in fails
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "cost_dispatches_zero" in warns
    assert "timing_started_missing" in warns


def test_cost_waived_suppresses_dispatch_warning(tmp_path):
    waived = dict(SOURCE_MATCHING_BAD, cost_tracking_waived=True)
    result = fr.evaluate(waived)
    warns = {f["code"] for f in result["findings"] if f["level"] == "WARN"}
    assert "cost_dispatches_zero" not in warns


def test_fix_stamps_completed_at_from_last_completed(tmp_path):
    p = _write(tmp_path, SOURCE_MATCHING_BAD)
    fr.apply_fix(p)
    st = _read(p)
    assert st["timestamps"]["completed_at"] == "2026-06-04T23:04:22.658323"


def test_fix_does_not_clear_pending_batch(tmp_path):
    p = _write(tmp_path, SOURCE_MATCHING_BAD)
    fr.apply_fix(p)
    st = _read(p)
    assert st["tasks"]["task_10"]["verifier"] == "PENDING_BATCH"


def test_check_exit_codes(tmp_path):
    good = _write(tmp_path, CLEAN)
    assert fr.main(["--state", str(good), "--check"]) == 0
    bad = _write(tmp_path, SOURCE_MATCHING_BAD)
    assert fr.main(["--state", str(bad), "--check"]) == 1


def test_fix_then_pass_only_if_no_unfixable_fail(tmp_path):
    # PENDING_BATCH is unfixable, so --fix still exits 1.
    bad = _write(tmp_path, SOURCE_MATCHING_BAD)
    assert fr.main(["--state", str(bad), "--fix"]) == 1
    # Remove the unfixable task; only completed_at remains -> --fix exits 0.
    only_completed = {
        "status": "COMPLETE",
        "last_completed_at": "2026-06-04T23:04:22.658323",
        "timestamps": {"started_at": "a", "completed_at": None},
        "cost_ledger": {"totals": {"dispatches": 2}},
        "tasks": {"task_1": {"status": "COMPLETE", "verifier": "PASS",
                             "timing": {"started": "s", "completed": "c"}}},
    }
    p = _write(tmp_path, only_completed)
    assert fr.main(["--state", str(p), "--fix"]) == 0


def test_multi_plan_chain_checks_each_tree(tmp_path):
    multi = {
        "status": "COMPLETE",
        "timestamps": {"started_at": "a", "completed_at": "b"},
        "cost_ledger": {"totals": {"dispatches": 4}},
        "plan_chain": [
            {"tasks": {"t1": {"status": "COMPLETE", "verifier": "PASS",
                              "timing": {"started": "s", "completed": "c"}}}},
            {"tasks": {"t2": {"status": "COMPLETE", "verifier": "PENDING_BATCH",
                              "timing": {"started": "s", "completed": "c"}}}},
        ],
    }
    result = fr.evaluate(multi)
    assert any(f["code"] == "verifier_pending_batch" and f["scope"] == "plan_chain[1]"
               for f in result["findings"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/test_finalize_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'finalize_run'`

- [ ] **Step 3: Write the implementation**

Create `scripts/finalize_run.py`:

```python
#!/usr/bin/env python3
"""Finalization-consistency gate for a kws-claude-multi-agent-executor run.

Checks that a run that claims to be finished is actually finalized:
completed_at stamped, no LOW task left PENDING_BATCH, cost ledger populated,
per-task timing present. `--fix` performs only the one genuinely-safe write
(stamp completed_at); everything else is a loud report, never a silent mutation.

Exit 0: no unfixable FAIL (WARNs allowed).
Exit 1: at least one FAIL (after --fix, if used).
Exit 2: validator could not parse state.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _active_trees(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    chain = state.get("plan_chain")
    if isinstance(chain, list):
        return [(f"plan_chain[{i}]", entry) for i, entry in enumerate(chain)]
    return [("state", state)]


def evaluate(state: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []

    def add(level: str, scope: str, code: str, detail: str, fixable: bool = False) -> None:
        findings.append({"level": level, "scope": scope, "code": code,
                         "detail": detail, "fixable": fixable})

    # Run-level: completed_at.
    completed_at = (state.get("timestamps") or {}).get("completed_at")
    if not completed_at:
        add("FAIL", "state", "completed_at_null",
            "timestamps.completed_at is null/absent", fixable=True)

    # Run-level: cost ledger dispatches.
    if not state.get("cost_tracking_waived"):
        dispatches = ((state.get("cost_ledger") or {}).get("totals") or {}).get("dispatches", 0)
        if not dispatches:
            add("WARN", "state", "cost_dispatches_zero",
                "cost_ledger.totals.dispatches == 0 (accumulate_cost.py never ran)")

    # Per-tree task checks.
    for scope, tree in _active_trees(state):
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        for task_id, task in tasks.items():
            status = task.get("status")
            if status not in ("COMPLETE", "SKIPPED"):
                add("FAIL", scope, "task_not_terminal",
                    f"{task_id}: status={status!r} (expected COMPLETE/SKIPPED)")
            if task.get("verifier") == "PENDING_BATCH":
                add("FAIL", scope, "verifier_pending_batch",
                    f"{task_id}: verifier still PENDING_BATCH (final LOW sweep never wrote back)")
            timing = task.get("timing") or {}
            if not timing.get("started"):
                add("WARN", scope, "timing_started_missing",
                    f"{task_id}: timing.started absent (per-task duration uncomputable)")

    # Run-level consistency: a COMPLETE run must be fully finalized.
    if state.get("status") == "COMPLETE":
        if any(f["code"] in ("completed_at_null", "verifier_pending_batch") for f in findings):
            add("FAIL", "state", "complete_but_unfinalized",
                "status==COMPLETE but completed_at null or a task is PENDING_BATCH")

    unfixable_fail = any(f["level"] == "FAIL" and not f["fixable"] for f in findings)
    any_fail = any(f["level"] == "FAIL" for f in findings)
    return {"passed": not any_fail, "unfixable_fail": unfixable_fail, "findings": findings}


def apply_fix(state_path: Path) -> dict[str, Any]:
    """Stamp completed_at if null. Atomic. Returns the post-fix evaluation."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ts = state.setdefault("timestamps", {})
    if not ts.get("completed_at"):
        ts["completed_at"] = state.get("last_completed_at") or \
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, state_path)
    return evaluate(state)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("--fix", action="store_true", help="stamp completed_at, then re-check")
    ap.add_argument("--active-plan", default="auto")  # accepted for contract parity
    args = ap.parse_args(argv)

    try:
        if args.fix:
            result = apply_fix(args.state)
        else:
            state = json.loads(args.state.read_text(encoding="utf-8"))
            result = evaluate(state)
    except Exception as exc:  # noqa: BLE001 — broken state is exit 2 by contract
        print(json.dumps({"passed": False, "error": f"unparseable state.json: {exc}"}))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_finalize_run.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/finalize_run.py \
        skills/kws-claude-multi-agent-executor/scripts/test_finalize_run.py
git commit -m "feat(v2.26): add finalize_run.py finalization gate with safe --fix"
```

---

## Task 3: Wire both gates into Phase 2 prose + SKILL.md Guardrail

**Files:**
- Modify: `references/phases/phase-2-finalization.md` (Step 1.5 and Step 2)
- Modify: `SKILL.md` (Guardrails table)

- [ ] **Step 1: Add the schema gate to Phase 2 Step 1.5**

In `references/phases/phase-2-finalization.md`, immediately AFTER the Step 1.5
method-audit `validate_method_audit.py` block (after its fenced bash block, before
the "Parse the JSON output" line is fine, or as a new paragraph at the end of Step
1.5), insert:

```markdown
**State-schema gate (v2.26):** after the method audit passes, run the canonical-shape validator:

\`\`\`bash
python3 <skill_dir>/scripts/validate_state_schema.py \
  --state <orch_dir>/state.json --active-plan auto
\`\`\`

`passed: true` → proceed to Step 2. Exit 1 → HALT with the printed `violations`
list (the run wrote a non-canonical state — e.g. empty `tasks{}` with records in
`task_summaries{}`, `execution_order` without `execution_plan`, or a risk value
outside low/mid/high). Do NOT call `close-run`; the operator inspects and repairs
state.json, then re-runs Phase 2. Exit 2 → HALT `validate_state_schema broken —
manual inspection required`.
```

- [ ] **Step 2: Add the finalization gate to Phase 2 Step 2**

In `references/phases/phase-2-finalization.md` Step 2, AFTER the
`agentlens run-close ... --outcome success` fenced block, insert:

```markdown
**Finalization gate (v2.26) — between completed_at stamp and report.** After the
`phase_boundary.py phase-emit --type phase_2_complete` stamp above, run the
finalization-consistency gate before emitting the Final Summary Report:

\`\`\`bash
python3 <skill_dir>/scripts/finalize_run.py --state <orch_dir>/state.json --fix
\`\`\`

`--fix` stamps `completed_at` if the boundary helper somehow left it null (safe,
atomic). Exit 0 → proceed to the report. Exit 1 → a residual **unfixable** FAIL
remains — almost always a task still at `verifier == PENDING_BATCH` (the Step 0 LOW
batch sweep did not write back) or a non-terminal task status. HALT with the printed
`findings`: re-run Step 0's LOW batch sweep for the offending task, then re-run this
gate. The gate must pass before `run-close --outcome success`; do not declare the
run COMPLETE with an unfinalized state. `cost_dispatches_zero` and
`timing_started_missing` are WARN (reported, non-blocking — set
`state.cost_tracking_waived=true` only when cost tracking was intentionally off).
```

- [ ] **Step 3: Add the Guardrails row to SKILL.md**

In `SKILL.md`, inside the `## Guardrails` table, add one row (place it adjacent to
the "Method audit must pass before Phase 2 close-run" row):

```markdown
| **Finalization gate is mandatory before close-run (v2.26)** | Phase 2 Step 1.5 runs `scripts/validate_state_schema.py` (canonical-shape: non-empty `tasks{}` when tasks are declared, `execution_plan` not `execution_order`, risk ∈ low/mid/high, run-level `dispatch_config`/`cost_ledger` present) and Step 2 runs `scripts/finalize_run.py --fix` (completed_at stamped, no task left `PENDING_BATCH`, terminal task statuses). A schema violation or an unfixable finalize FAIL HALTS before `agentlens run-close --outcome success` — the run is never declared COMPLETE with a non-canonical or unfinalized state.json. `finalize_run --fix` only stamps `completed_at`; it never clears `PENDING_BATCH` (that needs a real LOW batch sweep). `cost_ledger.dispatches==0` and missing `timing.started` are WARN unless `state.cost_tracking_waived`. |
```

- [ ] **Step 4: Verify the prose tokens are present**

Run: `grep -c "finalize_run.py" skills/kws-claude-multi-agent-executor/references/phases/phase-2-finalization.md skills/kws-claude-multi-agent-executor/SKILL.md`
Expected: both files report ≥ 1.

Run: `grep -c "validate_state_schema.py" skills/kws-claude-multi-agent-executor/references/phases/phase-2-finalization.md skills/kws-claude-multi-agent-executor/SKILL.md`
Expected: both files report ≥ 1.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-2-finalization.md \
        skills/kws-claude-multi-agent-executor/SKILL.md
git commit -m "feat(v2.26): wire schema + finalization gates into Phase 2"
```

---

## Task 4: Extend `check_skill_contract.py` so the wiring can't rot

**Files:**
- Modify: `evals/check_skill_contract.py`

- [ ] **Step 1: Add helper-exists + wiring checks**

In `evals/check_skill_contract.py`, after the `V221_WIRING` loop (around the
`skill_md_wires_legacy_migration_shim` record call), add a new block:

```python
    # ---- v2.26 finalization + schema gate contracts ----
    V226_HELPERS = {
        "scripts/validate_state_schema.py": ["--state", "execution_order_without_plan", "risk_value_invalid"],
        "scripts/finalize_run.py": ["--check", "--fix", "verifier_pending_batch", "completed_at_null"],
    }
    for rel_path, tokens in V226_HELPERS.items():
        full = skill_dir / rel_path
        if not full.is_file():
            record(f"v226_helper_exists_{rel_path.replace('/', '_')}", False,
                   f"{rel_path} must exist (v2.26)")
            continue
        body = full.read_text(encoding="utf-8")
        record(
            f"v226_helper_contract_{rel_path.replace('/', '_')}",
            all(t in body for t in tokens),
            f"{rel_path} must define its CLI/violation-code tokens: {', '.join(tokens)}",
        )

    record(
        "v226_schema_gate_wired",
        "validate_state_schema.py" in corpus,
        "Phase 2 prose must wire validate_state_schema.py (Step 1.5 schema gate)",
    )
    record(
        "v226_finalize_gate_wired",
        "finalize_run.py" in corpus,
        "Phase 2 prose must wire finalize_run.py --fix (Step 2 finalization gate)",
    )
    record(
        "v226_guardrail_row",
        "Finalization gate is mandatory before close-run" in corpus,
        "SKILL.md Guardrails must carry the v2.26 finalization-gate row",
    )
```

- [ ] **Step 2: Run the contract check**

Run: `python3 skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py --skill skills/kws-claude-multi-agent-executor/SKILL.md`
Expected: `"passed": true` (the new `v226_*` checks appear in `checks` and are all true, because Task 3 already landed the prose).

- [ ] **Step 3: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/evals/check_skill_contract.py
git commit -m "test(v2.26): contract-check the finalization + schema gate wiring"
```

---

## Task 5: Docs sync + experiment record + version bump

**Files:**
- Create: `docs/experiments/v2.26-finalization-enforcement/README.md`, `JOURNAL.md`, `findings/F01-close-out.md`
- Modify: `ARCHITECTURE.md` (script catalog + §5 `cost_tracking_waived`)
- Modify: `HISTORY.md` (v2.26 entry)
- Modify: `SKILL.md` (version frontmatter)

- [ ] **Step 1: Create the experiment record**

Copy the template and fill it in:

```bash
cd skills/kws-claude-multi-agent-executor
mkdir -p docs/experiments/v2.26-finalization-enforcement/{decisions,findings}
cp docs/experiments/_template/README.md docs/experiments/v2.26-finalization-enforcement/README.md
cp docs/experiments/_template/JOURNAL.md docs/experiments/v2.26-finalization-enforcement/JOURNAL.md
```

Then edit `README.md` to state: hypothesis (attached-mode runs skip Phase 2
finalization + write non-canonical state; mechanical gates catch it), the two
real 2026-06-04 runs as evidence, the two scripts shipped, and status `shipped`.
Add a one-line `JOURNAL.md` entry dated 2026-06-04 describing the change, and a
`findings/F01-close-out.md` with the ship decision and the Remaining Risk (skipped
Phase 2 still bypasses the gate; Stop-hook declined).

- [ ] **Step 2: Sync ARCHITECTURE.md**

In `ARCHITECTURE.md`: (a) add `validate_state_schema.py` and `finalize_run.py` to
the scripts/helper catalog section; (b) in the §5 state-schema snippet add the new
optional run-level field `cost_tracking_waived: bool` (default false) with a
one-line note that it suppresses the `cost_dispatches_zero` finalize WARN.

- [ ] **Step 3: Add the HISTORY.md entry**

In `HISTORY.md`, add a v2.26 entry: "Finalization + schema enforcement —
`validate_state_schema.py` + `finalize_run.py` Phase 2 gates close the
attached-mode finalization gap observed in two 2026-06-04 runs (null completed_at,
PENDING_BATCH leftover, dispatches 0, non-canonical schema)."

- [ ] **Step 4: Bump the SKILL.md version**

In `SKILL.md` frontmatter, set `version:` to `"2.26.0"`.

- [ ] **Step 5: Run the doc-freshness check**

Run: `python3 skills/kws-claude-multi-agent-executor/evals/check_doc_freshness.py`
Expected: no new failures attributable to this change (pre-existing version-skew
warnings may persist; do not regress link/HISTORY checks). If it flags a missing
`docs/snapshots/v2.26.md`, create a minimal snapshot per the doc-update-protocol.

- [ ] **Step 6: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/docs/experiments/v2.26-finalization-enforcement \
        skills/kws-claude-multi-agent-executor/ARCHITECTURE.md \
        skills/kws-claude-multi-agent-executor/HISTORY.md \
        skills/kws-claude-multi-agent-executor/SKILL.md
git commit -m "docs(v2.26): experiment record + ARCHITECTURE/HISTORY sync + version bump"
```

---

## Task 6: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Run both new unit suites**

Run: `cd skills/kws-claude-multi-agent-executor && python3 -m pytest scripts/test_validate_state_schema.py scripts/test_finalize_run.py -q`
Expected: all pass (16 passed).

- [ ] **Step 2: Run the full scripts test suite (no regressions)**

Run: `cd skills/kws-claude-multi-agent-executor && python3 -m pytest scripts/ -q`
Expected: all pre-existing tests still pass plus the two new suites.

- [ ] **Step 3: Run the contract check + self-test preflight**

Run: `cd skills/kws-claude-multi-agent-executor && python3 evals/check_skill_contract.py --skill SKILL.md && python3 scripts/compare_agentlens_events.py --self-test`
Expected: contract `"passed": true`; self-test ok.

- [ ] **Step 4: Smoke-test both validators against the two real bad runs**

Run:
```bash
cd skills/kws-claude-multi-agent-executor
python3 scripts/validate_state_schema.py --state ~/.claude/orchestrator/readmates-member-reading-experience-20260604-210358/state.json; echo "exit=$?"
python3 scripts/finalize_run.py --state ~/.claude/orchestrator/source-matching-refinement-20260604-210431/state.json --check; echo "exit=$?"
```
Expected: schema validator exits 1 on readmates with the three documented
violations; finalize_run exits 1 on source-matching flagging `verifier_pending_batch`
+ `completed_at_null` (do NOT pass `--fix` here — these are the user's real run
files; `--check` only).

- [ ] **Step 5: Report**

Summarize: tests green, contract green, both validators correctly flag the two real
runs. Note the worktree/branch is unmerged for the user to review.

---

## Self-Review

**Spec coverage:** Deliverable A → Task 1; B → Task 2; C → Task 3; D → Tasks 1/2 (fixtures) + Task 4 (contract eval); E → Task 5. Remaining-risk (skipped Phase 2) is documented in spec + F01 close-out (Task 5 Step 1). All spec sections map to a task.

**Placeholder scan:** every code step contains complete, runnable code; no TBD/TODO; prose-edit tasks quote the exact insertion text and anchor.

**Type consistency:** `validate()` returns `{passed, scopes_checked, violations[], warnings[]}` (violation `code`s used verbatim in tests + contract: `tasks_empty_but_declared`, `execution_order_without_plan`, `risk_value_invalid`, `mode_invalid`, `missing_dispatch_config`, `missing_cost_ledger`). `evaluate()` returns `{passed, unfixable_fail, findings[]}` (finding `code`s: `completed_at_null`, `verifier_pending_batch`, `task_not_terminal`, `cost_dispatches_zero`, `timing_started_missing`, `complete_but_unfinalized`). `apply_fix()` and `main()` signatures match their test call-sites. Contract-check tokens in Task 4 match the literal strings present in the Task 1/2 implementations.
