# CPE 2.0 Wave 4: Operations, Analysis, and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn CPE's format-2 evidence into practical operator commands, conservative cross-run optimization signals, truthful branch handoff, and a verified 2.0.0 release without adding legacy compatibility or taking ownership from Superpowers.

**Architecture:** Read-only query services scan format-2 run roots and derive health, status, efficiency, reports, and recurring-signal analysis from immutable state/events/evidence. Public CLI commands render JSON by default with an optional concise human view. Cross-run analysis produces a local backlog candidate only after repeated independent evidence crosses a strict threshold. Finish output describes a branch handoff; integration completion requires a separate parent-observed receipt. A live canary runs the unchanged CPE input workflow against a disposable repository before version and documentation are finalized.

**Tech Stack:** Python 3 standard library, `unittest`, argparse, JSON/JSONL, Git CLI, existing CPE eval harness.

## Global Constraints

- Implement only after Waves 0–3 pass their complete eval gates.
- Do not support format 1 or migrate legacy run directories. CPE 2.0 reads format 2 only and reports older roots as unsupported.
- Do not modify Superpowers skills, templates, hooks, or upstream packages.
- Do not add Waygent dependencies, a scheduler, parallel plans, or semantic quality review to CPE.
- Keep `run --spec --plan --workspace` as the primary input workflow; the compiled index remains internal.
- All operational commands are read-only except `run`, `resume`, the internal `verify` helper, and explicit report materialization inside the run root.
- Never include prompts, transcripts, source file bodies, secrets, or arbitrary child stdout in summaries/backlogs.
- Follow the approved [token evidence and observability addendum](../specs/2026-07-17-cpe-2.0-token-evidence-observability-addendum.md). Report cached, uncached, output, reasoning, completeness, aggregate scope, and artifact/context pressure without fabricating per-role attribution.
- Cross-run promotion requires either two independent runs with the same normalized signal, or the category-specific same-run threshold. Duration-based categories retain the existing three occurrences and cumulative 30-minute threshold; artifact/context categories use the approved byte/count thresholds from the addendum.
- A completed CPE run means plan execution finished on an isolated branch. It does not mean merge, push, deployment, or product acceptance completed.
- Release version `2.0.0` only after the live canary and complete suite pass.
- Use test-driven development and commit after each task.

---

### Task 1: Add read-only run discovery and operator health checks

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/operations.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RunListing:
    run_id: str
    status: str
    workspace: str
    branch: str
    created_at: str
    updated_at: str
    current_plan_index: int
    plan_count: int

@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    status: Literal["pass", "warn", "fail"]
    reason_code: str
    details: Mapping[str, object]

def discover_runs(orchestrator_root: Path) -> list[RunListing]: ...
def doctor_checks(
    *, orchestrator_root: Path, workspace: Path | None
) -> list[DoctorCheck]: ...
```

**CLI contracts:**

```text
cpe.py doctor [--workspace PATH] [--human]
cpe.py list [--status STATUS] [--workspace PATH] [--limit N] [--human]
```

- [ ] **Step 1: Write failing run-discovery tests**

Prove that `discover_runs()`:

- returns only directories with valid format-2 `state.json`;
- ignores unrelated files and incomplete temporary files;
- reports format-1 roots separately as unsupported rather than trying to load them;
- sorts by `updated_at` descending with `run_id` as a stable tiebreaker;
- never follows a symlink outside the orchestrator root;
- tolerates one corrupt run and returns a structured warning for it instead of failing the whole listing.

- [ ] **Step 2: Write failing doctor tests**

Doctor must check:

- Python version satisfies the skill's declared minimum;
- runtime is POSIX and exposes `fcntl`, process groups, signals, and `start_new_session`; Windows is reported as unsupported rather than guessed compatible;
- `git` and `codex` executables resolve;
- orchestrator root exists or its parent is writable;
- selected workspace is a Git worktree when supplied;
- workspace permits an isolated worktree under the supported placement policy;
- a dirty selected primary workspace returns `workspace_dirty`; a selected linked/dedicated worktree that would require adopting existing work returns `unsupported_existing_worktree` before any model call. CPE 2.0 does not adopt either automatically;
- current CPE result schema and format version are internally consistent;
- existing format-2 roots pass path/digest validation;
- legacy format roots produce `warn: unsupported_format`, never an automatic conversion.

Doctor must not launch Codex, run product tests, create a worktree, or modify run state.

- [ ] **Step 3: Write failing CLI output tests**

JSON is the default and must have stable top-level schemas:

```json
{
  "schema_version": 1,
  "command": "doctor",
  "status": "pass",
  "checks": []
}
```

```json
{
  "schema_version": 1,
  "command": "list",
  "runs": [],
  "warnings": []
}
```

`--human` may change rendering only; it must use the same query result.

- [ ] **Step 4: Run the focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_cli.DoctorCliTests \
  evals.check_cli.ListCliTests -v
```

