---
name: agent-runway
description: Execute approved implementation plans through the deterministic AgentRunway Python runner with isolated worktrees, runtime adapters, review/verification gates, and AgentLens `agentrunway.*` observability.
---

# AgentRunway

Use this skill when the user asks to execute an approved plan/spec through AgentRunway or explicitly invokes `agent-runway`.

## Required Bootstrap

1. Invoke/read `using-superpowers` before doing anything else.
2. Accept either:
   - `plan=<path>` with optional `spec=<path>`, or
   - `topic=<topic>`, or
   - `run_id=<run_id>` / `last` for status, inspect, resume, cancel, or apply.
3. If the user gives only natural language and no clear `plan`, `topic`, `run_id`, or `last`, ask for one concise clarification.
4. Shell out to `scripts/agentrunway.py`; do not orchestrate workers from conversation context.

## Invocation

```bash
python3 skills/agent-runway/scripts/agentrunway.py run --plan <plan.md> --spec <spec.md>
```

```text
agent-runway topic=agent-runway-operations-hardening adapter=codex 로 실행해줘
agent-runway plan=docs/superpowers/plans/example.md spec=docs/superpowers/specs/example-design.md adapter=claude 로 실행해줘
agent-runway last 상태 확인해줘
```

The runner owns scheduling, state, worktrees, runtime adapters, review, verification, merge queue, and AgentLens emission. The host session surfaces the runner summary and uses `agentrunway status --run <run_id>` for follow-up visibility.
