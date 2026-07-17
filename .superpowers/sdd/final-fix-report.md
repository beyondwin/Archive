# Final Fix Report

## Scope

Resolved the complete final-review finding set in one consolidated pass:

- `CPE-W0-F1`: consumer result-envelope drift from the strict format-2 schema.
- `CPE-W0-F2`: stale `last_known_head` selection for an active later plan when its worktree is missing.

The approved Wave 0 plan and `.superpowers/sdd/final-review.md` were sufficient; the design spec was not consulted.

## Root Causes

### CPE-W0-F1

`runner.py` retained the format-1 recovery triple (`retryable`, `failure_signature`, and `next_strategy`) in its optional consumer field set, normalized and validated that triple, interpreted it as automatic-recovery input, and emitted it in synthetic timeout results. This made the consumer broader than the strict format-2 JSON schema.

### CPE-W0-F2

When `observed_head` was unavailable, `_summary` always selected `current_plan_index - 1`. That is correct only after all plans complete; while a later plan is active, `current_plan_index` identifies that active plan and its persisted `last_known_head` is the truthful fallback.

## Changes

- Removed the legacy recovery fields from the accepted result field set and handoff semantics.
- Removed failed-result automatic recovery based on undeclared child fields.
- Removed legacy recovery metadata from synthetic timeout results; timeout remains a durable format-2 checkpoint.
- Kept undeclared top-level properties fail-closed as `invalid_result`.
- Selected the active plan for missing-worktree `last_known_head`, and selected the final plan only when `current_plan_index == len(plans)`.
- Replaced stale recovery-envelope test expectations with the format-2 stop behavior.
- Added deterministic coverage for each legacy field individually, the formerly accepted complete triple, arbitrary undeclared fields, no plan advancement, and a two-plan distinct-HEAD missing-worktree inspection.
- Added the `blocked_after_commit` fake-controller fixture used by the two-plan regression.

## TDD Evidence

RED command:

```text
python3 -m unittest evals.check_runner.SequentialRunnerTest.test_legacy_recovery_fields_are_rejected_without_plan_advancement evals.check_runner.SequentialRunnerTest.test_missing_worktree_reports_active_later_plan_last_known_head -v
```

Observed before production edits: 2 tests ran; the later-plan HEAD regression failed because inspect returned plan 1's commit instead of plan 2's persisted commit. The initial individual-field cases already failed closed under the old atomic-triple rule, so the regression was strengthened to include the complete legacy triple that the old consumer accepted.

Focused GREEN command:

```text
python3 -m unittest evals.check_runner.SequentialRunnerTest.test_legacy_recovery_fields_are_rejected_without_plan_advancement evals.check_runner.SequentialRunnerTest.test_undeclared_result_field_is_rejected_at_handoff evals.check_runner.SequentialRunnerTest.test_missing_worktree_reports_active_later_plan_last_known_head evals.check_runner.SequentialRunnerTest.test_missing_worktree_never_reports_source_commit_as_observed_head evals.check_runner.SequentialRunnerTest.test_timeout_persists_advanced_head_and_returns_without_relaunch -v
```

Observed: `Ran 5 tests in 2.724s` and `OK`.

Affected runner suite command:

```text
python3 -m unittest evals.check_runner -v
```

Observed after reconciling stale recovery-era assertions: `Ran 48 tests in 10.339s` and `OK`.

Per controller instruction, the complete final verification gate was not run.

## Concerns

None within this finding set. Private recovery capsules retain their internal signature/strategy fields for explicit resume context, but the public format-2 child result envelope neither accepts nor synthesizes those legacy top-level fields.
