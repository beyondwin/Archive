# Drift Reconciliation

Drift reconciliation detects mismatches between resumable state, compatibility
state, context snapshots, and project-local event evidence. Detection is
read-only by default. Repair mode may apply only explicitly safe mechanical
repairs.

Drift record shape:

```json
{
  "type": "stale-last-event-seq",
  "severity": "repairable",
  "detected_at": "2026-05-16T07:35:00Z",
  "message": "state.last_event_seq is 3 but events.jsonl ends at 4",
  "repair": "set state.last_event_seq to 4",
  "repaired_at": null
}
```

Severity enum:

- `info`
- `repairable`
- `blocking`

## Safe Repairs

| Drift | Repair |
| --- | --- |
| `stale-root-state-pointer` | update `.codex-orchestrator/state.json` pointer/copy from per-run state |
| `missing-event-journal-path` | set expected path if journal exists |
| `stale-last-event-seq` | set from journal tail |
| `missing-context-health-timestamp` | set to `timestamps.updated_at` only when finished state is otherwise valid |

## Blocking Drift

| Drift | Reason |
| --- | --- |
| `context-basis-hash-mismatch` | Source basis changed; agent must inspect. |
| `completed-task-missing-unit-manifest` | Cannot infer task write/context policy safely. |
| `finished-with-open-carried-acceptance` | Completion claim contradicts unresolved metric. |
| `finished-missing-completion-audit` | Existing state validator already blocks this. |
| `journal-run-id-mismatch` | Audit evidence may belong to another run. |

Blocking drift must leave a concrete `handoff_reason` or `context_health`
`next_action` when it stops a run.

