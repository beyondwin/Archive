# AgentRunway Operations Quality Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared AgentRunway diagnosis, quality policy, candidate ranking, and decision evidence so operations recovery and high-risk execution quality are driven by one tested decision model.

**Architecture:** The implementation adds focused pure modules first, then routes `status`, `inspect`, `resume`, AgentLens projection, and finally runner candidate execution through those modules. AgentRunway SQLite, run artifacts, and git state remain authoritative; AgentLens receives explanatory evidence but never decides execution state.

**Tech Stack:** Python 3.11+, argparse, SQLite, pytest, JSONL event journal, git worktrees, AgentLens evaluator projection.

---

## Scope Check

This plan covers one feature slice: AgentRunway operations and quality decisions.
It touches AgentRunway and AgentLens, but the surfaces are tightly coupled by the
existing `agentrunway.*` event contract. The work is deliberately staged so each
task is independently testable:

- Tasks 1-3 add pure decision models and tests.
- Task 4 routes status/inspect through read-only diagnosis.
- Task 5 records decision evidence and extends AgentLens projection.
- Task 6 moves gate retry decisions behind policy.
- Task 7 adds high-risk multi-candidate ranking.
- Task 8 extends resume planning with conflict redispatch/manual-action states.
- Task 9 updates docs and runs final verification.

No web dashboard, source checkout auto-apply, remote execution, CPE/CME bridge,
or automatic merge-conflict editing is part of this plan.

## Audit-Driven Refinements (2026-05-20)

A source review against `skills/agent-runway/scripts/agentrunway/` and
`AgentLens/src/agentlens/evaluator/agentrunway_events.py` surfaced gaps in the
draft tasks below. These refinements are required for v1 to match the design
in `docs/superpowers/specs/2026-05-20-agentrunway-operations-quality-engine-design.md`
§14. Apply them inline when the relevant task runs.

- **Task 3 (Diagnostics):** v1 intentionally covers only the subset of statuses
  and reasons listed in design §14.1; the remaining ones fall back to existing
  `needs_manual_action`/`unknown` defaults. The diagnostics module imports the
  existing `_process_alive` from `reconciliation` (or copies it with a `# TODO:
  share with reconciliation` comment); do not introduce a second slightly
  different implementation. `agentlens_health` returns the full
  `agentlens_summary` shape (`status`, `last_status`, `failed`, `last_error`).
- **Task 4 (Status/Inspect):** compute the diagnosis exactly once. `runner.status`
  attaches the diagnosis dict to the payload and `status.next_operator_action`
  reads `run.get("diagnosis", {}).get("next_action")` first, falling back to the
  legacy status-based hints. Extend `build_inspect_payload` to also include
  `candidate_rankings`, `quality_decisions`, and `conflict_redispatch_plans`
  derived from the event journal (filter `db.list_events()` by
  `agentrunway.candidate_ranked`, `agentrunway.quality_decision`,
  `agentrunway.conflict_redispatch_planned`) and a `quality_policy` snapshot
  with `{task_id, candidate_count, review_retry_budget,
  verification_retry_budget}` for each task derived from `db.list_tasks()` and
  the policy module.
- **Task 6 (Gate retry policy):** after replacing the review/verification
  retry branches, delete the now-unused
  `runner._verification_failure_actionable` helper in the same commit.
- **Task 7 (High-risk multi-candidate):**
  - Declare `review_retries = 0` and `verification_retries = 0` **inside** the
    outer `while len(merge_ready_candidate_ids) < target_candidate_count`
    loop, not above it. Each candidate gets a fresh gate-retry budget.
  - Add `WorkerState.NOT_SELECTED = "not_selected"` to `models.py` and update
    the ranking step in `runner.run` so non-selected candidates have both the
    merge_candidate row AND the worker row set to `not_selected`.
  - After ranking, if at least one candidate is in `merge_ready` status,
    overwrite `task.status` back to `merge_ready` (a prior per-candidate
    `block` path may have set it to `blocked`). If zero candidates reach
    `merge_ready`, leave the existing block state in place.
  - The score table is honest about v1 limitations: `_candidate_for_ranking`
    is documented inline (one comment) as "v1 stub — signals 3-7 are
    placeholders pending follow-up". Real signals require reading
    `review_result.json` / `verification_result.json` and comparing diff
    scope to `task.file_claims`; that is explicitly out-of-slice for this
    plan.
- **Task 8 (Conflict redispatch):** in `apply_reconciliation_plan`, when the
  `conflict_redispatch` action is recorded for the first time for a task,
  also call `record_conflict_redispatch_planned(journal, …)` so the
  AgentLens projection's `conflict_redispatch_plans` populates from real
  runs (currently only tests insert that event directly). `apply` still does
  not auto-replay the merge; it records the decision and the operator triggers
  a follow-up run. The `manual_action` branch already emits the failed-outcome
  resume action — leave it as-is.
- **Task 9 (Docs):** the README section explicitly notes (a) v1 candidate
  ranking is rank-by-id + evidence; (b) conflict redispatch is advisory
  (operator initiates the follow-up run); (c) high-risk tasks double local
  compute (2× implementer + 2× reviewer + 2× verifier per task).

## File Structure

### Create

| Path | Responsibility |
|---|---|
| `skills/agent-runway/scripts/agentrunway/quality_policy.py` | Pure policy decisions for candidate count, gate retry, and conflict redispatch budget. |
| `skills/agent-runway/scripts/agentrunway/candidate_selection.py` | Deterministic ranking for validated merge candidates. |
| `skills/agent-runway/scripts/agentrunway/diagnostics.py` | Read-only run diagnosis from run JSON, SQLite, worker/process state, merge queue, git state, and AgentLens health. |
| `skills/agent-runway/scripts/agentrunway/decision_events.py` | Small helpers that record quality decisions to the existing local journal and AgentLens emitter. |
| `skills/agent-runway/evals/test_quality_policy.py` | Unit tests for policy decisions. |
| `skills/agent-runway/evals/test_candidate_selection.py` | Unit tests for candidate ranking. |
| `skills/agent-runway/evals/test_diagnostics.py` | Unit tests for run diagnosis states and next actions. |
| `skills/agent-runway/evals/test_decision_events.py` | Unit tests for decision event payloads and journal writes. |

### Modify

| Path | Change |
|---|---|
| `skills/agent-runway/scripts/agentrunway/status.py` | Render `RunDiagnosis` and include diagnosis in inspect payloads. |
| `skills/agent-runway/scripts/agentrunway/reconciliation.py` | Use diagnosis and policy to plan safe retries, conflict redispatch, and manual-action blocks. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Use quality policy for gate retries, high-risk candidate count, candidate selection, and decision event recording. |
| `AgentLens/src/agentlens/evaluator/agentrunway_events.py` | Project `quality_decision`, `candidate_ranked`, and `conflict_redispatch_planned` evidence. |
| `AgentLens/tests/unit/test_agentrunway_events.py` | Add projection tests for the new decision events. |
| `skills/agent-runway/evals/fixtures/fake-bin/codex` | Allow deterministic high-risk candidate variation for runner tests. |
| `skills/agent-runway/evals/test_runner_production_e2e.py` | Cover high-risk multi-candidate selection and policy-backed retry. |
| `skills/agent-runway/evals/test_reconciliation.py` | Cover first conflict redispatch and repeated conflict manual action. |
| `skills/agent-runway/evals/test_artifact_graph_status.py` | Update inspect/status assertions for diagnosis fields. |
| `skills/agent-runway/README.md` | Document diagnosis, quality decisions, and high-risk candidate behavior. |
| `skills/agent-runway/references/agentlens-events.md` | Document new decision event types. |