Expected: commands are not recognized.

- [ ] **Step 5: Implement bounded discovery and doctor checks**

Scan only direct children of `~/.codex/orchestrator`; cap discovery at 10,000 directories and expose truncation as a warning. Reuse the format-2 state validator and path-boundary helpers. `--limit` must be between 1 and 1000.

Use exit codes:

- `0` when doctor has no failures, including warnings;
- existing usage code for invalid arguments;
- `1` when at least one doctor check is `fail`.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the command from Step 4. Expected: all doctor/list tests pass and fixtures prove no child processes or state writes occur.

- [ ] **Step 7: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/operations.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/evals/check_cli.py
git commit -m "feat(cpe): add run discovery and doctor"
```

---

### Task 2: Add efficiency inspection and report materialization

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/operations.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/templates/optimization-report.schema.json`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/canvas-format1-token-forensic.json`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
def build_efficiency_summary(run_root: Path) -> dict[str, object]: ...
def build_run_report(run_root: Path) -> dict[str, object]: ...
def materialize_run_report(run_root: Path) -> tuple[Path, str]: ...
```

**CLI contracts:**

```text
cpe.py inspect --run-id RUN_ID [--efficiency] [--human]
cpe.py report --run-id RUN_ID [--write] [--human]
```

Without `--write`, `report` is read-only and prints the derived report. With `--write`, it atomically writes `reports/run-report.json` inside the selected run root and returns its digest/path.

- [ ] **Step 1: Write failing efficiency-schema tests**

Write the RED test against this complete stable shape, then update `templates/optimization-report.schema.json` in Step 4 to require the same fields and reject additional properties:

```json
{
  "schema_version": 1,
  "run_id": "cpe-example",
  "launches": {
    "compiler": 1,
    "controller": 3,
    "verification": 4,
    "avoided": 5
  },
  "recovery": {
    "productive_timeouts": 1,
    "no_progress_slices": 0,
    "unchanged_blocker_stops": 1,
    "budget_stops": 0,
    "envelope_repairs": 1
  },
  "verification": {
    "executions": 4,
    "reuses": 3,
    "reuses_by_phase": {"task": 2, "affected": 1, "branch_final": 0, "merged_main": 0}
  },
  "reviews": {
    "task": 4,
    "delta": 1,
    "whole_branch": 1,
    "redundant_receipts": 0,
    "consolidated_fix_cycles": 1
  },
  "coordination": {
    "spawns": 4,
    "max_depth": 2,
    "fork_turns_none": 4,
    "fork_turns_all": 0,
    "unjustified_full_context_forks": 0,
    "compactions": 0,
    "declared_context_refs": 12,
    "declared_context_bytes": 193536,
    "context_measurement_kind": "declared_refs_not_provider_ingestion",
    "usage_scope": "controller_and_nested_agents_aggregate",
    "usage_attribution": "unavailable",
    "usage_attribution_unavailable_reason": "provider_event_not_agent_scoped"
  },
  "usage": {
    "attempts_finished": 3,
    "attempts_fully_observed": 2,
    "input": {
      "observed_tokens": 4100,
      "known_attempts": 2,
      "unknown_attempts": 1,
      "total_kind": "lower_bound"
    },
    "cached_input": {
      "observed_tokens": 3075,
      "known_attempts": 2,
      "unknown_attempts": 1,
      "total_kind": "lower_bound"
    },
    "uncached_input": {
      "observed_tokens": 1025,
      "known_attempts": 2,
      "unknown_attempts": 1,
      "derivation": "input_minus_cached_per_attempt",
      "total_kind": "lower_bound"
    },
    "output": {
      "observed_tokens": 210,
      "known_attempts": 2,
      "unknown_attempts": 1,
      "total_kind": "lower_bound"
    },
    "reasoning_output": {
      "observed_tokens": 40,
      "known_attempts": 2,
      "unknown_attempts": 1,
      "total_kind": "lower_bound"
    },
    "launcher_prompt": {
      "observed_bytes": 7497,
      "known_attempts": 3,
      "unknown_attempts": 0,
      "unit": "bytes"
    },
    "paired_observation_cache_ratio": 0.75,
    "unknown_attempt_duration_ms": 3600000,
    "unknown_attempts_by_reason": {"timeout": 1},
    "scope": "controller_and_nested_agents_aggregate",
    "attribution": "unavailable"
  },
  "context_artifacts": {
    "produced_files": 37,
    "produced_bytes": 712704,
    "declared_context_refs": 12,
    "declared_context_bytes": 193536,
    "review_diff_files": 8,
    "review_diff_bytes": 524288,
    "largest_review_diff_bytes": 131072,
    "duplicate_review_diff_digests": 1,
    "measurement_kind": "produced_and_declared_refs",
    "sealed_evidence_limit_exceeded": false
  },
  "duration_seconds": {
    "total": 2400,
    "compiler": 12,
    "controller": 1800,
    "verification": 400,
    "blocked": 188
  },
  "data_quality": {
    "complete": false,
    "usage_completeness_ratio": 0.6667,
    "coordination_telemetry_available": true,
    "declared_context_metadata_available": true,
    "artifact_inventory_available": true,
    "usage_includes_nested_agents": true,
    "warnings": ["one attempt ended without final usage"]
  }
}
```

