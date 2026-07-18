# CPE 2.0 Wave 2: Progress-Aware Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blind retry behavior with typed capability blockers, progress-aware checkpoints, bounded continuation, and a mechanical envelope-repair path that never spends another model turn on a safe wire-format fix.

**Architecture:** Wave 2 consumes the format-2 state, compiled index, execution ledger, and evidence recorder created by Waves 0–1. A pure capability module canonicalizes environment observations and computes a stable fingerprint. A pure progress module decides whether a timed-out plan made durable progress and may continue within explicit budgets. The runner uses both decisions before launching any child. Envelope repair is a separate deterministic path restricted to artifact-path normalization; semantic result changes remain prohibited.

**Tech Stack:** Python 3 standard library, `unittest`, JSON/JSONL, SHA-256, POSIX process/worktree behavior already used by CPE.

## Global Constraints

- Implement only after Wave 0 and Wave 1 are complete and their full eval suites pass.
- Do not modify Superpowers skills, templates, hooks, or upstream package files.
- Do not add a scheduler, parallel plan execution, child-agent orchestration, or a semantic reviewer to CPE.
- Keep the public `run --spec --plan --workspace` and `resume --run-id RUN_ID` workflow intact.
- Treat `parent_observed`, `child_attested`, `derived`, and `hypothesis` as distinct trust levels. A hypothesis cannot become a blocker without a parent observation.
- An unchanged typed blocker must stop `resume` before compiler, Codex, or verification child launch.
- A productive timeout may continue only when the progress fingerprint changes and all plan budgets still allow it.
- A second consecutive no-progress slice stops the plan; do not retry merely because launches remain.
- Envelope repair may change only a mechanically provable result-envelope path field. Preserve the original receipt and record both digests.
- Keep runtime artifacts under `~/.codex/orchestrator/<run-id>/`; do not write them into the product repository.
- Use test-driven development for every behavior change and commit after each task.

---

### Task 1: Add typed capability observations and stable environment fingerprints

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/capabilities.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class CapabilityObservation:
    capability: str
    scope: str
    outcome: Literal["available", "unavailable", "unknown"]
    reason_code: str
    observed_by: Literal["parent_observed", "child_attested", "derived", "hypothesis"]
    stable_details: Mapping[str, str]

def canonicalize_observation(observation: CapabilityObservation) -> dict[str, object]: ...
def environment_fingerprint(observations: Sequence[CapabilityObservation]) -> str: ...
def typed_blockers(observations: Sequence[CapabilityObservation]) -> list[dict[str, object]]: ...
def blocker_resume_decision(
    *, previous_fingerprint: str | None, current_fingerprint: str
) -> Literal["launch", "stop_unchanged"]: ...
```

`stable_details` must contain only decision-relevant capability metadata from a per-capability allowlist. Exclude timestamps, PIDs, temporary paths, randomized ports, raw environment values, credentials, and prose error messages from the fingerprint. Persist versions and booleans, never tokens, cookies, passwords, provider keys, or the full environment.

- [ ] **Step 1: Write failing canonicalization and fingerprint tests**

Add these cases to `evals/check_runner.py`:

```python
class CapabilityTests(unittest.TestCase):
    def test_fingerprint_ignores_incidental_probe_details(self):
        first = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1", "probe_port": "43117"},
        )
        second = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1", "probe_port": "58241"},
        )
        self.assertEqual(
            environment_fingerprint([first]),
            environment_fingerprint([second]),
        )

    def test_child_hypothesis_does_not_become_typed_blocker(self):
        observation = CapabilityObservation(
            capability="product_runtime",
            scope="plan",
            outcome="unavailable",
            reason_code="suspected_environment",
            observed_by="hypothesis",
            stable_details={},
        )
        self.assertEqual([], typed_blockers([observation]))

    def test_parent_observed_unavailable_capability_is_a_blocker(self):
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1"},
        )
        self.assertEqual("loopback_bind", typed_blockers([observation])[0]["capability"])

    def test_trust_upgrade_does_not_change_environment_fingerprint(self):
        child = CapabilityObservation(
            "loopback_bind", "workspace", "unavailable", "permission_denied",
            "child_attested", {"host": "127.0.0.1"},
        )
        parent = dataclasses.replace(child, observed_by="parent_observed")
        self.assertEqual(
            environment_fingerprint([child]), environment_fingerprint([parent])
        )
        self.assertEqual([], typed_blockers([child]))
        self.assertEqual(1, len(typed_blockers([parent])))
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.CapabilityTests -v
```

Expected: import failures for `cpe_runtime.capabilities` or missing interfaces.

- [ ] **Step 3: Implement pure capability normalization**

Create `scripts/cpe_runtime/capabilities.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal, Mapping, Sequence