---

## Task 1: Add Pure Quality Policy

```yaml agentrunway-task
task_id: task_001
title: Add Pure Quality Policy
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.6.2, S1.10.1, S1.14.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/quality_policy.py, mode: owned}
  - {path: skills/agent-runway/evals/test_quality_policy.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_quality_policy.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/quality_policy.py`
- Create: `skills/agent-runway/evals/test_quality_policy.py`

- [ ] **Step 1: Write failing policy tests**

Create `skills/agent-runway/evals/test_quality_policy.py`:

```python
from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.quality_policy import (
    conflict_decision,
    candidate_count_for_task,
    gate_retry_decision,
)


def _task(*, risk: str = "medium", acceptance: tuple[str, ...] = ("python -m pytest",)) -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=acceptance,
    )


def test_candidate_count_defaults_to_two_for_high_risk_only() -> None:
    assert candidate_count_for_task(_task(risk="low")) == 1
    assert candidate_count_for_task(_task(risk="medium")) == 1
    assert candidate_count_for_task(_task(risk="high")) == 2


def test_review_changes_requested_retries_once_when_actionable() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"findings": [{"severity": "major", "body": "tighten tests"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=0,
    )

    assert decision.action == "retry"
    assert decision.reason == "review_changes_requested"
    assert decision.outcome == "partial"


def test_review_changes_requested_blocks_after_budget() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"findings": [{"severity": "major", "body": "tighten tests"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=1,
    )

    assert decision.action == "block"
    assert decision.reason == "gate_budget_exhausted"
    assert decision.outcome == "failed"


def test_verifier_failed_without_actionable_signal_blocks() -> None:
    decision = gate_retry_decision(
        task=_task(acceptance=()),
        gate="verification",
        status="failed",
        result={"checks": []},
        candidate={"changed_files": []},
        previous_retries=0,
    )

    assert decision.action == "block"
    assert decision.reason == "verification_failed_not_actionable"


def test_verifier_blocked_never_retries() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="verification",
        status="blocked",
        result={"checks": [{"command": "python -m pytest", "status": "blocked"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=0,
    )

    assert decision.action == "block"
    assert decision.reason == "verification_blocked"


def test_first_conflict_can_redispatch_but_repeated_conflict_requires_manual_action() -> None:
    first = conflict_decision(task_id="task_001", previous_conflicts=0)
    repeated = conflict_decision(task_id="task_001", previous_conflicts=1)

    assert first.action == "redispatch"
    assert first.reason == "merge_conflict"
    assert repeated.action == "manual_action"
    assert repeated.reason == "repeated_merge_conflict"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_quality_policy.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.quality_policy'`.

- [ ] **Step 3: Implement the pure policy module**

Create `skills/agent-runway/scripts/agentrunway/quality_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import TaskSpec

PolicyAction = Literal["retry", "block", "continue", "redispatch", "manual_action"]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    outcome: Literal["success", "partial", "failed"]
    next_attempt: int | None = None


def candidate_count_for_task(task: TaskSpec) -> int:
    return 2 if task.risk == "high" else 1


def _has_actionable_review(result: dict[str, Any], candidate: dict[str, Any]) -> bool:
    findings = result.get("findings")
    changed_files = candidate.get("changed_files")
    return bool(findings) and bool(changed_files)


def _has_actionable_verification(task: TaskSpec, result: dict[str, Any], candidate: dict[str, Any]) -> bool:
    checks = result.get("checks")
    changed_files = candidate.get("changed_files")
    return bool(checks) or bool(changed_files) or bool(task.acceptance_commands)


def gate_retry_decision(
    *,
    task: TaskSpec,
    gate: Literal["review", "verification"],
    status: str,
    result: dict[str, Any],
    candidate: dict[str, Any],
    previous_retries: int,
) -> PolicyDecision:
    if gate == "review":
        if status == "approved":
            return PolicyDecision(action="continue", reason="review_approved", outcome="success")
        if status == "changes_requested" and previous_retries < 1 and _has_actionable_review(result, candidate):
            return PolicyDecision(
                action="retry",
                reason="review_changes_requested",
                outcome="partial",
                next_attempt=previous_retries + 2,
            )
        if status == "changes_requested":
            return PolicyDecision(action="block", reason="gate_budget_exhausted", outcome="failed")
        return PolicyDecision(action="block", reason="review_rejected", outcome="failed")

    if status == "passed":
        return PolicyDecision(action="continue", reason="verification_passed", outcome="success")
    if status == "blocked":
        return PolicyDecision(action="block", reason="verification_blocked", outcome="failed")
    if status == "failed" and previous_retries < 1 and _has_actionable_verification(task, result, candidate):
        return PolicyDecision(
            action="retry",
            reason="verification_failed",
            outcome="partial",
            next_attempt=previous_retries + 2,
        )
    if status == "failed":
        return PolicyDecision(action="block", reason="verification_failed_not_actionable", outcome="failed")
    return PolicyDecision(action="block", reason="verification_rejected", outcome="failed")


def conflict_decision(*, task_id: str, previous_conflicts: int) -> PolicyDecision:
    if previous_conflicts < 1:
        return PolicyDecision(action="redispatch", reason="merge_conflict", outcome="partial", next_attempt=previous_conflicts + 2)
    return PolicyDecision(action="manual_action", reason="repeated_merge_conflict", outcome="failed")
```

