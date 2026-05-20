---
name: kws-agent-orchestrator
description: Execute approved implementation plans through the deterministic KAO Python runner with isolated worktrees, runtime adapters, review/verification gates, and AgentLens `kws.kao.*` observability.
---

# KWS Agent Orchestrator

Use this skill when the user asks to execute an approved plan/spec through KAO or explicitly invokes `kws-agent-orchestrator`.

## Required Bootstrap

1. Invoke/read `using-superpowers` before doing anything else.
2. Confirm the user supplied `plan=<path>` and optional `spec=<path>`.
3. Shell out to `scripts/kao.py`; do not orchestrate workers from conversation context.

## Invocation

```bash
python3 skills/kws-agent-orchestrator/scripts/kao.py run --plan <plan.md> --spec <spec.md>
```

The runner owns scheduling, state, worktrees, runtime adapters, review, verification, merge queue, and AgentLens emission. The host session surfaces the runner summary and uses `kao status --run <run_id>` for follow-up visibility.