TrustLevel = Literal["parent_observed", "child_attested", "derived", "hypothesis"]
Outcome = Literal["available", "unavailable", "unknown"]

_INCIDENTAL_DETAIL_KEYS = {
    "timestamp", "pid", "probe_port", "temporary_path", "raw_error", "duration_ms"
}
_ALLOWED_DETAIL_KEYS = {
    "loopback_bind": {"host", "host_family", "sandbox_policy"},
    "workspace_write": {"filesystem_type", "sandbox_policy"},
    "git": {"version", "worktree_supported"},
}


@dataclass(frozen=True)
class CapabilityObservation:
    capability: str
    scope: str
    outcome: Outcome
    reason_code: str
    observed_by: TrustLevel
    stable_details: Mapping[str, str]


def canonicalize_observation(observation: CapabilityObservation) -> dict[str, object]:
    validate_observation(observation)
    details = {
        key: value
        for key, value in sorted(observation.stable_details.items())
        if key not in _INCIDENTAL_DETAIL_KEYS
        and key in _ALLOWED_DETAIL_KEYS.get(observation.capability, set())
    }
    return {
        "capability": observation.capability,
        "scope": observation.scope,
        "outcome": observation.outcome,
        "reason_code": observation.reason_code,
        "observed_by": observation.observed_by,
        "stable_details": details,
    }


def environment_fingerprint(observations: Sequence[CapabilityObservation]) -> str:
    payload = []
    for item in observations:
        canonical = canonicalize_observation(item)
        canonical.pop("observed_by")
        payload.append(canonical)
    payload.sort(
        key=lambda item: (
            str(item["capability"]), str(item["scope"]), str(item["reason_code"])
        ),
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def typed_blockers(observations: Sequence[CapabilityObservation]) -> list[dict[str, object]]:
    for item in observations:
        validate_observation(item)
    return [
        canonicalize_observation(item)
        for item in observations
        if item.outcome == "unavailable" and item.observed_by == "parent_observed"
    ]


def blocker_resume_decision(
    *, previous_fingerprint: str | None, current_fingerprint: str
) -> Literal["launch", "stop_unchanged"]:
    if previous_fingerprint is not None and previous_fingerprint == current_fingerprint:
        return "stop_unchanged"
    return "launch"
```

- [ ] **Step 4: Add validation tests for malformed observations**

Require non-empty `capability`, `scope`, and `reason_code`; reject unsupported enum values, non-string detail keys/values, secret-like keys, and keys outside the union of the capability allowlist plus `_INCIDENTAL_DETAIL_KEYS` in a `validate_observation()` function. Known incidental fields are accepted then excluded from the fingerprint; unknown fields fail closed. Add one passing and five failing cases. Do not silently coerce malformed child data.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.CapabilityTests -v
```

Expected: all capability tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/capabilities.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): type capability blockers"
```

---

### Task 2: Implement durable progress fingerprints and bounded checkpoint decisions

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/progress.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ProgressSnapshot:
    head: str
    completed_task_ids: tuple[str, ...]
    current_task_id: str | None
    accepted_review_ids: tuple[str, ...]
    closed_finding_ids: tuple[str, ...]

@dataclass(frozen=True)
class CheckpointBudget:
    max_progress_checkpoints: int
    max_controller_launches: int
    plan_wall_seconds: int

@dataclass(frozen=True)
class CheckpointDecision:
    action: Literal["continue", "stop_stalled", "stop_budget", "finish"]
    reason_code: str
    progress_fingerprint: str

def progress_fingerprint(snapshot: ProgressSnapshot) -> str: ...
def decide_checkpoint(
    *, previous: ProgressSnapshot | None, current: ProgressSnapshot,
    timed_out: bool, consecutive_no_progress: int,
    progress_checkpoints: int, controller_launches: int,
    plan_elapsed_seconds: int, budget: CheckpointBudget,
) -> CheckpointDecision: ...
```

- [ ] **Step 1: Write failing decision-table tests**

Cover every row explicitly:

| Input | Expected action |
|---|---|
| child completed | `finish` |
| timed out, fingerprint changed, budgets remain | `continue` |
| timed out, fingerprint unchanged, first no-progress slice | `continue` |
| timed out, fingerprint unchanged, second consecutive no-progress slice | `stop_stalled` |
| changed fingerprint but checkpoint count is 6 | `stop_budget` |
| changed fingerprint but controller launch count is 8 | `stop_budget` |
| changed fingerprint but plan wall time is 21600 seconds | `stop_budget` |

Use the Wave 0 defaults in every test:

```python
DEFAULT_BUDGET = CheckpointBudget(
    max_progress_checkpoints=6,
    max_controller_launches=8,
    plan_wall_seconds=21_600,
)
```

Also prove ordering is canonical:

```python
def test_progress_fingerprint_ignores_set_like_ordering(self):
    left = ProgressSnapshot("abc", ("T2", "T1"), "T3", ("R2", "R1"), ("F1",))
    right = ProgressSnapshot("abc", ("T1", "T2"), "T3", ("R1", "R2"), ("F1",))
    self.assertEqual(progress_fingerprint(left), progress_fingerprint(right))
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.ProgressDecisionTests -v
```

Expected: missing `cpe_runtime.progress` module.

- [ ] **Step 3: Implement canonical progress hashing and the decision table**

Create `scripts/cpe_runtime/progress.py`. The decision must test completion first, then hard budgets, then progress/stall behavior. Use sorted unique identifiers in the fingerprint and reject an empty `head` rather than hashing an ambiguous state.

```python
def decide_checkpoint(
    *,
    previous: ProgressSnapshot | None,
    current: ProgressSnapshot,
    timed_out: bool,
    consecutive_no_progress: int,
    progress_checkpoints: int,
    controller_launches: int,
    plan_elapsed_seconds: int,
    budget: CheckpointBudget,
    child_completed: bool = False,
) -> CheckpointDecision:
    fingerprint = progress_fingerprint(current)
    if child_completed:
        return CheckpointDecision("finish", "child_completed", fingerprint)

    if progress_checkpoints >= budget.max_progress_checkpoints:
        return CheckpointDecision("stop_budget", "checkpoint_budget_exhausted", fingerprint)
    if controller_launches >= budget.max_controller_launches:
        return CheckpointDecision("stop_budget", "launch_budget_exhausted", fingerprint)
    if plan_elapsed_seconds >= budget.plan_wall_seconds:
        return CheckpointDecision("stop_budget", "wall_budget_exhausted", fingerprint)

    changed = previous is None or progress_fingerprint(previous) != fingerprint
    if timed_out and changed:
        return CheckpointDecision("continue", "productive_timeout", fingerprint)
    if timed_out and consecutive_no_progress >= 1:
        return CheckpointDecision("stop_stalled", "second_no_progress_slice", fingerprint)
    if timed_out:
        return CheckpointDecision("continue", "first_no_progress_slice", fingerprint)
    return CheckpointDecision("stop_stalled", "child_stopped_without_completion", fingerprint)
```

- [ ] **Step 4: Make the execution ledger expose a `ProgressSnapshot`**

Add to `evidence.py`:

```python
def read_progress_snapshot(run_root: Path, *, plan_index: int, head: str) -> ProgressSnapshot:
    plan_id = load_state(run_root)["plans"][plan_index]["plan_id"]
    events = validate_execution_ledger(
        current_execution_ledger_path(run_root),
        expected_plan_id=plan_id,
    )
    completed = {
        event["task_id"] for event in events
        if event["category"] == "task"
        and event["action"] == "completed"
        and event["result"] == "pass"
    }
    started = [
        event["task_id"] for event in events
        if event["category"] == "task" and event["action"] == "started"
    ]
    current = next((task_id for task_id in reversed(started) if task_id not in completed), None)
    return ProgressSnapshot(
        head=head,
        completed_task_ids=tuple(sorted(completed)),
        current_task_id=current,
        accepted_review_ids=tuple(sorted({
            event["review_id"] for event in events
            if event["category"] == "review" and event["result"] == "accepted"
        })),
        closed_finding_ids=tuple(sorted({
            finding_id for event in events
            if event["category"] == "finding_fix" and event["result"] == "closed"
            for finding_id in event["finding_ids"]
        })),
    )
```

The loader must use the Wave 1 JSONL validator, preserve category-specific required fields, and fail closed on malformed or duplicate ledger data. It must not introduce a second object-shaped ledger format.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.ProgressDecisionTests -v
```

Expected: all progress tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/progress.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): decide recovery from durable progress"
```