- [ ] **Step 4: Run policy tests and verify they pass**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_quality_policy.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/quality_policy.py skills/agent-runway/evals/test_quality_policy.py
git commit -m "feat: add AgentRunway quality policy"
```

Expected: commit succeeds.

## Task 2: Add Deterministic Candidate Selection

```yaml agentrunway-task
task_id: task_002
title: Add Deterministic Candidate Selection
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.6.3, S1.10.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/candidate_selection.py, mode: owned}
  - {path: skills/agent-runway/evals/test_candidate_selection.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_candidate_selection.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/candidate_selection.py`
- Create: `skills/agent-runway/evals/test_candidate_selection.py`

- [ ] **Step 1: Write failing candidate selection tests**

Create `skills/agent-runway/evals/test_candidate_selection.py`:

```python
from __future__ import annotations

from agentrunway.candidate_selection import rank_candidates, select_candidate


def _candidate(candidate_id: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": candidate_id,
        "task_id": "task_001",
        "worker_id": f"task_001-implementer-{candidate_id:03d}",
        "status": "validated",
        "verification_status": "passed",
        "review_status": "approved",
        "file_claim_violation": False,
        "required_artifacts_present": True,
        "acceptance_evidence_present": True,
        "scope_match": True,
        "unexpected_changed_files": 0,
    }
    data.update(overrides)
    return data


def test_verifier_passed_candidate_wins() -> None:
    ranked = rank_candidates(
        [
            _candidate(2, verification_status="failed"),
            _candidate(1, verification_status="passed"),
        ]
    )

    assert ranked[0].candidate_id == 1
    assert ranked[0].rank == 1
    assert "verifier_passed" in ranked[0].reasons


def test_file_claim_violation_loses_even_with_lower_candidate_id() -> None:
    selected = select_candidate(
        [
            _candidate(1, file_claim_violation=True),
            _candidate(2),
        ]
    )

    assert selected.selected_candidate_id == 2
    assert selected.scores[0].candidate_id == 2


def test_missing_artifact_and_acceptance_evidence_lower_score() -> None:
    selected = select_candidate(
        [
            _candidate(1, required_artifacts_present=False, acceptance_evidence_present=False),
            _candidate(2, unexpected_changed_files=1),
        ]
    )

    assert selected.selected_candidate_id == 2
    assert selected.scores[0].score > selected.scores[1].score


def test_tie_breaks_by_candidate_id() -> None:
    selected = select_candidate([_candidate(8), _candidate(7)])

    assert selected.selected_candidate_id == 7
    assert [score.candidate_id for score in selected.scores] == [7, 8]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_candidate_selection.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.candidate_selection'`.

- [ ] **Step 3: Implement candidate ranking**

Create `skills/agent-runway/scripts/agentrunway/candidate_selection.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: int
    rank: int
    score: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "reasons": list(self.reasons)}


@dataclass(frozen=True)
class CandidateSelection:
    selected_candidate_id: int | None
    scores: tuple[CandidateScore, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_candidate_id": self.selected_candidate_id,
            "scores": [score.to_dict() for score in self.scores],
        }


def _bool(candidate: dict[str, Any], key: str, default: bool = False) -> bool:
    value = candidate.get(key, default)
    return bool(value)


def _candidate_id(candidate: dict[str, Any]) -> int:
    return int(candidate["id"])


def _score(candidate: dict[str, Any]) -> tuple[int, tuple[str, ...]]:
    score = 0
    reasons: list[str] = []
    if candidate.get("verification_status") == "passed" or candidate.get("status") in {"merge_ready", "merged"}:
        score += 40
        reasons.append("verifier_passed")
    if candidate.get("review_status") == "approved":
        score += 25
        reasons.append("reviewer_approved")
    if not _bool(candidate, "file_claim_violation"):
        score += 15
        reasons.append("file_claims_clean")
    if _bool(candidate, "required_artifacts_present", True):
        score += 8
        reasons.append("required_artifacts_present")
    if _bool(candidate, "acceptance_evidence_present", False):
        score += 6
        reasons.append("acceptance_evidence_present")
    if _bool(candidate, "scope_match", True):
        score += 4
        reasons.append("scope_match")
    unexpected = int(candidate.get("unexpected_changed_files", 0) or 0)
    score -= unexpected
    if unexpected:
        reasons.append("unexpected_changed_files")
    return score, tuple(reasons)


def rank_candidates(candidates: list[dict[str, Any]]) -> list[CandidateScore]:
    raw: list[tuple[int, int, tuple[str, ...]]] = []
    for candidate in candidates:
        score, reasons = _score(candidate)
        raw.append((_candidate_id(candidate), score, reasons))
    ordered = sorted(raw, key=lambda item: (-item[1], item[0]))
    return [
        CandidateScore(candidate_id=candidate_id, rank=index + 1, score=score, reasons=reasons)
        for index, (candidate_id, score, reasons) in enumerate(ordered)
    ]


def select_candidate(candidates: list[dict[str, Any]]) -> CandidateSelection:
    scores = tuple(rank_candidates(candidates))
    selected = scores[0].candidate_id if scores else None
    return CandidateSelection(selected_candidate_id=selected, scores=scores)
```

- [ ] **Step 4: Run candidate selection tests and verify they pass**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_candidate_selection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/candidate_selection.py skills/agent-runway/evals/test_candidate_selection.py
git commit -m "feat: rank AgentRunway candidates deterministically"
```

Expected: commit succeeds.

## Task 3: Add Read-Only Run Diagnostics

```yaml agentrunway-task
task_id: task_003
title: Add Read-Only Run Diagnostics
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.6.1, S1.7.2, S1.10.1, S1.14.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/diagnostics.py, mode: owned}
  - {path: skills/agent-runway/evals/test_diagnostics.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_diagnostics.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/diagnostics.py`
- Create: `skills/agent-runway/evals/test_diagnostics.py`

- [ ] **Step 1: Write failing diagnostics tests**

Create `skills/agent-runway/evals/test_diagnostics.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.diagnostics import diagnose_run
from agentrunway.models import FileClaim, TaskSpec


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="medium",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _run_json(run_dir: Path, status: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "run_001",
        "status": status,
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "tasks": [],
    }
    payload.update(extra)
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_finished_run_is_healthy(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    run_json = _run_json(run_dir, "finished")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "finished"
    assert diagnosis.reason == "none"
    assert diagnosis.next_action == "apply or inspect artifacts"


def test_blocked_task_reports_blocked_by_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "blocked")
    run_json = _run_json(run_dir, "blocked")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "blocked_by_gate"
    assert diagnosis.reason == "gate_budget_exhausted"
    assert diagnosis.blocked_tasks == ["task_001"]


def test_dead_worker_missing_result_needs_resume(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="worker",
        state="running",
        handle_json={"pid": 999999},
    )
    run_json = _run_json(run_dir, "running")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "needs_resume"
    assert diagnosis.reason == "dead_worker_missing_result"
    assert "resume" in diagnosis.safe_actions


def test_merge_conflict_reports_conflict_redispatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merge_conflict",
    )
    run_json = _run_json(run_dir, "blocked")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "needs_conflict_redispatch"
    assert diagnosis.reason == "merge_conflict"
    assert diagnosis.conflict == {"task_id": "task_001", "candidate_id": 1}
```

- [ ] **Step 2: Run diagnostics tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_diagnostics.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.diagnostics'`.

- [ ] **Step 3: Implement diagnostics**

Create `skills/agent-runway/scripts/agentrunway/diagnostics.py`:

```python
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .db import AgentRunwayDb


@dataclass(frozen=True)
class RunDiagnosis:
    run_id: str
    status: str
    reason: str
    next_action: str
    safe_actions: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)
    conflict: dict[str, Any] | None = None
    agentlens_health: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _process_alive(handle_json: dict[str, Any]) -> bool:
    pid = handle_json.get("pid")
    if pid is None and isinstance(handle_json.get("process"), dict):
        pid = handle_json["process"].get("pid")
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _agentlens_health(db: AgentRunwayDb) -> dict[str, Any]:
    summary = db.agentlens_summary()
    return {
        "status": summary.get("run_status") or summary.get("last_status") or "unknown",
        "last_status": summary.get("last_status"),
        "failed": summary.get("failed", 0),
        "last_error": summary.get("last_error"),
    }


def diagnose_run(*, run_json: dict[str, Any], db: AgentRunwayDb) -> RunDiagnosis:
    run_id = str(run_json.get("run_id") or "unknown")
    run_status = str(run_json.get("status") or "unknown")
    agentlens = _agentlens_health(db)

    for candidate in db.list_merge_candidates():
        if candidate["status"] == "merge_conflict":
            return RunDiagnosis(
                run_id=run_id,
                status="needs_conflict_redispatch",
                reason="merge_conflict",
                next_action=f"agentrunway resume --run {run_id} --dry-run",
                safe_actions=["resume", "inspect"],
                conflict={"task_id": candidate["task_id"], "candidate_id": int(candidate["id"])},
                agentlens_health=agentlens,
            )

    blocked_tasks = [
        str(task["task_id"])
        for task in db.list_tasks()
        if str(task.get("status")) == "blocked"
    ]
    if blocked_tasks:
        return RunDiagnosis(
            run_id=run_id,
            status="blocked_by_gate",
            reason="gate_budget_exhausted",
            next_action=f"agentrunway inspect --run {run_id}",
            safe_actions=["inspect", "resume"],
            blocked_tasks=blocked_tasks,
            agentlens_health=agentlens,
        )

    for worker in db.list_workers():
        if worker["state"] == "running" and not _process_alive(worker.get("handle_json", {})):
            return RunDiagnosis(
                run_id=run_id,
                status="needs_resume",
                reason="dead_worker_missing_result",
                next_action=f"agentrunway resume --run {run_id}",
                safe_actions=["resume", "inspect"],
                agentlens_health=agentlens,
            )

    if run_status == "finished":
        return RunDiagnosis(
            run_id=run_id,
            status="finished",
            reason="none",
            next_action="apply or inspect artifacts",
            safe_actions=["apply", "inspect"],
            agentlens_health=agentlens,
        )
    if run_status in {"created", "running"}:
        return RunDiagnosis(
            run_id=run_id,
            status="running",
            reason="none",
            next_action="continue monitoring",
            safe_actions=["status", "inspect"],
            agentlens_health=agentlens,
        )
    if run_status in {"blocked", "failed"}:
        return RunDiagnosis(
            run_id=run_id,
            status="needs_manual_action",
            reason="blocked",
            next_action=f"agentrunway inspect --run {run_id}",
            safe_actions=["inspect"],
            manual_actions=["inspect blocked run"],
            agentlens_health=agentlens,
        )
    if run_status == "cancelled":
        return RunDiagnosis(
            run_id=run_id,
            status="needs_manual_action",
            reason="cancelled",
            next_action="inspect events before restarting",
            safe_actions=["inspect"],
            manual_actions=["inspect cancelled run"],
            agentlens_health=agentlens,
        )
    return RunDiagnosis(
        run_id=run_id,
        status="missing" if run_status == "missing" else "needs_manual_action",
        reason="unknown",
        next_action="inspect run state",
        safe_actions=["inspect"],
        manual_actions=["inspect run state"],
        agentlens_health=agentlens,
    )
```

- [ ] **Step 4: Run diagnostics tests and verify they pass**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_diagnostics.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/diagnostics.py skills/agent-runway/evals/test_diagnostics.py
git commit -m "feat: diagnose AgentRunway run state"
```

Expected: commit succeeds.

## Task 4: Route Status and Inspect Through Diagnosis

```yaml agentrunway-task
task_id: task_004
title: Route Status and Inspect Through Diagnosis
risk: medium
phase: implementation
dependencies: [task_003]
spec_refs: [S1.7.2, S1.9, S1.10.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_artifact_graph_status.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_artifact_graph_status.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/evals/test_artifact_graph_status.py`

- [ ] **Step 1: Write failing status/inspect tests**

Append these tests to `skills/agent-runway/evals/test_artifact_graph_status.py`:

```python
def test_inspect_payload_includes_diagnosis(tmp_path: Path) -> None:
    from agentrunway.db import AgentRunwayDb
    from agentrunway.status import build_inspect_payload

    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    run_json = {
        "run_id": "run_001",
        "status": "finished",
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "tasks": [],
    }

    payload = build_inspect_payload(run_json=run_json, db=db)

    assert payload["diagnosis"]["status"] == "finished"
    assert payload["diagnosis"]["next_action"] == "apply or inspect artifacts"


def test_format_run_status_prefers_diagnosis_next_action() -> None:
    from agentrunway.status import format_run_status

    text = format_run_status(
        {
            "run_id": "run_001",
            "status": "blocked",
            "diagnosis": {
                "status": "blocked_by_gate",
                "reason": "gate_budget_exhausted",
                "next_action": "agentrunway inspect --run run_001",
            },
            "agentlens": {"last_status": "agentlens_emitted"},
        }
    )

    assert "diagnosis=blocked_by_gate" in text
    assert "reason=gate_budget_exhausted" in text
    assert "next_action=agentrunway inspect --run run_001" in text
```

- [ ] **Step 2: Run targeted tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_artifact_graph_status.py::test_inspect_payload_includes_diagnosis evals/test_artifact_graph_status.py::test_format_run_status_prefers_diagnosis_next_action -v
```

Expected: FAIL because `diagnosis` is not yet included/rendered.

- [ ] **Step 3: Update status formatting and inspect payload**

Modify `skills/agent-runway/scripts/agentrunway/status.py`:

```python
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .artifact_graph import build_artifact_graph
from .db import AgentRunwayDb
from .diagnostics import diagnose_run


def next_operator_action(run_json: dict[str, Any], agentlens: dict[str, Any]) -> str:
    db_path = run_json.get("state_db")
    if isinstance(db_path, str) and db_path:
        try:
            db = AgentRunwayDb.open(Path(db_path))
            return diagnose_run(run_json=run_json, db=db).next_action
        except Exception:
            pass
    status = str(run_json.get("status") or "unknown")
    if status == "finished":
        return "apply or inspect artifacts"
    if status in {"blocked", "failed"}:
        return "inspect blocked tasks and run resume --dry-run"
    if status == "cancelled":
        return "inspect events before restarting"
    if str(agentlens.get("last_status")) == "agentlens_failed" or int(agentlens.get("failed", 0) or 0) > 0:
        return "inspect AgentLens failures and continue monitoring"
    if status in {"created", "running"}:
        return "continue monitoring"
    if status == "missing":
        return "none"
    return "inspect run state"


def format_run_status(run: dict[str, object]) -> str:
    tasks = run.get("tasks") if isinstance(run.get("tasks"), list) else []
    counts = Counter(str(task.get("status", "unknown")) for task in tasks if isinstance(task, dict))
    suffix = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    agentlens = run.get("agentlens") if isinstance(run.get("agentlens"), dict) else {}
    diagnosis = run.get("diagnosis") if isinstance(run.get("diagnosis"), dict) else {}
    next_action = diagnosis.get("next_action") or run.get("next_action")
    diagnosis_bits = ""
    if diagnosis:
        diagnosis_bits = f" diagnosis={diagnosis.get('status')} reason={diagnosis.get('reason')}"
    return (
        f"{run.get('run_id')} status={run.get('status')} {suffix}{diagnosis_bits} "
        f"agentlens={agentlens.get('last_status', 'unknown')} next_action={next_action}"
    ).strip()


def build_inspect_payload(*, run_json: dict[str, Any], db: AgentRunwayDb) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    graph = build_artifact_graph(run_dir=run_dir, db=db)
    coverage_path = run_dir / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else graph["coverage"]
    agentlens = db.agentlens_summary()
    diagnosis = diagnose_run(run_json=run_json, db=db).to_dict()
    return {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "run_dir": str(run_dir),
        "tasks": db.list_tasks(),
        "workers": db.list_workers(),
        "merge_candidates": db.list_merge_candidates(),
        "artifact_graph": graph,
        "coverage": coverage,
        "agentlens": agentlens,
        "diagnosis": diagnosis,
        "next_action": diagnosis["next_action"],
    }


def format_inspect_payload(payload: dict[str, Any]) -> str:
    agentlens = payload.get("agentlens", {})
    coverage = payload.get("coverage", {})
    diagnosis = payload.get("diagnosis", {})
    return (
        f"{payload.get('run_id')} status={payload.get('status')} "
        f"diagnosis={diagnosis.get('status')} "
        f"reason={diagnosis.get('reason')} "
        f"tasks={len(payload.get('tasks', []))} "
        f"workers={len(payload.get('workers', []))} "
        f"covered={len(coverage.get('covered', []))} "
        f"blocked={len(coverage.get('blocked', []))} "
        f"agentlens_failed={agentlens.get('failed', 0)} "
        f"next_action={payload.get('next_action')}"
    )
```

- [ ] **Step 4: Update `runner.status` to include diagnosis**

Modify the `status(run_id: str)` function in `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
def status(run_id: str) -> dict[str, Any]:
    data = _load_run_json(run_id)
    if data is None:
        return _missing(run_id)
    from .diagnostics import diagnose_run
    from .status import next_operator_action

    db = AgentRunwayDb.open(Path(data["state_db"]))
    agentlens = db.agentlens_summary()
    diagnosis = diagnose_run(run_json=data, db=db).to_dict()
    return {
        "run_id": run_id,
        "status": data.get("status"),
        "run_dir": data.get("run_dir"),
        "agentlens": agentlens,
        "diagnosis": diagnosis,
        "next_action": diagnosis.get("next_action") or next_operator_action(data, agentlens),
    }
```

- [ ] **Step 5: Run status tests**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_artifact_graph_status.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/status.py skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_artifact_graph_status.py
git commit -m "feat: surface AgentRunway diagnosis in status"
```

Expected: commit succeeds.

## Task 5: Record and Project Decision Events

```yaml agentrunway-task
task_id: task_005
title: Record and Project Decision Events
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.6.4, S1.7.4, S1.10.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/decision_events.py, mode: owned}
  - {path: skills/agent-runway/evals/test_decision_events.py, mode: owned}
  - {path: AgentLens/src/agentlens/evaluator/agentrunway_events.py, mode: owned}
  - {path: AgentLens/tests/unit/test_agentrunway_events.py, mode: owned}
  - {path: skills/agent-runway/references/agentlens-events.md, mode: shared_append}