Derive all values from validated events/receipts; do not trust child-provided aggregate totals. Each usage field has independent known/unknown counts. Derive uncached input per attempt only when both input and cached input are valid, then sum. Compute the cache ratio only over those paired observations. Reject booleans, negative/overflowing counters, and cached input greater than paired input. Unknown values remain `null` or increase the relevant unknown counter; they never become zero.

The aggregate usage scope is always explicit. `controller_and_nested_agents_aggregate` may not be allocated to implementer/reviewer roles unless independently attributable provider events exist. Launcher prompt bytes, produced artifact bytes, declared context bytes, bounded output bytes, and model tokens remain separate units.

- [ ] **Step 2: Write failing report safety tests**

Prove:

- report size is capped at 1 MiB;
- report contains normalized reason codes and artifact references, not full logs/source/prompts;
- corrupt events produce `data_quality.warnings` and cannot inflate avoided-work metrics;
- timeout attempts without a final usage event contribute their duration and normalized reason to usage-darkness fields;
- partial usage fields preserve independent completeness and never fabricate uncached input;
- produced artifact inventory is metadata-only and is not labelled as model-consumed context;
- missing declared-context bytes remain `null`, not zero;
- raw review diff bodies never appear in reports or sealed evidence;
- materialization uses an atomic replace and a deterministic canonical digest;
- `report --write` cannot write outside the selected run root;
- missing worktree reports `observed_head=null` plus `last_known_head`, never substitutes the source commit.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.EfficiencyReportTests \
  evals.check_cli.EfficiencyCliTests \
  evals.check_cli.ReportCliTests -v