---

### Task 3: Stop unchanged blockers before child launch and continue productive timeouts

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
def _observe_capabilities(workspace: Path, compiled_index: Mapping[str, object]) -> list[CapabilityObservation]: ...
def _current_head(worktree: Path) -> str: ...
def _resume_preflight(state: Mapping[str, object], observations: Sequence[CapabilityObservation]) -> str: ...
def _record_checkpoint(state: dict[str, object], decision: CheckpointDecision) -> None: ...
def _launch_plan_slice(
    *, runner: SequentialRunner, plan_state: Mapping[str, object], request: StructuredLaunchRequest
) -> LaunchResult: ...
```

`_observe_capabilities` must run only the probes declared by the compiled index or required by CPE itself: repository readability, worktree writability, git command availability, and explicitly required loopback binding. Do not guess product health from a generic test failure.

- [ ] **Step 1: Add failing zero-launch unchanged-blocker test**

Create a fake run whose result contains a parent-confirmed blocker and whose state records the matching environment fingerprint. On `resume`, inject an observation provider returning the same fingerprint and assert:

```python
self.assertEqual("blocked", resumed["status"])
self.assertEqual(0, fake_codex_launch_count(run_root))
self.assertEqual(0, compiler_launch_count(run_root))
self.assertEqual("unchanged_environment_blocker", resumed["last_decision_reason"])
```

Then return an `available` observation and prove exactly one child launch is allowed.

- [ ] **Step 2: Add failing productive-timeout and stalled-timeout integration tests**

Extend `fake_codex.py` with deterministic scenarios:

- `timeout_with_progress`: updates the execution ledger and worktree commit, writes a checkpoint result, then exits with the launcher timeout code.
- `timeout_without_progress`: writes the same checkpoint result and leaves HEAD/ledger unchanged.

Assert:

```python
self.assertEqual("completed", productive["status"])
self.assertEqual(2, fake_codex_launch_count(run_root))

self.assertEqual("blocked", stalled["status"])
self.assertEqual("second_no_progress_slice", stalled["last_decision_reason"])
self.assertEqual(2, fake_codex_launch_count(run_root))
```

Assert each `StructuredLaunchRequest.timeout_seconds` equals the plan's saved `budget.controller_slice_timeout_seconds` (3600 by default); no independent launcher constant may silently override the durable budget.

Load `evals/fixtures/canvas-direct-run-format2.json` in a regression test and prove its five 3600-second timeouts are split into productive-timeout evidence when HEAD advances and unchanged-blocker evidence when the canonical capability fingerprint repeats. Load the two comparative fixtures only to assert they do not affect CPE launch/timeout totals.

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.ResumeCapabilityTests \
  evals.check_runner.ProgressRecoveryIntegrationTests -v
```

Expected: resume still launches on unchanged blockers or productive timeouts are still classified as generic interruption/failure.

- [ ] **Step 4: Integrate the resume preflight before compiler and launcher calls**

At the beginning of `SequentialRunner.resume()`:

1. Load and validate format-2 state.
2. Re-run only the saved typed capability probes.
3. Compute the current fingerprint.
4. If the prior blocker fingerprint is identical, append `resume.stopped_unchanged_blocker`, update the efficiency counters, save state, and return without invoking the compiler or Codex.
5. If the fingerprint changed, append `resume.environment_changed` and proceed.

Do not reuse a child-attested blocker as parent-observed evidence without a local probe.

Expose compiled `split_or_checkpoint_required` or `handoff_to_waygent` only as an advisory in inspect/report events. Neither advisory raises a budget, launches Waygent, nor blocks a user-approved CPE run by itself.

- [ ] **Step 5: Integrate checkpoint decisions after every child slice**

Replace the timeout branch in `_execute()` with this order:

```python
head = _current_head(worktree)
current = read_progress_snapshot(run_root, plan_index=plan_index, head=head)
decision = decide_checkpoint(
    previous=previous_snapshot,
    current=current,
    timed_out=launch.timed_out,
    consecutive_no_progress=plan_state["consecutive_no_progress_slices"],
    progress_checkpoints=plan_state["progress_checkpoint_count"],
    controller_launches=plan_state["controller_launch_count"],
    plan_elapsed_seconds=plan_state["plan_elapsed_seconds"],
    budget=budget_from_state(state),
    child_completed=result["status"] == "completed",
)
_record_checkpoint(state, decision)
```