acceptance_commands: [python3 -m pytest evals/test_decision_events.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/decision_events.py`
- Create: `skills/agent-runway/evals/test_decision_events.py`
- Modify: `AgentLens/src/agentlens/evaluator/agentrunway_events.py`
- Modify: `AgentLens/tests/unit/test_agentrunway_events.py`
- Modify: `skills/agent-runway/references/agentlens-events.md`

- [ ] **Step 1: Write failing decision event tests**

Create `skills/agent-runway/evals/test_decision_events.py`:

```python
from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.decision_events import record_candidate_ranked, record_quality_decision
from agentrunway.events import EventJournal


def test_record_quality_decision_writes_bounded_event(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)

    event = record_quality_decision(
        journal,
        run_id="run_001",
        task_id="task_001",
        decision="retry",
        reason="verification_failed",
        outcome="partial",
        diagnosis_status="needs_resume",
    )

    assert event.event_type == "agentrunway.quality_decision"
    assert event.payload["decision"] == "retry"
    assert event.payload["reason"] == "verification_failed"
    assert event.payload["diagnosis_status"] == "needs_resume"


def test_record_candidate_ranked_writes_scores(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)

    event = record_candidate_ranked(
        journal,
        run_id="run_001",
        task_id="task_001",
        selected_candidate_id=7,
        scores=[{"candidate_id": 7, "rank": 1, "score": 96, "reasons": ["verifier_passed"]}],
    )

    assert event.event_type == "agentrunway.candidate_ranked"
    assert event.payload["selected_candidate_id"] == 7
    assert event.payload["scores"][0]["reasons"] == ["verifier_passed"]
```

- [ ] **Step 2: Run decision event tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_decision_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.decision_events'`.

- [ ] **Step 3: Implement decision event helpers**

Create `skills/agent-runway/scripts/agentrunway/decision_events.py`:

```python
from __future__ import annotations

from typing import Any

from .events import EventJournal, EventRecord, build_event_payload


def record_quality_decision(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    decision: str,
    reason: str,
    outcome: str,
    diagnosis_status: str | None = None,
    **extra: Any,
) -> EventRecord:
    return journal.record(
        "agentrunway.quality_decision",
        build_event_payload(
            run_id,
            "quality",
            outcome,
            "quality decision",
            task_id=task_id,
            decision=decision,
            reason=reason,
            diagnosis_status=diagnosis_status,
            **extra,
        ),
    )


def record_candidate_ranked(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    selected_candidate_id: int | None,
    scores: list[dict[str, Any]],
) -> EventRecord:
    return journal.record(
        "agentrunway.candidate_ranked",
        build_event_payload(
            run_id,
            "quality",
            "success" if selected_candidate_id is not None else "failed",
            "candidate ranked",
            task_id=task_id,
            decision="select_candidate",
            selected_candidate_id=selected_candidate_id,
            scores=scores,
        ),
    )


def record_conflict_redispatch_planned(
    journal: EventJournal,
    *,
    run_id: str,
    task_id: str,
    candidate_id: int,
    reason: str,
) -> EventRecord:
    return journal.record(
        "agentrunway.conflict_redispatch_planned",
        build_event_payload(
            run_id,
            "resume",
            "partial",
            "conflict redispatch planned",
            task_id=task_id,
            candidate_id=candidate_id,
            reason=reason,
            decision="conflict_redispatch",
        ),
    )
```

- [ ] **Step 4: Add AgentLens projection tests**

Append to `AgentLens/tests/unit/test_agentrunway_events.py`:

```python
def test_projection_tracks_quality_decisions_and_candidate_ranking() -> None:
    projection = project_agentrunway_events(
        [
            _event(
                "agentrunway.quality_decision",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "decision": "retry",
                    "reason": "verification_failed",
                    "diagnosis_status": "needs_resume",
                },
            ),
            _event(
                "agentrunway.candidate_ranked",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "selected_candidate_id": 7,
                    "scores": [{"candidate_id": 7, "rank": 1, "score": 96, "reasons": ["verifier_passed"]}],
                },
                ts="2026-05-20T00:00:01Z",
            ),
            _event(
                "agentrunway.conflict_redispatch_planned",
                {
                    "run_id": "ar-001",
                    "task_id": "task_001",
                    "candidate_id": 7,
                    "reason": "merge_conflict",
                },
                ts="2026-05-20T00:00:02Z",
            ),
        ]
    )

    assert projection["quality_decisions"] == [
        {
            "task_id": "task_001",
            "decision": "retry",
            "reason": "verification_failed",
            "diagnosis_status": "needs_resume",
        }
    ]
    assert projection["candidate_rankings"][0]["selected_candidate_id"] == 7
    assert projection["conflict_redispatch_plans"] == [
        {"task_id": "task_001", "candidate_id": 7, "reason": "merge_conflict"}
    ]
```

- [ ] **Step 5: Run AgentLens projection test and verify it fails**

Run:

```bash
cd AgentLens
python -m pytest tests/unit/test_agentrunway_events.py::test_projection_tracks_quality_decisions_and_candidate_ranking -v
```

Expected: FAIL with missing `quality_decisions` or `candidate_rankings` keys.

- [ ] **Step 6: Extend AgentLens projection**

Modify `_empty_projection()` in `AgentLens/src/agentlens/evaluator/agentrunway_events.py` to add:

```python
        "quality_decisions": [],
        "candidate_rankings": [],
        "conflict_redispatch_plans": [],
```

Then add these branches inside `project_agentrunway_events()` after the existing merge branches:

```python
        elif event_name == "quality_decision":
            projection["quality_decisions"].append(
                {
                    "task_id": payload.get("task_id"),
                    "decision": payload.get("decision"),
                    "reason": payload.get("reason"),
                    "diagnosis_status": payload.get("diagnosis_status"),
                }
            )
        elif event_name == "candidate_ranked":
            projection["candidate_rankings"].append(
                {
                    "task_id": payload.get("task_id"),
                    "selected_candidate_id": payload.get("selected_candidate_id"),
                    "scores": payload.get("scores") if isinstance(payload.get("scores"), list) else [],
                }
            )
        elif event_name == "conflict_redispatch_planned":
            projection["conflict_redispatch_plans"].append(
                {
                    "task_id": payload.get("task_id"),
                    "candidate_id": payload.get("candidate_id"),
                    "reason": str(payload.get("reason") or "merge_conflict"),
                }
            )
```

- [ ] **Step 7: Run decision event and projection tests**

Run:

```bash
cd skills/agent-runway && python3 -m pytest evals/test_decision_events.py -v
cd ../..
cd AgentLens && python -m pytest tests/unit/test_agentrunway_events.py::test_projection_tracks_quality_decisions_and_candidate_ranking -v
```

Expected: PASS.

- [ ] **Step 8: Update AgentRunway event reference docs**

Append this section to `skills/agent-runway/references/agentlens-events.md`:

```markdown
## Quality Decision Events

AgentRunway emits decision events when policy or candidate ranking changes the
execution path:

- `agentrunway.quality_decision`: retry, block, continue, or manual-action decisions.
- `agentrunway.candidate_ranked`: deterministic candidate score table and selected candidate.
- `agentrunway.conflict_redispatch_planned`: first merge conflict converted into a safe redispatch plan.

These events are explanatory evidence. AgentRunway SQLite state remains the
source of truth for task, worker, and merge status.
```

- [ ] **Step 9: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/decision_events.py skills/agent-runway/evals/test_decision_events.py AgentLens/src/agentlens/evaluator/agentrunway_events.py AgentLens/tests/unit/test_agentrunway_events.py skills/agent-runway/references/agentlens-events.md
git commit -m "feat: record AgentRunway quality decisions"
```

Expected: commit succeeds.

## Task 6: Use Quality Policy for Gate Retries

```yaml agentrunway-task
task_id: task_006
title: Use Quality Policy for Gate Retries
risk: medium
phase: implementation
dependencies: [task_001, task_005]
spec_refs: [S1.6.2, S1.7.1, S1.10.2, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_runner_production_e2e.py::test_review_changes_requested_redispatches_implementer_once evals/test_runner_production_e2e.py::test_verifier_failed_redispatches_implementer_once evals/test_runner_production_e2e.py::test_verifier_blocked_does_not_redispatch -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add a runner test for policy-backed verifier block**

Append to `skills/agent-runway/evals/test_runner_production_e2e.py`:

```python
def test_verifier_blocked_does_not_redispatch(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_plan(git_repo, path="src/verify_blocked.py")
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/verify_blocked.py"
    env["AGENTRUNWAY_FAKE_VERIFY_STATUS"] = "blocked"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "codex",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    workers = conn.execute("SELECT role FROM workers ORDER BY worker_id").fetchall()
    events = conn.execute("SELECT event_type, payload_json FROM agentlens_events ORDER BY id").fetchall()
    quality_payloads = [
        json.loads(row["payload_json"])
        for row in events
        if row["event_type"] == "agentrunway.quality_decision"
    ]

    assert payload["status"] == "blocked"
    assert [row["role"] for row in workers] == ["implementer", "reviewer", "verifier"]
    assert quality_payloads[-1]["decision"] == "block"
    assert quality_payloads[-1]["reason"] == "verification_blocked"
```

- [ ] **Step 2: Run the new runner test and verify it fails**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_runner_production_e2e.py::test_verifier_blocked_does_not_redispatch -v
```

Expected: FAIL because no `quality_decision` event is emitted yet.

- [ ] **Step 3: Import policy and decision events in runner**

Add imports to `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
from .decision_events import record_quality_decision
from .quality_policy import gate_retry_decision
```

- [ ] **Step 4: Replace review retry branch with policy decision**

In `runner.run`, replace the `if review_status == "changes_requested":` branch with:

```python
                if review_status != "approved":
                    decision = gate_retry_decision(
                        task=task,
                        gate="review",
                        status=review_status,
                        result=review,
                        candidate=_merge_candidate(db, candidate_id),
                        previous_retries=review_retries,
                    )
                    record_quality_decision(
                        journal,
                        run_id=run_id,
                        task_id=task.task_id,
                        decision=decision.action,
                        reason=decision.reason,
                        outcome=decision.outcome,
                        diagnosis_status=None,
                    )
                    db.set_merge_candidate_status(candidate_id, "changes_requested" if review_status == "changes_requested" else "review_rejected")
                    if decision.action == "retry":
                        review_retries += 1
                        implementer_context = _retry_context(decision.reason, review, _merge_candidate(db, candidate_id))
                        _record_gate_retry(
                            journal,
                            run_id=run_id,
                            task_id=task.task_id,
                            reason=decision.reason,
                            next_attempt=implementer_attempt + 1,
                        )
                        continue
                    db.set_task_status(task.task_id, "blocked")
                    _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason=decision.reason)
                    break
```

- [ ] **Step 5: Replace verification retry branch with policy decision**

In `runner.run`, replace the `verification_status` failed/blocked branch after the `passed` case with:

```python
                decision = gate_retry_decision(
                    task=task,
                    gate="verification",
                    status=verification_status,
                    result=verification,
                    candidate=_merge_candidate(db, candidate_id),
                    previous_retries=verification_retries,
                )
                record_quality_decision(
                    journal,
                    run_id=run_id,
                    task_id=task.task_id,
                    decision=decision.action,
                    reason=decision.reason,
                    outcome=decision.outcome,
                    diagnosis_status=None,
                )
                if verification_status == "failed":
                    db.set_merge_candidate_status(candidate_id, "verification_failed")
                else:
                    db.set_merge_candidate_status(candidate_id, "verification_blocked")
                if decision.action == "retry":
                    verification_retries += 1
                    implementer_context = _retry_context(decision.reason, verification, _merge_candidate(db, candidate_id))
                    _record_gate_retry(
                        journal,
                        run_id=run_id,
                        task_id=task.task_id,
                        reason=decision.reason,
                        next_attempt=implementer_attempt + 1,
                    )
                    continue
                db.set_task_status(task.task_id, "blocked")
                _record_run_blocked(journal, run_id=run_id, task_id=task.task_id, reason=decision.reason)
                break
```

- [ ] **Step 6: Run gate-related tests**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_runner_production_e2e.py::test_review_changes_requested_redispatches_implementer_once evals/test_runner_production_e2e.py::test_verifier_failed_redispatches_implementer_once evals/test_runner_production_e2e.py::test_verifier_blocked_does_not_redispatch -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: apply AgentRunway gate retry policy"
```

Expected: commit succeeds.

## Task 7: Add High-Risk Multi-Candidate Selection

```yaml agentrunway-task
task_id: task_007
title: Add High-Risk Multi-Candidate Selection
risk: high
phase: implementation
dependencies: [task_002, task_005, task_006]
spec_refs: [S1.6.3, S1.7.1, S1.10.2, S1.14.2, S1.14.3]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/models.py, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/codex, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/evals/fixtures/fake-bin/codex`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`

- [ ] **Step 1: Add high-risk plan helper and failing e2e test**

Append this helper and test to `skills/agent-runway/evals/test_runner_production_e2e.py`:

```python
def _write_high_risk_plan(repo: Path) -> tuple[Path, Path]:
    spec = repo / "spec.md"
    plan = repo / "plan.md"
    spec.write_text("# Spec\n\n## A\n\nAdd high-risk worker file.\n", encoding="utf-8")
    plan.write_text(
        "## Task 1: A\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: A\n"
        "risk: high\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1.1]\n"
        "file_claims:\n"
        "  - {path: src/high_risk.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Add high-risk worker file.\n",
        encoding="utf-8",
    )
    return plan, spec


def test_high_risk_task_ranks_two_candidates(git_repo: Path, isolated_home: Path) -> None:
    plan, spec = _write_high_risk_plan(git_repo)
    env = os.environ.copy()
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env['PATH']}"
    env["AGENTRUNWAY_FAKE_TARGET"] = "src/high_risk.py"
    env["AGENTRUNWAY_FAKE_CANDIDATE_VARIANT"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--plan",
            str(plan),
            "--spec",
            str(spec),
            "--adapter",
            "codex",
        ],
        cwd=git_repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    conn = sqlite3.connect(payload["state_db"])
    conn.row_factory = sqlite3.Row
    implementers = conn.execute("SELECT worker_id FROM workers WHERE role='implementer' ORDER BY worker_id").fetchall()
    ranking = conn.execute(
        "SELECT payload_json FROM agentlens_events WHERE event_type='agentrunway.candidate_ranked' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert payload["status"] == "finished"
    assert [row["worker_id"] for row in implementers] == [
        "task_001-implementer-001",
        "task_001-implementer-002",
    ]
    assert json.loads(ranking["payload_json"])["selected_candidate_id"] is not None
```

- [ ] **Step 2: Run the high-risk test and verify it fails**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v
```

Expected: FAIL because high-risk still dispatches one implementer.

- [ ] **Step 3: Update fake Codex to vary candidate output by attempt**

In `skills/agent-runway/evals/fixtures/fake-bin/codex`, replace the implementer target write:

```python
    target.write_text("VALUE = 'codex'\n", encoding="utf-8")
```

with:

```python
    variant_enabled = os.environ.get("AGENTRUNWAY_FAKE_CANDIDATE_VARIANT") == "1"
    try:
        attempt = int(os.environ["AGENTRUNWAY_WORKER_ID"].rsplit("-", 1)[1])
    except (KeyError, IndexError, ValueError):
        attempt = 1
    value = "codex" if not variant_enabled else f"codex-{attempt}"
    target.write_text(f"VALUE = '{value}'\n", encoding="utf-8")
```

- [ ] **Step 4: Import candidate policy/selection in runner**

Add imports to `skills/agent-runway/scripts/agentrunway/runner.py`:

```python
from .candidate_selection import select_candidate
from .decision_events import record_candidate_ranked, record_quality_decision
from .quality_policy import candidate_count_for_task
```

If `record_quality_decision` was already imported in Task 6, keep one combined import.

- [ ] **Step 5: Add a local helper to normalize merge candidates for ranking**

Add this helper near `_merge_candidate` in `runner.py`:

```python
def _candidate_for_ranking(candidate: dict[str, Any]) -> dict[str, Any]:
    status = str(candidate.get("status") or "")
    return {
        "id": int(candidate["id"]),
        "task_id": candidate["task_id"],
        "worker_id": candidate["worker_id"],
        "status": status,
        "verification_status": "passed" if status in {"merge_ready", "merged"} else status,
        "review_status": "approved" if status in {"merge_ready", "merged"} else status,
        "file_claim_violation": False,
        "required_artifacts_present": True,
        "acceptance_evidence_present": bool(candidate.get("commits")),
        "scope_match": True,
        "unexpected_changed_files": 0,
    }
```

- [ ] **Step 6: Dispatch high-risk candidate attempts before ranking**

In the non-local task branch of `runner.run`, add this immediately before the
current implementer retry loop:

```python
            target_candidate_count = candidate_count_for_task(task)
            merge_ready_candidate_ids: list[int] = []
```

Then replace the existing implementer retry loop header:

```python
            while True:
```

with:

```python
            while len(merge_ready_candidate_ids) < target_candidate_count:
```

Finally, replace the `break` at the end of the existing
`if verification_status == "passed":` branch with this block:

```python
                    merge_ready_candidate_ids.append(candidate_id)
                    if len(merge_ready_candidate_ids) >= target_candidate_count:
                        break
                    implementer_context = None
                    continue
```

The other block/retry branches keep their existing `break` or `continue`
statements. Low and medium tasks keep the existing single-candidate behavior
because `target_candidate_count` is 1.

- [ ] **Step 7: Rank merge-ready candidates and record decision**

After the candidate loop for a task finishes, before the final merge loop, add:

```python
            ready_candidates = [
                candidate
                for candidate in db.list_merge_candidates()
                if candidate["task_id"] == task.task_id and candidate["status"] == "merge_ready"
            ]
            if ready_candidates:
                selection = select_candidate([_candidate_for_ranking(candidate) for candidate in ready_candidates])
                record_candidate_ranked(
                    journal,
                    run_id=run_id,
                    task_id=task.task_id,
                    selected_candidate_id=selection.selected_candidate_id,
                    scores=[score.to_dict() for score in selection.scores],
                )
                for candidate in ready_candidates:
                    if int(candidate["id"]) != selection.selected_candidate_id:
                        db.set_merge_candidate_status(int(candidate["id"]), "not_selected")
```

The final merge loop already only merges candidates with status `merge_ready`, so non-selected candidates will not be merged.

- [ ] **Step 8: Run high-risk and existing e2e tests**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_runner_production_e2e.py::test_codex_fake_implementer_reaches_validated_candidate evals/test_runner_production_e2e.py::test_high_risk_task_ranks_two_candidates -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py skills/agent-runway/evals/fixtures/fake-bin/codex skills/agent-runway/evals/test_runner_production_e2e.py
git commit -m "feat: rank high-risk AgentRunway candidates"
```

Expected: commit succeeds.

## Task 8: Extend Resume Planning for Conflict Redispatch

```yaml agentrunway-task
task_id: task_008
title: Extend Resume Planning for Conflict Redispatch
risk: medium
phase: implementation
dependencies: [task_001, task_003, task_005]
spec_refs: [S1.7.3, S1.8, S1.10.1, S1.14.2]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/reconciliation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_reconciliation.py, mode: owned}
acceptance_commands: [python3 -m pytest evals/test_reconciliation.py -v]
required_skills: [using-superpowers, test-driven-development]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/reconciliation.py`
- Modify: `skills/agent-runway/evals/test_reconciliation.py`

- [ ] **Step 1: Write failing conflict redispatch tests**

Append to `skills/agent-runway/evals/test_reconciliation.py`:

```python
def test_plan_reconciliation_plans_first_conflict_redispatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merge_conflict",
    )

    plan = plan_reconciliation(run_id="run_001", run_dir=run_dir, db=db)

    assert {
        "target": "task_001",
        "action": "conflict_redispatch",
        "reason": "merge_conflict",
        "writes": True,
    } in plan["actions"]