```

Expected: missing schemas/commands.

- [ ] **Step 3a: Add the sanitized format-1 forensic fixture**

Create `evals/fixtures/canvas-format1-token-forensic.json` from the approved addendum snapshot. It must declare `provenance=direct_cpe_format1_forensic`, `count_as_format2_runtime_metrics=false`, `sanitized=true`, and `snapshot_state=running`. Preserve stable aggregate attempt, usage, duration, timeout, and artifact-class counts only. Reject prompt, transcript, raw log, source body, arbitrary error prose, secrets, absolute home paths, or format-2 success claims.

Add fixture tests proving it can exercise report completeness and privacy logic but cannot enter format-2 lifecycle success, savings, or cross-run promotion totals.

- [ ] **Step 4: Implement one derivation pipeline for inspect and report**

`inspect --efficiency` and `report` must call the same `build_efficiency_summary()`. The report adds run identity, plan outcomes, blockers, obligations, evidence references, branch handoff, field-complete usage, context artifact pressure, and data-quality warnings. No command may independently maintain counters.

The Wave 1 minimal usage object is intentionally replaced here. Preserve observed input, cached input, output, reasoning output, launcher prompt bytes, per-field known/unknown counts, paired uncached derivation, cache ratio, unknown attempt duration/reasons, aggregate scope, and attribution availability. Launcher prompt size remains bytes, not tokens. Do not embed provider prices.

Update `optimization-report.schema.json` to mirror this result with `additionalProperties=false` at every object boundary. Preserve `format_version=2` for the durable run contract and `schema_version=1` for this report shape.

- [ ] **Step 5: Implement safe report materialization**

Serialize with sorted keys and compact separators, enforce the 1 MiB limit before writing, fsync, and atomically replace `reports/run-report.json`. Append `report.materialized` only after the file is durable.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the command from Step 3. Expected: all report/efficiency tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/operations.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/templates/optimization-report.schema.json \
  skills/kws-codex-plan-executor/evals/fixtures/canvas-format1-token-forensic.json \
  skills/kws-codex-plan-executor/evals/check_cli.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): expose efficiency and run reports"
```

---

### Task 3: Add conservative cross-run recurring-signal analysis

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/analysis.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class OptimizationSignal:
    signal_key: str
    category: Literal[
        "repeated_blocker", "verification_duplication", "review_duplication",
        "context_overfork", "no_progress_recovery", "envelope_repair",
        "usage_darkness", "artifact_growth", "context_payload_amplification"
    ]
    reason_code: str
    run_ids: tuple[str, ...]
    occurrence_count: int
    metric_kind: Literal[
        "duration_seconds", "artifact_bytes", "declared_context_bytes"
    ]
    cumulative_metric_value: int
    cumulative_duration_seconds: int
    evidence_refs: tuple[str, ...]
    confidence: Literal["candidate", "promotable"]

def normalize_signal(event: Mapping[str, object]) -> tuple[str, str] | None: ...
def analyze_runs(run_roots: Sequence[Path]) -> list[OptimizationSignal]: ...
```

**CLI contract:**

```text
cpe.py analyze [--workspace PATH] [--since YYYY-MM-DD] [--limit N] [--human]
```

- [ ] **Step 1: Write failing normalization tests**

The normalized key may use only stable fields such as category, reason code, command ID, phase, capability, and scope. It must exclude run ID, timestamps, source paths, branch names, PIDs, ports, arbitrary prose, and raw error text.

Two events with different incidental fields but the same stable cause must normalize to the same key. Semantically different command IDs, phases, capabilities, or reason codes must not collapse.

- [ ] **Step 2: Write failing promotion-threshold tests**

Required cases:

- same signal in two independent run IDs: `promotable`;
- three occurrences in one run totaling exactly 1800 seconds: `promotable`;
- three occurrences in one run totaling 1799 seconds: `candidate`;
- two occurrences in one run totaling more than 1800 seconds: `candidate`;
- duplicate event IDs or replayed JSONL lines count once;
- child hypotheses without parent/derived corroboration are excluded;
- corrupt or data-quality-incomplete runs cannot make a signal promotable;
- evidence refs are bounded to 20 and contain only relative paths/digests.
- the sanitized Canvas direct-CPE fixture may produce regression signals from its two run IDs, while ReadMates and GasStation comparative fixtures remain excluded from promotion counts and CPE efficiency totals.
- the format-1 token forensic fixture is excluded from format-2 efficiency and promotion totals but remains usable as a report/data-quality regression baseline;
- `usage_darkness` is promotable from two independent format-2 runs, or three same-run attempts with at least 1800 seconds of unknown-usage duration;
- `artifact_growth` is promotable from two independent format-2 runs, or three same-run checkpoints whose produced inventory exceeds the 128-file or 8-MiB sealed-evidence boundary;
- `context_payload_amplification` is promotable from two independent format-2 runs, or three same-scope review observations with increasing declared context bytes totaling at least 8 MiB;
- production artifact bytes without declared context metadata cannot promote `context_payload_amplification`;
- byte-based categories do not reuse duration thresholds, and duration-based categories do not infer bytes.

- [ ] **Step 3: Write failing CLI privacy and filtering tests**

Prove `analyze`:

- reads only valid format-2 runs;
- applies workspace/date/limit filters before event loading;
- emits no source snippets, prompts, transcripts, or arbitrary error prose;
- is read-only and launches no children;
- marks legacy runs unsupported in warnings;
- returns deterministic ordering by confidence, occurrence count, metric kind, cumulative metric value, duration, then signal key.

- [ ] **Step 4: Run focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.CrossRunAnalysisTests \
  evals.check_cli.AnalyzeCliTests -v
```

