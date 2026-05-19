# Drift Reconciliation

Run before reporting `lifecycle_outcome=finished`:

```bash
python3 scripts/reconcile_state.py --state "$STATE_PATH" --check
python3 scripts/reconcile_state.py --state "$STATE_PATH" --repair-safe
```

`--check` reports drift without modifying `state.json`. `--repair-safe`
persists the narrow safe repairs and records drift metadata in state.

Safe repair is intentionally narrow:

| type | repair |
| --- | --- |
| `missing-context-health-timestamp` | copy `timestamps.updated_at` into `context_health.last_checked_at` |

Blocking drift remains unresolved until the executor fixes the source of truth.
Typical blockers include finished tasks without manifests, open carried
acceptance, and `context.json` basis hash mismatch.
