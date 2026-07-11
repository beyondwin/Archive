# Drift, Reconciliation, And Repair

Reconciliation checks, in order: manifest and source hashes, event sequence and
hash chain, fresh projection, stored projection, git identity and diff, task
file claims, evidence digests, attempt terminal state and route attestation,
then verification/completion links.

Results include `clean`, `clean_incomplete`, `repairable`, or `blocking_drift`.
`clean_incomplete` is integrity-valid but does not imply completion. Check and
repair-plan modes are read-only. Apply requires one exact run target, an
allowlisted action, action-specific evidence in `--details`, a non-empty
`--expected-projection-delta`, and explicit `--apply`.

The exact safe actions are:

- `rebuild_snapshot`
- `regenerate_derived_reports`
- `mark_stale_attempt_interrupted`
- `reconnect_existing_evidence`
- `resolve_blocker`
- `schedule_retry`

`rebuild_snapshot` and `regenerate_derived_reports` may be offered by
`reconcile_state.py --repair-safe`. Stateful actions use `repair_runs.py` and
must prove the declared projection delta after replay. If the requested state
already holds, repair returns `applied=false` and appends no event. Repair
cannot edit product files, change source hashes, invent attestation or success,
rewrite a damaged event chain, or mutate an unsupported schema.

```bash
python3 scripts/reconcile_state.py --run-dir RUN_DIR --check
python3 scripts/reconcile_state.py --run-dir RUN_DIR --repair-safe
python3 scripts/repair_runs.py --run-dir RUN_DIR --dry-run
python3 scripts/repair_runs.py --run-dir RUN_DIR --action schedule_retry \
  --details '{"task_id":"T1","phase":"implementation","root_cause_key":"KEY"}' \
  --expected-projection-delta '{"task_status:T1":"implementing"}' --apply
```