Expected: missing analysis module/command.

- [ ] **Step 5: Implement bounded analysis**

Use streaming JSONL reads with the Wave 1 event-size limit. Analyze at most 1000 selected runs and at most 100,000 valid events. Normalize each category to its approved `metric_kind`; never compare byte-valued thresholds with duration-valued thresholds. Return an explicit truncation warning when either cap is hit. The command creates no issue, commit, task, or network request; it only produces evidence-backed local candidates.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the command from Step 4. Expected: all normalization, threshold, deduplication, privacy, and read-only tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/analysis.py \
  skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/evals/check_cli.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "feat(cpe): analyze recurring execution waste"
```

---

### Task 4: Make completion a truthful branch handoff

**Files:**

- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

**Interfaces:**

- Consumes: final format-2 structural evidence, current/missing worktree observations, and optional separate parent integration receipt.
- Produces: immutable `results/branch-handoff.json` and its state digest/reference.

**Handoff schema:**

```json
{
  "schema_version": 1,
  "scope": "branch_handoff",
  "run_id": "cpe-example",
  "branch": "codex/cpe-example",
  "worktree": "/tmp/cpe-example-worktree",
  "observed_head": "1111111111111111111111111111111111111111",
  "last_known_head": "1111111111111111111111111111111111111111",
  "base_commit": "2222222222222222222222222222222222222222",
  "plan_results": [],
  "whole_branch_review_receipt": "evidence/reviews/review-final.json",
  "acceptance_receipts": [],
  "open_obligations": [],
  "integration": {
    "status": "not_observed",
    "receipt": null
  }
}
```

- [ ] **Step 1: Write failing handoff truthfulness tests**

Prove:

- normal completed worktree reports the current observed HEAD;
- deleted/missing worktree reports `observed_head=null` and preserves `last_known_head`;
- missing worktree never substitutes base/source commit as observed HEAD;
- branch completion keeps `integration.status=not_observed` without a separate parent receipt;
- merge, push, deploy, or product acceptance claims in child prose cannot change integration status;
- a separate parent-observed integration receipt can set an explicit integration status in a later read/report without rewriting the branch handoff.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.BranchHandoffTests -v
```

Expected: current summary conflates missing-worktree observations or lacks the handoff boundary.

- [ ] **Step 3: Persist the handoff before completed transition**

Write `results/branch-handoff.json` atomically after final structural gates pass and before state moves to `completed`. Save its digest/path in state. If handoff materialization fails, do not mark the run completed.

Use `observed_head` only when `git rev-parse HEAD` succeeds in the saved worktree at report time. Preserve the latest earlier observed value separately as `last_known_head`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the command from Step 2. Expected: all handoff truthfulness tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/reporting.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "fix(cpe): report branch handoff truthfully"
```

---

### Task 5: Split structural acceptance from lifecycle orchestration after behavior is fixed

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/acceptance.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`

This is a behavior-preserving internal refactor. Do it only after Tasks 1–4 and Waves 0–3 have fixed all public behavior with deterministic tests.

**Interfaces:**

```python
@dataclass(frozen=True)
class AcceptanceContext:
    run_root: Path
    worktree: Path
    plan_id: str
    starting_commit: str
    current_head: str
    result_path: Path
    launch_returncode: int
    launch_timed_out: bool
    launch_forced_cleanup: bool

@dataclass(frozen=True)
class AcceptanceDecision:
    accepted: bool
    reason_code: str
    status: Literal["completed", "checkpointed", "blocked", "failed"]
    result: Mapping[str, object] | None
    evidence_refs: tuple[str, ...]

def evaluate_plan_result(context: AcceptanceContext) -> AcceptanceDecision: ...
```