Before each slice, clone the controller request with `timeout_seconds=plan_state["budget"]["controller_slice_timeout_seconds"]`. Increment `controller_launch_count` and persist state immediately before process spawn so coordinator loss cannot grant an uncounted extra attempt.

For `continue`, persist state and evidence before launching the next slice. For `stop_stalled` or `stop_budget`, write a typed blocker/result and return. Never perform an unrecorded retry.

`_record_checkpoint` always increments `checkpoint_count`. It increments `progress_checkpoint_count` and resets `consecutive_no_progress_slices` to zero only when the fingerprint changed; otherwise it increments `consecutive_no_progress_slices`. `plan_elapsed_seconds` accumulates monotonic active controller/helper/parent-acceptance duration for that plan; the one-time compiler is a run-level metric, and an operator pause while blocked/checkpointed is reported separately. Persist the new fingerprint, counters, elapsed seconds, and last-known HEAD atomically before any continuation launch.

- [ ] **Step 6: Record optimization metrics for each decision**

Update `reporting.py` counters:

```json
{
  "launches_avoided": 1,
  "productive_timeouts": 1,
  "no_progress_slices": 0,
  "budget_stops": 0,
  "continuation_reason_counts": {
    "productive_timeout": 1
  }
}
```

Counters are derived from JSONL events; do not mutate totals independently in multiple files.

- [ ] **Step 7: Run the focused tests and confirm GREEN**

Run the same focused unittest command from Step 3. Expected: all tests pass, with explicit launch-count assertions.

- [ ] **Step 8: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): bound progress-aware recovery"
```

---

### Task 4: Add zero-model mechanical envelope repair

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class EnvelopeRepair:
    original_path: Path
    repaired_path: Path
    original_digest: str
    repaired_digest: str
    changed_fields: tuple[str, ...]

def repair_result_envelope(
    *, run_root: Path, worktree: Path, original_result_path: Path
) -> EnvelopeRepair | None: ...
```

The only allowed repair in 2.0 is normalizing an absolute `workflow_receipt.ledger_path` or `workflow_receipt.final_review_path` that resolves to a regular file inside the exact owned worktree into a safe worktree-relative POSIX path. All other differences are semantic and must return `None`.

- [ ] **Step 1: Write failing safe and unsafe repair tests**

Required cases:

1. An absolute in-worktree `workflow_receipt.final_review_path` where the regular file exists: repair succeeds to a relative POSIX path.
2. An absolute in-worktree spelling containing `..`: repair succeeds to the canonical relative path.
3. Symlink whose target escapes the worktree: repair returns `None`.
4. Missing artifact: repair returns `None`.
5. Unknown result key: repair returns `None`.
6. Status or summary change would be needed: repair returns `None`.
7. Successful repair preserves the original file byte-for-byte and creates a new file under `results/repaired/`.
8. Dirty worktree, result HEAD mismatch, changed verification evidence digest, changed review/finding state, or an original error other than `unsafe_workflow_artifact`: repair returns `None`.