def test_plan_reconciliation_repeated_conflict_requires_manual_action(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merge_conflict",
    )
    db.insert_event(
        event_type="agentrunway.conflict_redispatch_planned",
        payload={
            "schema": "agentrunway.event.v1",
            "run_id": "run_001",
            "agentrunway_run_id": "run_001",
            "phase": "resume",
            "outcome": "partial",
            "summary": "conflict redispatch planned",
            "task_id": "task_001",
            "reason": "merge_conflict",
        },
        status="agentlens_disabled",
    )

    plan = plan_reconciliation(run_id="run_001", run_dir=run_dir, db=db)

    assert {
        "target": "task_001",
        "action": "manual_action",
        "reason": "repeated_merge_conflict",
        "writes": False,
    } in plan["actions"]
```

- [ ] **Step 2: Run conflict tests and verify they fail**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_reconciliation.py::test_plan_reconciliation_plans_first_conflict_redispatch evals/test_reconciliation.py::test_plan_reconciliation_repeated_conflict_requires_manual_action -v
```

Expected: FAIL because merge conflict actions are not planned.

- [ ] **Step 3: Add conflict history helpers**

Modify `skills/agent-runway/scripts/agentrunway/reconciliation.py`:

```python
from .quality_policy import conflict_decision
```

Add helper functions:

```python
def _conflict_redispatch_count(db: AgentRunwayDb, task_id: str) -> int:
    count = 0
    for event in db.list_events():
        if event["event_type"] != "agentrunway.conflict_redispatch_planned":
            continue
        payload = event.get("payload", {})
        if payload.get("task_id") == task_id:
            count += 1
    return count


def _action_exists(actions: list[dict[str, Any]], target: str, action: str) -> bool:
    return any(item.get("target") == target and item.get("action") == action for item in actions)
```

- [ ] **Step 4: Plan conflict redispatch/manual-action actions**

Inside `plan_reconciliation()`, after the interrupted cherry-pick check and before worker iteration, add:

```python
    for candidate in db.list_merge_candidates():
        if candidate["status"] != "merge_conflict":
            continue
        task_id = str(candidate["task_id"])
        decision = conflict_decision(
            task_id=task_id,
            previous_conflicts=_conflict_redispatch_count(db, task_id),
        )
        action = "conflict_redispatch" if decision.action == "redispatch" else "manual_action"
        if not _action_exists(actions, task_id, action):
            actions.append(
                {
                    "target": task_id,
                    "action": action,
                    "reason": decision.reason,
                    "writes": action == "conflict_redispatch",
                }
            )
```

- [ ] **Step 5: Apply conflict redispatch idempotently**

