# Task 1 Report: Lock The Format-2 State Contract

Status: DONE_WITH_CONCERNS

Commit: `b5e526e feat(cpe): establish format two state`

## Implementation

- Established format 2 with the required run/plan statuses, trust levels, and plan budget.
- New runs start in `preparing`, create private `evidence/` and `reports/`, and use the required expanded plan record.
- Added exact field/type and semantic validation plus explicit, non-mutating format-1 rejection.
- Extracted `atomic_private_write()` while retaining canonical JSON, private modes, atomic replacement, file fsync, and directory fsync.
- Added bounded, trust-labelled event envelopes while retaining `O_NOFOLLOW`, regular-file checking, append, fsync, and `0600` behavior.
- Added the three required tests and a minimal format-2 store fixture helper.

## Files

- `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- `skills/kws-codex-plan-executor/evals/check_runner.py`

## TDD RED

Command:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_state_has_preparation_and_budget_fields \
  evals.check_runner.SequentialRunnerTest.test_format_one_state_is_unsupported_without_mutation -v
```

Result: exit 1, two expected failures. Creation reported `1 != 2`; legacy opening raised `invalid format-version-1 state` instead of `unsupported_legacy_run`.

## GREEN / Final Focused Verification

Command:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_state_has_preparation_and_budget_fields \
  evals.check_runner.SequentialRunnerTest.test_format_one_state_is_unsupported_without_mutation \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_has_bounded_trust_labelled_envelope \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_impossible_plan_and_run_relationships \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_incomplete_completed_evidence \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_nonpristine_future_plan -v
python3 -m py_compile scripts/cpe_runtime/state.py evals/check_runner.py
git diff --check
```

Result: exit 0; six tests passed, Python compilation passed, and diff hygiene passed.

Additional affected-state command:

```bash
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_snapshots_preserve_spec_and_plan_order \
  evals.check_runner.SequentialRunnerTest.test_worktree_creation_failure_never_leaves_running_state -v
```

Result: snapshot-order passed; the runner lifecycle test errored because unmigrated `runner.py` explicitly passes legacy `initial_status="initializing"`.

## Self-review

- Checked every exact constant, field, directory, legacy error, event field, and persistence requirement against the brief.
- Only the two declared task files were committed.
- The worktree was clean immediately after commit.

## Concerns

- `scripts/cpe_runtime/runner.py` still requests/emits legacy `initializing` and `interrupted` states. Broader runner lifecycle tests require the planned caller migration; this task did not expand beyond its declared files.
- The eventual full verification was not run, as requested.

## Fix Report

Status: FIXED

### Findings Addressed

- T1-F1: `append_event()` rejects reserved event-envelope fields before encoding or appending, so detail data cannot replace parent-owned identity metadata.
- T1-F2: plan budgets require the exact key set and integer (non-boolean) values before comparison with the format-2 defaults.

### Files

- `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- `skills/kws-codex-plan-executor/evals/check_runner.py`
- `.superpowers/sdd/task-1-report.md`

### TDD RED

Command:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_rejects_reserved_envelope_collisions \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_non_integer_budget_values -v
```

Result: exit 1. Reserved detail fields were accepted and persisted; a float-valued budget equivalent to the integer default was accepted. The initial collision test also confirmed Python's method signature itself rejects a duplicate `action` argument, so the focused test exercises the reserved keys that can reach `**details`.

### Focused GREEN

Commands:

```bash
cd skills/kws-codex-plan-executor
python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_rejects_reserved_envelope_collisions \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_non_integer_budget_values -v

python3 -m unittest \
  evals.check_runner.SequentialRunnerTest.test_format_two_state_has_preparation_and_budget_fields \
  evals.check_runner.SequentialRunnerTest.test_format_one_state_is_unsupported_without_mutation \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_has_bounded_trust_labelled_envelope \
  evals.check_runner.SequentialRunnerTest.test_format_two_event_rejects_reserved_envelope_collisions \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_non_integer_budget_values \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_impossible_plan_and_run_relationships \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_incomplete_completed_evidence \
  evals.check_runner.SequentialRunnerTest.test_state_rejects_nonpristine_future_plan -v
```

Result: exit 0. The two focused regressions passed, followed by all eight Task 1 focused tests passing.

### Self-review

- Confirmed all six envelope-owned names are reserved in production validation: `event_id`, `at`, `source`, `run_id`, `category`, and `action`.
- Confirmed rejected collisions leave the existing event stream byte-for-byte unchanged.
- Confirmed both float and boolean budget values are rejected, while exact integer defaults remain accepted by the original format-2 creation test.
- Kept the patch limited to T1-F1, T1-F2, focused tests, and this report; no full-suite run was performed.