- [ ] **Step 1: Freeze the current acceptance decision table with failing characterization gaps**

Convert the existing handoff tests into a table that covers every terminal reason:

- malformed/oversized result;
- wrong plan ID or HEAD;
- broken ancestry;
- dirty worktree;
- nonzero exit, timeout, and forced cleanup;
- invalid verification receipt/key;
- unsafe workflow receipt;
- envelope-repair eligible and ineligible errors;
- missing/stale review receipt;
- open transition obligation;
- completed, checkpointed, blocked, and failed status mapping.

Before moving code, add missing cases until this decision table passes against the existing runner. The refactor may not change a single expected reason code or launch count.

- [ ] **Step 2: Run the characterization tests before refactoring**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest evals.check_runner.AcceptanceDecisionTableTests -v
```

Expected: all decision rows pass against pre-refactor behavior. If a row fails, fix the fixture or behavior as its own focused change before proceeding.

- [ ] **Step 3: Move structural result acceptance into `acceptance.py`**

Move strict result-envelope validation, HEAD/ancestry/cleanliness checks, verification/review/obligation reference validation, and envelope-repair dispatch behind `evaluate_plan_result()`. The module may call pure helpers from `evidence.py`, `review_evidence.py`, `obligations.py`, and `verification.py`.

Keep these in `runner.py`:

- run/resume locks and state transitions;
- worktree creation/reconciliation;
- compiler and controller launch ordering;
- checkpoint/budget decisions;
- event persistence and report triggering.

Keep these in `launcher.py`:

- command/request construction;
- subprocess start and process-group ownership;
- two-pipe draining, bounded logs, timeout, and cleanup;
- structured result bytes returned to the caller.

`launcher.py` must not import state, evidence, review, obligation, reporting, or acceptance policy modules.

- [ ] **Step 4: Replace runner condition chains with one decision boundary**

After each controller slice, construct `AcceptanceContext`, call `evaluate_plan_result()`, append one `result.acceptance_decided` parent event with its reason/evidence refs, and apply the returned status through the existing transition functions. Do not duplicate acceptance checks in runner and the new module.

- [ ] **Step 5: Run characterization, process, and full gates**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.AcceptanceDecisionTableTests \
  evals.check_runner.SequentialRunnerTest.test_timeout_kills_the_complete_process_group \
  evals.check_runner.SequentialRunnerTest.test_timeout_and_exception_paths_drain_both_pipes -v
./evals/run.sh
```

Expected: exact decision reasons/launch counts remain unchanged and the complete suite passes once after the move.

- [ ] **Step 6: Inspect responsibility boundaries and commit Task 5**

```bash
rg -n "from \.((state|evidence|review_evidence|obligations|reporting|acceptance))" \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
rg -n "_RESULT_|_WORKFLOW_RECEIPT_FIELDS|def _handoff_error" \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
```

