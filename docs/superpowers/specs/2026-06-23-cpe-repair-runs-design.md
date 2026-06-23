# CPE Run-State Repair/Cleanup Design

## Goal

Add a conservative CPE run-state repair flow that turns
`inspect_runs.py --quality-report --validate-state` follow-ups into an explicit
dry-run repair plan, and allows only narrow, validated state updates when the
operator selects one run and one safe action.

The first implementation should make stale or impossible-to-resume CPE runs
operationally honest. It should not delete files, remove worktrees, or hide
schema drift.

## Context

Current CPE state tooling is split across:

- `scripts/inspect_runs.py`: read-only recent-run inspection and
  `run_quality.open_followups`.
- `scripts/reconcile_state.py`: per-state drift detection with a small
  `--repair-safe` path.
- `scripts/validate_state.py`: hard state contract validation.

Recent inspection on this checkout showed real follow-up categories:

- `stale_non_terminal_run`
- `missing_execution_worktree`
- `state_schema_drift`

Waygent already has a safer product-runtime pattern in
`packages/orchestrator/src/orphanRuns.ts`: scan first, expose safe actions,
mark stale runs blocked before cleanup, and require explicit confirmation for
destructive actions. CPE should borrow the safety model, not the TypeScript
state schema.

## Non-Goals

- Do not delete worktrees or run directories in the first implementation.
- Do not repair arbitrary `validate_state.py` failures.
- Do not mutate finished successful runs.
- Do not merge this with `inspect_runs.py`; inspection must remain read-only.
- Do not route this through Waygent or revive the old CPE/CME split as product
  architecture.

## Proposed Interface

Add:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --recent 20 \
  --stale-hours 24 \
  --output /tmp/cpe-repair-plan.json
```

Apply one safe action:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --run-id <run_id> \
  --action mark-blocked-stale \
  --apply
```

Optional output modes:

- default JSON object for dashboards and humans.
- `--jsonl` for one repair candidate per line.

The script must default to dry-run. `--apply` requires both `--run-id` and
`--action`; broad apply is not allowed.

## Repair Plan Model

The dry-run payload should be deterministic:

```json
{
  "schema_version": "1",
  "checked_at": "2026-06-23T00:00:00Z",
  "dry_run": true,
  "summary": {
    "candidate_count": 1,
    "apply_safe_count": 1,
    "manual_review_count": 0
  },
  "candidates": [
    {
      "run_id": "example-run",
      "state_path": "~/.codex/orchestrator/example-run/state.json",
      "detected_followups": ["stale_non_terminal_run", "missing_execution_worktree"],
      "recommended_action": "mark-blocked-stale",
      "apply_safe": true,
      "reason": "non-terminal stale run cannot resume because execution worktree is missing",
      "state_patch_preview": {
        "lifecycle_outcome": "blocked",
        "current_phase": "recover",
        "current_blocker.category": "state_integrity_drift"
      }
    }
  ]
}
```

## Candidate Classification

### `mark-blocked-stale`

Use when all are true:

- `run_quality.open_followups` contains `stale_non_terminal_run`.
- The run is non-terminal.
- `missing_worktree` is true or `run_quality.open_followups` contains
  `missing_execution_worktree`.
- The state validates before the repair.
- The state has no existing `current_blocker`.

Dry-run marks it `apply_safe=true`.

Apply updates only that run's `state.json`:

- `lifecycle_outcome = "blocked"`
- `current_phase = "recover"`
- `handoff_reason` explains that the stale run cannot resume because the
  execution worktree is missing.
- `current_blocker` is set with:
  - `category = "state_integrity_drift"`
  - `summary` naming the stale run and missing worktree condition.
  - `recoverable = true`
  - `next_action_kind = "operator_decision"`
- `context_health.handoff_ready = true`
- `context_health.next_action` points to operator inspection or a fresh run.
- `timestamps.updated_at` is refreshed.
- `timestamps.completed_at` is set if absent.

After constructing the next state, run `validate_state.validate(next_state)`.
Only write the file if validation passes.

### `manual-review-required`

Use when any are true:

- `run_quality.validation_status = "failed"`.
- The state is unreadable or invalid JSON.
- The run already has `current_blocker`.
- The state path does not satisfy the CPE path invariant.
- The run is terminal `finished`.

Do not mutate. Include validator errors or the blocking reason in the repair
candidate.

### `acknowledge-cleaned-worktree`

Finished runs with missing execution worktrees are common after branch cleanup.
The first implementation should report this as non-mutating:

- `recommended_action = "acknowledge-cleaned-worktree"`
- `apply_safe = false`
- reason: finished state should not be rewritten without a v2.24 state field
  for cleanup acknowledgement.

This keeps the first change safe while leaving room for a later explicit
cleanup-ack field.

## Safety Rules

- No filesystem deletion.
- No mutation unless `--apply --run-id <id> --action <action>` is present.
- No mutation outside `~/.codex/orchestrator/<run_id>/state.json`.
- No mutation when `state.run_id` differs from the directory name.
- No mutation when the state path does not end with
  `.codex/orchestrator/<run_id>/state.json`.
- No mutation when `validate_state.py` fails before repair.
- No mutation when the repaired state fails validation.
- Use temp-file plus atomic replace for writes.
- Print a before/after summary and the validation status after apply.

## Documentation Updates

Update these CPE docs:

- `SKILL.md`: mention `repair_runs.py` after read-only inspection follow-ups.
- `README.md`: add dry-run and apply examples.
- `references/state-schema.md`: document stale blocked repair fields.
- `docs/state-and-logging.md`: explain dry-run/apply safety.
- `docs/evals-and-verification.md`: add the new eval.
- `docs/risks-limitations-deferrals.md`: replace the current read-only
  limitation with the first safe repair boundary.
- `HISTORY.md`: record the behavior change.

## Verification Plan

Add `evals/check_repair_runs.py`.

Required eval cases:

1. **Dry-run stale missing worktree**
   - Fixture: valid non-terminal state, old mtime, missing worktree.
   - Expect: `mark-blocked-stale`, `apply_safe=true`, no file mutation.

2. **Apply stale missing worktree**
   - Same fixture with `--apply --run-id ... --action mark-blocked-stale`.
   - Expect: state changes to blocked, `current_blocker` present,
     `timestamps.completed_at` present, `validate_state.py` passes.

3. **Finished missing worktree is not auto-applied**
   - Fixture: finished state, missing worktree.
   - Expect: candidate is reported, `apply_safe=false`, apply exits non-zero.

4. **Schema drift blocks repair**
   - Fixture: validator failure.
   - Expect: `manual-review-required`, validator errors surfaced, no mutation.

5. **Existing blocker blocks overwrite**
   - Fixture: stale non-terminal with `current_blocker`.
   - Expect: no overwrite; candidate explains existing blocker.

6. **Unsafe state path blocks apply**
   - Fixture: state path outside `.codex/orchestrator/<run_id>/state.json`.
   - Expect: apply exits non-zero and does not write.

7. **No candidates**
   - Fixture: clean terminal or active non-stale state.
   - Expect: exit 0, empty candidates, summary counts zero.

8. **JSONL output**
   - Fixture: two candidates.
   - Expect: one valid JSON object per candidate line.

Full verification:

```bash
cd skills/kws-codex-plan-executor
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

## Open Follow-Up

Worktree/run-directory deletion should be a separate design. It needs explicit
confirmation, safe path checks, and possibly parity with Waygent
`cleanupStaleRunWorktree`.
