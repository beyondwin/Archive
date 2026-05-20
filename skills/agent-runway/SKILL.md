---
name: agent-runway
description: Execute approved implementation plans through the deterministic AgentRunway Python runner with isolated worktrees, runtime adapters, review/verification gates, and AgentLens `agentrunway.*` observability.
---

# AgentRunway

Use this skill when the user asks to execute an approved plan/spec through AgentRunway or explicitly invokes `agent-runway`.

## Required Bootstrap

1. Invoke/read `using-superpowers` before doing anything else.
2. Confirm the user supplied `plan=<path>` and optional `spec=<path>`.
3. Shell out to `scripts/agentrunway.py`; do not orchestrate workers from conversation context.

## Invocation

```bash
python3 skills/agent-runway/scripts/agentrunway.py run --plan <plan.md> --spec <spec.md>
```

The runner owns scheduling, state, worktrees, runtime adapters, review, verification, merge queue, and AgentLens emission. The host session surfaces the runner summary and uses `agentrunway status --run <run_id>` for follow-up visibility.