Also assert `fake_codex_launch_count(run_root) == 0` for repair-only resume.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.EnvelopeRepairTests -v
```

Expected: missing repair interface.

- [ ] **Step 3: Implement fail-closed repair**

Use strict schema validation before and after normalization:

```python
def repair_result_envelope(
    *,
    run_root: Path,
    worktree: Path,
    original_result_path: Path,
) -> EnvelopeRepair | None:
    original_bytes = original_result_path.read_bytes()
    payload = json.loads(original_bytes)
    if set(payload) - RESULT_FORMAT_2_FIELDS:
        return None
    if git_head(worktree) != payload.get("head_commit") or not git_is_clean(worktree):
        return None
    repaired = dict(payload)
    repaired["workflow_receipt"] = dict(payload["workflow_receipt"])
    changed_fields: list[str] = []
    for field in ("ledger_path", "final_review_path"):
        raw = repaired["workflow_receipt"].get(field)
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            continue
        resolved = resolve_without_symlink_components(Path(raw), worktree)
        if resolved is None or not resolved.is_file():
            return None
        repaired["workflow_receipt"][field] = resolved.relative_to(
            worktree.resolve(strict=True)
        ).as_posix()
        changed_fields.append(f"/workflow_receipt/{field}")
    if not changed_fields:
        return None
    validate_result_v2(repaired)
    if semantic_projection(repaired) != semantic_projection(payload):
        return None
    repaired_bytes = json.dumps(
        repaired, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    original_digest = hashlib.sha256(original_bytes).hexdigest()
    repaired_digest = hashlib.sha256(repaired_bytes).hexdigest()
    repaired_root = run_root / "results" / "repaired"
    repaired_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    repaired_path = repaired_root / f"{original_result_path.stem}-{repaired_digest}.json"
    atomic_private_write(repaired_path, repaired_bytes, mode=0o400)
    return EnvelopeRepair(
        original_path=original_result_path,
        repaired_path=repaired_path,
        original_digest=original_digest,
        repaired_digest=repaired_digest,
        changed_fields=tuple(changed_fields),
    )
```

`resolve_without_symlink_components` must first prove the lexical absolute path is under the owned worktree, then walk every component with `lstat`/`O_NOFOLLOW` before resolution. `resolved.is_symlink()` alone is insufficient after resolution. `semantic_projection` excludes only the two allowlisted path spellings; it includes status, HEAD, verification keys/results/digests, review/finding state, ancestry/remote-policy references, and every other result field.

- [ ] **Step 4: Integrate repair before any recovery launch**

When result validation fails only with `unsafe_workflow_artifact`, and the current verification/review evidence manifests still match the result references, call `repair_result_envelope()`. On success:

- append `result.envelope_repaired` with both digests and `changed_fields`;
- point state to the repaired receipt while retaining `original_result_path`;
- increment `envelope_repairs` and `launches_avoided` in the derived report;
- continue normal receipt acceptance without compiler or Codex launch.

All other validation errors follow the existing typed failure path.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run the unittest command from Step 2. Expected: all repair and zero-launch tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): repair safe result envelopes locally"
```

---

### Task 5: Document Wave 2 recovery policy and run the complete gate

**Files:**

- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**

- Consumes: all Wave 2 focused gates and the Wave 1 report/event derivation pipeline.
- Produces: documented recovery contract and one complete deterministic Wave 2 integration gate.

- [ ] **Step 1: Update the operator contract**

Document these exact behaviors:

- unchanged parent-observed blockers produce zero new child launches;
- changed capability fingerprints permit a bounded resume;
- productive timeouts continue only with changed progress fingerprints;
- the second consecutive no-progress slice stops;
- defaults are 3600 seconds per slice, 6 progress checkpoints, 21600 seconds per plan, and 8 controller launches;
- envelope repair is path-only, preserves the original receipt, and uses zero model turns;
- `checkpointed` is a durable state, not a failure synonym.

Keep ownership explicit: Superpowers decides what implementation/review work is correct; CPE decides whether another execution slice is justified.

- [ ] **Step 2: Ensure the eval runner discovers every new test**

Do not add a second test harness. Keep `evals/run.sh` as the single entry point and ensure it invokes the existing runner and CLI suites that now include Wave 2 cases.

- [ ] **Step 3: Run focused recovery tests**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.CapabilityTests \
  evals.check_runner.ProgressDecisionTests \
  evals.check_runner.ResumeCapabilityTests \
  evals.check_runner.ProgressRecoveryIntegrationTests \
  evals.check_runner.EnvelopeRepairTests -v
```

Expected: all Wave 2 cases pass.

- [ ] **Step 4: Run the complete CPE gate once**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

Expected: every runner and CLI test passes. Do not run the full suite after every individual repair; this is the single Wave 2 integration gate.

- [ ] **Step 5: Run patch hygiene and inspect scope**

```bash
git diff --check
git status --short --branch --untracked-files=all
git diff --stat HEAD~4..HEAD
```

Expected: no whitespace errors, no runtime artifacts, and changes limited to the CPE skill plus this approved plan series.

- [ ] **Step 6: Commit Task 5**

```bash
git add skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "docs(cpe): define progress-aware recovery"
```

---

## Wave 2 Done When

- A repeated, unchanged environment blocker causes zero compiler, model, and verification launches.
- A changed environment fingerprint permits bounded recovery.
- A timed-out slice with durable progress can continue automatically.
- Two consecutive no-progress slices stop with a typed reason.
- Checkpoint, launch, and wall-time budgets are enforced before another launch.
- Safe artifact-path envelope errors are repaired locally with immutable before/after evidence.
- No semantic result field can be changed by envelope repair.
- Optimization metrics explain every avoided launch, continuation, and budget stop.
- The complete CPE eval suite and `git diff --check` pass.
