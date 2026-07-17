# Plan 02 Final Verification Fix Report

## Root cause

The two failing tests had stale isolation fixtures after compiler preparation and
durable execution evidence became mandatory. The spawn-failure test configured
the missing executable on the shared launcher, so compiler preparation failed
before the intended plan-launch failure. The resume test synthesized a completed
first-plan result without the now-required execution ledger, so evidence
ingestion correctly failed closed before the second plan could block.

## Investigation evidence

- Both reserved failures reproduced unchanged with focused `unittest` targets.
- The spawn case returned `compiled_index_preparation_failed` before creating a
  plan attempt.
- The resume case's durable event stream ended at `plan.evidence_failed` with
  `required evidence is missing or redirected` for `plan-01`.
- Production compiler preparation and evidence ingestion behaved as designed;
  only the test fixtures bypassed their prerequisites.

## Files changed

- `skills/kws-codex-plan-executor/evals/check_runner.py`
  - Uses the working fake compiler independently of the deliberately missing
    plan launcher in the spawn-failure test.
  - Uses the existing fake Codex workflow/evidence fixture for the synthesized
    completed plan in the resume test.

## RED evidence

`python3 -m unittest -v evals.check_runner.SequentialRunnerTest.test_spawn_failure_is_recorded_as_a_durable_failed_attempt evals.check_runner.SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state`

Outcome before the fix: 2 tests run, 2 failures. Observed errors matched the
brief: `compiled_index_preparation_failed` and `failed` instead of `blocked`.

## GREEN commands and exact outcomes

- Focused failures: same command as RED — `Ran 2 tests in 1.480s`, `OK`.
- Directly affected coverage:
  `python3 -m unittest -v evals.check_runner.SequentialRunnerTest.test_run_prepares_index_before_worktree_and_reports_after_plan evals.check_runner.SequentialRunnerTest.test_plan_evidence_survives_worktree_removal evals.check_runner.SequentialRunnerTest.test_compiler_launcher_is_read_only_bounded_and_has_no_git_add_dir`
  — `Ran 3 tests in 0.559s`, `OK`.
- `git diff --check` — exit 0 with no output.

## Commit SHA

`6e60d7bb467d9406fe5b900ada8185dedef28940`

## Concerns

None. No production behavior, compiler safety boundary, evidence requirement,
or assertion was weakened. The reserved full eval suite was not run.

## Follow-up: direct eval entrypoint import

### Root cause and RED evidence

The first fix imported `workflow_receipt` as `evals.fake_codex`, which worked
when `check_runner` was loaded as a package but failed under the canonical
`run.sh` entrypoint. Direct execution places `evals/`, not its parent, on
`sys.path`; therefore the package-qualified import raised
`ModuleNotFoundError: No module named 'evals'` before any test ran.

### Fix

Import the sibling fixture as `fake_codex`, matching direct script execution
and preserving the fixture behavior added by the first fix.

### GREEN commands and exact outcomes

- `python3 evals/check_runner.py SequentialRunnerTest.test_spawn_failure_is_recorded_as_a_durable_failed_attempt SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state`
  — `Ran 2 tests in 1.227s`, `OK`.
- `python3 evals/check_runner.py --help`
  — exit 0; unittest help rendered, proving the direct entrypoint imports.
- `git diff --check` — exit 0 with no output.

### Commit SHA

Recorded in the final controller response for the commit containing this
follow-up section.

### Concerns

None. The reserved full eval suite was not run.

## Follow-up: FVR-001 dual entrypoint compatibility

### Root cause and RED evidence

The sibling-only `from fake_codex import workflow_receipt` fixed direct script
execution but made the plan-declared module-style command unable to import
`check_runner`. Running the exact module-style two-test command failed before
tests with two `ModuleNotFoundError: No module named 'fake_codex'` errors.

### Fix

Prefer the package-qualified fixture import and fall back to the sibling import
only when the missing module is specifically the `evals` package. This supports
both Python entrypoint layouts without masking an import failure inside the
fixture module.

### GREEN commands and exact outcomes

- Module style: `python3 -m unittest -v evals.check_runner.SequentialRunnerTest.test_spawn_failure_is_recorded_as_a_durable_failed_attempt evals.check_runner.SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state`
  — `Ran 2 tests in 1.424s`, `OK`.
- Direct script: `python3 evals/check_runner.py SequentialRunnerTest.test_spawn_failure_is_recorded_as_a_durable_failed_attempt SequentialRunnerTest.test_resume_skips_completed_plan_and_continues_current_git_state`
  — `Ran 2 tests in 1.224s`, `OK`.
- `git diff --check` — exit 0 with no output.

### Concerns

None. The reserved full eval suite was not run.