Expected: both searches return no matches.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/acceptance.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/evals/check_runner.py
git commit -m "refactor(cpe): isolate structural acceptance"
```

---

### Task 6: Run a disposable live canary with the unchanged user workflow

**Files:**

- Create: `skills/kws-codex-plan-executor/evals/live_canary.sh`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/live-canary-spec.md`
- Create: `skills/kws-codex-plan-executor/evals/fixtures/live-canary-plan.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Modify: `skills/kws-codex-plan-executor/README.md`

**Interfaces:**

- Consumes: normal public `run --spec --plan --workspace`, real Codex CLI, and a disposable local Git repository.
- Produces: one preserved audited run ID plus passing branch-handoff/efficiency/report evidence; never mutates a remote.

The canary is opt-in and must not run from `evals/run.sh`, because it invokes a real Codex child and can incur time/cost. It is the release gate for 2.0.0, not a per-change regression test.

- [ ] **Step 1: Write the canary fixture**

The disposable repository starts with one small Python function and a failing unit test. The plan has two tasks:

1. implement the function with focused verification and a task review receipt;
2. run final whole-branch verification/review and finish.

The fixture must not require network access, package installation, browser state, or external services.

- [ ] **Step 2: Implement a safe canary script**

`live_canary.sh` must:

1. create a repository with `mktemp -d`;
2. install a trap that removes only that resolved temporary path;
3. initialize Git and commit the fixture;
4. call the normal public interface with `--spec`, `--plan`, and `--workspace`;
5. capture the run ID from JSON output;
6. assert format 2, compiled index, execution ledger, events, evidence, report, and branch handoff exist;
7. assert the canary unit test passes in the isolated worktree;
8. assert no runtime artifact was written into the product repository;
9. run `inspect --efficiency` and `report` successfully;
10. assert the usage report distinguishes cached/uncached/output/reasoning fields, even when the fake workload produces zero or missing values;
11. assert produced artifacts and declared context refs are separate and contain no raw content;
12. print the run ID and preserve the run root for audit while removing the disposable product repository.

Reject an empty, `/`, home directory, workspace root, or unresolved temp path before cleanup.

- [ ] **Step 3: Run shell syntax and fixture-only checks**

```bash
bash -n skills/kws-codex-plan-executor/evals/live_canary.sh
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.LiveCanaryFixtureTests -v
```

`LiveCanaryFixtureTests` must prove the fixture has two ordered tasks, no network/package/browser/external-service dependency, safe absolute-path substitution, and no remote mutation. Expected: shell syntax and focused fixture checks pass before the paid/live call. Do not repeat the full deterministic suite here; Task 5 already ran it and Task 6 changes no runtime code.

- [ ] **Step 4: Run the live canary once**

```bash
cd skills/kws-codex-plan-executor
canary_output_file="$(mktemp)"
trap 'rm -f "$canary_output_file"' EXIT
./evals/live_canary.sh | tee "$canary_output_file"
canary_run_id="$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1], encoding="utf-8").read().splitlines()[-1])["run_id"])' "$canary_output_file")"
python3 scripts/cpe.py inspect --run-id "$canary_run_id" --efficiency
python3 scripts/cpe.py report --run-id "$canary_run_id"
python3 scripts/cpe.py analyze --limit 10
```

`live_canary.sh` must emit a final one-line JSON object containing `run_id` so the commands above require no manual substitution. Expected: exit 0; output contains a completed branch handoff, passing canary test, valid efficiency summary, and report path.

If the canary exposes a product defect, add one focused deterministic regression test, fix it, rerun that test, then rerun the canary once. Do not loop the full suite for every repair.

- [ ] **Step 5: Inspect the canary flight recorder**

Review the three JSON outputs produced in Step 4. Confirm there are no missing digests, unexplained launches, open obligations, stale final reviews, or false integration claims.

Also confirm usage scope/completeness is explicit, no aggregate usage is silently assigned to roles, and artifact production bytes are not reported as consumed tokens.

- [ ] **Step 6: Document the live gate and commit Task 6**

```bash
git add skills/kws-codex-plan-executor/evals/live_canary.sh \
  skills/kws-codex-plan-executor/evals/fixtures/live-canary-spec.md \
  skills/kws-codex-plan-executor/evals/fixtures/live-canary-plan.md \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/README.md
git commit -m "test(cpe): add format 2 live canary"
```

---

### Task 7: Release CPE 2.0.0 and run final verification

**Files:**

- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py`
- Modify: `skills/kws-codex-plan-executor/templates/plan-result-schema.json`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**

- Consumes: accepted Wave 0–4 commits and the successful live-canary receipt.
- Produces: public CPE version `2.0.0`, synchronized docs/schema/inventory, and one post-commit complete deterministic gate.

- [ ] **Step 1: Update version and public contract**

Set the skill/runtime version to `2.0.0` only now. Document:

- unchanged Superpowers plan inputs and automatic internal compilation;
- format-2-only support and explicit lack of legacy migration;
- run-root layout and evidence limits;
- typed blockers and progress-aware recovery budgets;
- verification reuse key and invalidation rules;
- review/obligation structural validation boundary;
- flight-recorder and report locations;
- `doctor`, `list`, `inspect --efficiency`, `report`, and `analyze` commands;
- branch-handoff meaning and the separate integration-receipt boundary;
- live canary usage and cost warning.
- field-complete token evidence, lower-bound semantics, aggregate attribution limits, and context-artifact measurement boundaries from the observability addendum;
- POSIX support boundary and the non-binding `split_or_checkpoint_required` / `handoff_to_waygent` advisories; CPE never launches Waygent automatically.

