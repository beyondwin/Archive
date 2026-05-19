# Event Journal

The project-local event journal is replayable execution evidence for one run.
It complements state, but does not replace it.

| Layer | Location | Purpose | Source of truth |
| --- | --- | --- | --- |
| State | `.codex-orchestrator/runs/<run_id>/state.json` | Current resumable run state | yes |
| Event journal | `.codex-orchestrator/runs/<run_id>/events.jsonl` | Replayable project-local evidence | no |
| Learning log | `~/.codex/learning/kws-codex-plan-executor/` | Cross-repo process learning | no |

Event shape:

```json
{
  "schema_version": "1",
  "run_id": "20260516T073000Z-archive-codex-example-abcdef0-a1b2c3",
  "seq": 1,
  "timestamp": "2026-05-16T07:30:00Z",
  "type": "run_started",
  "payload": {
    "mode": "interactive",
    "state_path": ".codex-orchestrator/runs/20260516T073000Z-archive-codex-example-abcdef0-a1b2c3/state.json"
  }
}
```

`seq` is monotonic per run and starts at 1. `state.last_event_seq` should match
the last appended sequence before terminal completion.

Append an event with:

```bash
python3 scripts/append_run_event.py \
  --state .codex-orchestrator/runs/<run_id>/state.json \
  --type task_contract_recorded \
  --payload '{"task_id":"task_2"}'
```

The helper resolves `.codex-orchestrator/runs/<run_id>/events.jsonl`, rejects a
payload `run_id` that does not match `state.run_id`, appends the next sequence,
and updates `state.event_journal_path` plus `state.last_event_seq`.

## Redaction

Reject or redact keys matching `token`, `secret`, `password`, `api_key`,
`authorization`, `cookie`, `private_key`, or `session`.

Store paths, command names, statuses, issue keys, and short summaries. Do not
store full prompt transcripts. Do not store full command output.

## Event Types

Initial runtime support may include only the event types needed by the executor
flow, such as `run_started`, `task_contract_recorded`, `task_completed`,
`verification_completed`, `blocker_recorded`, and `run_finished`. Future event
types should remain short, factual, and derived from project-local execution
state.

Current event type vocabulary:

- `run_started`
- `context_snapshot_created`
- `pre_dispatch_checked`
- `dispatch_gate_failed`
- `task_contract_recorded`
- `task_started`
- `task_completed`
- `verification_started`
- `verification_passed`
- `verification_failed`
- `drift_detected`
- `drift_repaired`
- `blocked`
- `failed`
- `finished`

## AgentLens Dual-Write (parity window)

During the parity window, every event-journal append also mirrors to AgentLens
under the `kws-cpe.<event>` namespace. Open the AgentLens orchestration run at
execution init with `agentlens run-open --agent kws-cpe-orchestrator
--workspace "$WORKTREE_ABS" --meta plan=...` and persist the returned id as the
run-level `agentlens_orchestration_run` field of
`.codex-orchestrator/runs/<run_id>/state.json`. Then guard every emit:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type kws-cpe.<event> \
    --payload-json '<json>' \
    2>/dev/null || true
fi
```

Expected `kws-cpe.<event>` mirror types (one per event-journal vocabulary
item) at minimum:

- `kws-cpe.run_started`
- `kws-cpe.task_started`
- `kws-cpe.task_completed`
- `kws-cpe.verification_passed`
- `kws-cpe.verification_failed`
- `kws-cpe.compaction` (emitted at phase transitions when applicable)
- `kws-cpe.blocker`
- `kws-cpe.failed`
- `kws-cpe.run_completed` (terminal `finished`)

Headless `codex exec` spawns must propagate the parent id with
`AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`. The legacy
`scripts/append_run_event.py` call stays in place alongside the AgentLens
append until parity is verified. AgentLens failures are never blocking.
