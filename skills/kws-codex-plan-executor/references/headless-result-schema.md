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
- `context_artifacts`
- `next_action`

For `status=blocked`, the payload also includes `blocker` with category,
summary, recoverability, and next action kind. For `status=failed`, the payload
includes `failure_decision` with the machine decision and reason.

The machine-readable schema lives at `templates/headless-output-schema.json`.
