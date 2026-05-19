# Event Journal

Replayable execution evidence for one run is recorded directly to AgentLens
under the `kws-cpe.<event>` namespace. The legacy project-local journal
(`.codex-orchestrator/runs/<run_id>/events.jsonl`) was retired at the v2.18
cutover along with `scripts/append_run_event.py`. State remains the source of
truth; AgentLens carries the event stream.

| Layer | Location | Purpose | Source of truth |
| --- | --- | --- | --- |
| State | `.codex-orchestrator/runs/<run_id>/state.json` | Current resumable run state | yes |
| Event stream | AgentLens (`kws-cpe.*` types under `agentlens_orchestration_run`) | Replayable evidence | no |
| Learning stream | AgentLens (`kws-cpe.learning.*` types under the same run) | Cross-repo process learning | no |

AgentLens event shape (orchestrator emit):

```json
{
  "type": "kws-cpe.run_started",
  "payload": {
    "mode": "interactive",
    "run_id": "20260516T073000Z-archive-codex-example-abcdef0-a1b2c3",
    "state_path": ".codex-orchestrator/runs/.../state.json"
  }
}
```

Emit each event with:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type kws-cpe.task_started \
    --payload-json '{"task_id":"task_2"}' \
    2>/dev/null || true
fi
```

AgentLens failure is non-blocking. Query the event stream with
`agentlens events --run "$ORCH_RUN_ID" --type 'kws-cpe.*'`.

## Redaction

Reject or redact keys matching `token`, `secret`, `password`, `api_key`,
`authorization`, `cookie`, `private_key`, or `session`.

Store paths, command names, statuses, issue keys, and short summaries. Do not
store full prompt transcripts. Do not store full command output.

## Active AgentLens Event Vocabulary

`kws-cpe.<event>` types emitted at documented boundaries:

- `kws-cpe.run_started`
- `kws-cpe.task_started` (emitted after the task contract is saved)
- `kws-cpe.task_completed`
- `kws-cpe.verification_passed`
- `kws-cpe.verification_failed`
- `kws-cpe.compaction` (phase transitions when applicable)
- `kws-cpe.blocker`
- `kws-cpe.failed`
- `kws-cpe.run_completed` (terminal `finished`)

Three are renames of the pre-cutover legacy journal vocabulary —
`task_contract_recorded → kws-cpe.task_started`, `blocked → kws-cpe.blocker`,
and `finished → kws-cpe.run_completed`. The renaming contract is encoded in
`scripts/compare_agentlens_events.py`; run

```bash
python3 scripts/compare_agentlens_events.py --self-test
```

to validate the mapping table after any change. To compare a live run, pass
the per-run dir and (optional) historical legacy streams:

```bash
python3 scripts/compare_agentlens_events.py \
  --journal .codex-orchestrator/runs/<run_id>/events.jsonl \
  --learning ~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/events.jsonl \
  <agentlens_run_dir>
```

`agentlens events --run "$ORCH_RUN_ID" --type 'kws-cpe.*'` is the canonical
query for the project-level stream;
`agentlens events --run "$ORCH_RUN_ID" --type 'kws-cpe.learning.*'` queries
the learning stream.

## Parent Propagation

Open the AgentLens orchestration run at execution init with `agentlens
run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS" --meta
plan=...` and persist the returned id as the run-level
`agentlens_orchestration_run` field of
`.codex-orchestrator/runs/<run_id>/state.json`. Headless `codex exec` spawns
must propagate the parent id with `AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`.
AgentLens failures are never blocking; an empty `ORCH_RUN_ID` silently no-ops
every guarded emit.