- [ ] **Step 2: Reconcile the tracked inventory**

Update the README inventory to include every new runtime module and canary fixture. Assert it against Git:

```bash
git ls-files skills/kws-codex-plan-executor | sort
```

Expected tracked runtime modules include:

```text
scripts/cpe_runtime/analysis.py
scripts/cpe_runtime/acceptance.py
scripts/cpe_runtime/capabilities.py
scripts/cpe_runtime/compiler.py
scripts/cpe_runtime/coordination.py
scripts/cpe_runtime/evidence.py
scripts/cpe_runtime/obligations.py
scripts/cpe_runtime/operations.py
scripts/cpe_runtime/progress.py
scripts/cpe_runtime/reporting.py
scripts/cpe_runtime/review_evidence.py
scripts/cpe_runtime/verification.py
```

- [ ] **Step 3: Run format/schema consistency checks**

Add deterministic assertions to the existing eval suites that:

- runtime `FORMAT_VERSION == 2`;
- package/skill version is `2.0.0`;
- template schema declares format 2 and matches validator fields;
- every documented command parses;
- no format-1 loading, migration, resume, dual-write, or compatibility execution path exists; minimal read-only version detection for the `unsupported_legacy_run` error remains;
- all runtime paths stay under the run root or isolated worktree.

- [ ] **Step 4: Run focused release-contract tests**

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.ReleaseContractTests \
  evals.check_cli.ReleaseCommandTests -v
```

Expected: all release-contract cases pass.

- [ ] **Step 5: Run static release hygiene without repeating the full suite**

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
bash -n evals/live_canary.sh
```

Expected: syntax checks pass. The focused release-contract tests from Step 4 cover version/schema/command changes; the complete suite runs once on the actual release commit in Step 8.

- [ ] **Step 6: Run repository hygiene and final diff review**

```bash
cd /Users/kws/source/private/Archive
git diff --check
git status --short --branch --untracked-files=all
git diff --stat HEAD~6..HEAD
git diff HEAD~6..HEAD -- skills/kws-codex-plan-executor
```

Review against `code_review.md` with findings first. Confirm:

- no path traversal or symlink acceptance;
- no process-group regression;
- no unbounded logs/events/reports;
- no secret/transcript persistence;
- no semantic review ownership in CPE;
- no broad or cross-run verification cache;
- no legacy format support;
- no false integration-completion claim.

- [ ] **Step 7: Commit the release**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py \
  skills/kws-codex-plan-executor/templates/plan-result-schema.json \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "release(cpe): publish 2.0.0"
```

- [ ] **Step 8: Verify the release commit, not only the pre-commit tree**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check HEAD^ HEAD
git status --short --branch --untracked-files=all
```

Expected: complete suite passes once on the release commit and the worktree is clean.

---

## Wave 4 Done When

- `doctor` diagnoses CPE prerequisites without launching children or mutating runs.
- `list` discovers valid format-2 runs safely and reports legacy roots as unsupported.
- `inspect --efficiency` and `report` share one evidence-derived metrics pipeline.
- Usage reports preserve cached, uncached, output, reasoning, completeness, unknown duration/reason, aggregate scope, and attribution availability.
- Produced artifact inventory and declared context refs remain separate from model token totals.
- `analyze` promotes only repeated, corroborated, privacy-safe optimization signals at the approved threshold.
- Usage-darkness and artifact/context amplification signals use their approved category-specific thresholds.
- Missing worktrees report `observed_head=null` and retain a separate `last_known_head`.
- Completion produces a truthful branch handoff and never implies merge/push/deploy/integration without a separate receipt.
- The unchanged `--spec --plan --workspace` workflow succeeds in a disposable real-Codex canary.
- CPE version is `2.0.0`, format 1 is unsupported, and no migration path exists.
- The complete deterministic suite, live canary, release-commit suite, `git diff --check`, and final review all pass.