Modify `apply_reconciliation_plan()` to handle the new actions:

```python
        elif action["action"] == "conflict_redispatch":
            if not _resume_action_exists(db, target, "conflict_redispatch"):
                _record_resume_action(
                    db,
                    str(plan["run_id"]),
                    target,
                    "conflict_redispatch",
                    "partial",
                    "conflict redispatch required",
                )
        elif action["action"] == "manual_action":
            _record_resume_action(
                db,
                str(plan["run_id"]),
                target,
                "manual_action",
                "failed",
                "manual action required",
            )
```

- [ ] **Step 6: Run reconciliation tests**

Run:

```bash
cd skills/agent-runway
python3 -m pytest evals/test_reconciliation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/reconciliation.py skills/agent-runway/evals/test_reconciliation.py
git commit -m "feat: plan AgentRunway conflict redispatch"
```

Expected: commit succeeds.

## Task 9: Documentation and Final Verification

```yaml agentrunway-task
task_id: task_009
title: Documentation and Final Verification
risk: low
phase: documentation
dependencies: [task_001, task_002, task_003, task_004, task_005, task_006, task_007, task_008]
spec_refs: [S1.9, S1.10, S1.12, S1.14.3]
file_claims:
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/agentlens-events.md, mode: shared_append}
acceptance_commands: [./evals/run.sh]
required_skills: [using-superpowers, verification-before-completion]
serial: true
```

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/agentlens-events.md`

- [ ] **Step 1: Update README**

Add this section to `skills/agent-runway/README.md` after the AgentLens operations paragraph:

```markdown
## Operations Quality Engine

AgentRunway computes a shared diagnosis for `status`, `inspect`, and `resume`.
The diagnosis reports the run state, reason, safe actions, manual actions, and
next operator action. High-risk tasks can produce two implementer candidates;
AgentRunway ranks validated candidates deterministically and emits
`agentrunway.candidate_ranked` evidence explaining the selection.

Gate retries are policy-owned. Reviewer `changes_requested` and verifier
`failed` can retry once when the failure is actionable. Verifier `blocked`,
repeated merge conflicts, file-claim violations, and unsafe recovery states stop
with a manual action instead of guessing.
```

- [ ] **Step 2: Run AgentRunway eval suite**

Run:

```bash
cd skills/agent-runway
./evals/run.sh
```

Expected: all evals pass.

- [ ] **Step 3: Run Python compile checks**

Run:

```bash
python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
```

Expected: command exits 0.

- [ ] **Step 4: Run shell syntax and skill contract checks**

Run:

```bash
bash -n evals/run.sh
python3 evals/check_skill_contract.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Run AgentLens focused tests**

Run:

```bash
cd ../../AgentLens
python -m pytest tests/unit/test_agentrunway_events.py -v
```

Expected: PASS.

- [ ] **Step 6: Run repository checks**

Run:

```bash
cd ..
git diff --check
graphify update .
```

Expected: `git diff --check` exits 0 and `graphify update .` completes.

- [ ] **Step 7: Commit docs and final adjustments**

Run:

```bash
git add skills/agent-runway/README.md skills/agent-runway/references/agentlens-events.md
git commit -m "docs: document AgentRunway operations quality engine"
```

Expected: commit succeeds.

## Self-Review

Spec coverage:

- Shared run diagnosis: Tasks 3-4.
- Quality policy: Tasks 1 and 6.
- High-risk multi-candidate execution: Task 7.
- Deterministic candidate ranking: Tasks 2 and 7.
- Conflict redispatch/manual-action split: Task 8.
- Decision evidence: Task 5 and Task 7.
- AgentLens projection: Task 5.
- Documentation and verification: Task 9.

Placeholder scan:

- This plan avoids `TBD`, `TODO`, and unspecified "add tests" instructions.
- Each implementation task includes concrete file paths, code snippets,
  commands, expected results, and commit commands.

Type consistency:

- `PolicyDecision`, `CandidateScore`, `CandidateSelection`, and `RunDiagnosis`
  expose explicit attributes used by later tasks.
- `to_dict()` is included where later tasks serialize objects into status or
  event payloads.
