# Learning Log

Learning events are execution-only. `interactive` and `headless` runs may emit
redacted notable-boundary events to AgentLens under
`kws-cpe.learning.<event>`. `prompt` and `handoff` are not logging modes.

Use this lifecycle:

```bash
ORCH_RUN_ID="$(agentlens run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS" --meta plan="$PLAN_PATH" 2>/dev/null || true)"
[ -n "${ORCH_RUN_ID:-}" ] && agentlens event append --run "$ORCH_RUN_ID" --type "kws-cpe.learning.${EVENT_TYPE}" --payload-json "$PAYLOAD" 2>/dev/null || true
[ -n "${ORCH_RUN_ID:-}" ] && agentlens run-close --run "$ORCH_RUN_ID" --outcome "$AGENTLENS_OUTCOME" 2>/dev/null || true
```

Map executor lifecycle outcomes to AgentLens outcomes before `run-close`:

- `finished -> success`
- `blocked -> partial`
- `failed -> failed`
- `cancelled -> cancelled`

Payloads include `run_id`, `run_dir_ref`, `state_path_ref`, and a
redacted-context summary. Use refs such as `~/.codex/orchestrator/<run_id>` and
`~/.codex/orchestrator/<run_id>/state.json`; do not store absolute home paths in
payload metadata. Store run state at `~/.codex/orchestrator/<run_id>/state.json`.

Record only actionable boundaries:

- `blocker`
- `error`
- `verification_failure`
- `recurring_issue`
- `user_correction`
- `successful_workaround`
- `completion_learning`

Do not store secrets. Do not store full conversation transcripts. Do not store
long raw logs or absolute home paths in event payloads.
