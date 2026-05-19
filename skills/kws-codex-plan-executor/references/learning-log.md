# Learning Log

Learning events are execution-only. `interactive` and `headless` runs may emit
redacted notable-boundary events to AgentLens under
`kws-cpe.learning.<event>`. `prompt` and `handoff` are not logging modes.

Use this lifecycle:

```bash
ORCH_RUN_ID="$(agentlens run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS" --meta plan="$PLAN_PATH" 2>/dev/null || true)"
[ -n "${ORCH_RUN_ID:-}" ] && agentlens event append --run "$ORCH_RUN_ID" --type "kws-cpe.learning.${EVENT_TYPE}" --payload-json "$PAYLOAD" 2>/dev/null || true
[ -n "${ORCH_RUN_ID:-}" ] && agentlens run-close --run "$ORCH_RUN_ID" --outcome "$OUTCOME" 2>/dev/null || true
```

Payloads include `run_id`, `run_dir`, `state_path`, and a redacted-context
summary. Store run state at `~/.codex/orchestrator/<run_id>/state.json`.

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
