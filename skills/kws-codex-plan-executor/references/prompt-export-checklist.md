# Prompt Export Checklist

- Prompt and handoff modes are export-only.
- The generated prompt names `~/.codex/worktrees/<run_id>` for code execution.
- The generated prompt names `~/.codex/orchestrator/<run_id>/state.json` for state.
- The prompt includes `context.json`, `context_snapshot_path`,
  `context_basis_hash`, `context_health`, `handoff_ready`, and `next_action`.
- The prompt includes `completion_audit`, `prompt_to_artifact_checklist`,
  `verification_evidence`, `lifecycle_outcome`, `handoff_reason`, `finished`,
  `blocked`, and `failed`.
- The prompt requires `TASK EXECUTION CONTRACT` before edits.
- The prompt states subagents default on and documents `subagents=off`.
- The prompt includes the high-risk verification matrix terms: misleading
  success, stale state, hung.
- Handoff prompts include `HANDOFF CHECKPOINT`.
- No unfilled `{{...}}` template token remains.
