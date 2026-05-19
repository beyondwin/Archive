# Headless Result Schema

Headless runs write a final JSON payload with:

- `status`
- `run_id`
- `state_path`, pointing at `~/.codex/orchestrator/<run_id>/state.json`
- `summary`
- `changed_files`
- `verification`
- `open_gaps`
- `residual_risk`
- `next_action`

The machine-readable schema lives at `templates/headless-output-schema.json`.
