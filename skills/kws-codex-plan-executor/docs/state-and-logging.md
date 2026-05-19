# State And Logging

State lives at `~/.codex/orchestrator/<run_id>/state.json`.

Execution artifacts live beside it:

- `context.json`
- `hooks/`
- `learning_events/`
- raw verification evidence
- headless result files

AgentLens events are best-effort. They never replace state and never block
implementation.
