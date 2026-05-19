# Event Journal

Replay evidence is emitted to AgentLens under `kws-cpe.<event>`.

State remains authoritative at
`~/.codex/orchestrator/<run_id>/state.json`. AgentLens events are useful for
inspection and replay, but event emission is best-effort and must not block plan
execution.

Every event payload should include:

- `run_id`
- `run_dir`
- `state_path`
- `workspace`
- `worktree`
- redacted task or verification metadata

For resume, persist `agentlens_orchestration_run` and
`last_agentlens_event_at` in state when available.
