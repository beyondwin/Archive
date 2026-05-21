---
name: waygent
description: Translate natural-language Waygent run, status, explain, resume, and apply requests into stable CLI commands.
---

# Waygent

Use this skill when the user asks to run, inspect, resume, explain, or apply a
Waygent execution from natural language.

Waygent is the product runtime. This skill translates operator intent into the
`waygent` CLI and then reports the command outcome. It must not implement
scheduling, provider execution, worktree mutation, trust scoring, or direct
AgentLens writes.

Hard boundaries:

- Waygent must not call `skills/kws-codex-plan-executor`.
- Waygent must not call `skills/kws-claude-multi-agent-executor`.
- KWS executor skills are not Waygent product dependencies.
- New Waygent runs use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`
  event families.

Default mappings:

- "최근 승인된 플랜 실행해줘" -> `waygent run --latest`
- "상태 보여줘" -> `waygent status --last`
- "이벤트 보여줘" -> `waygent events --run <run_id> --json`
- "자세히 검사해줘" -> `waygent inspect --run <run_id> --json`
- "왜 막혔어?" -> `waygent explain --last`
- "재개해줘" -> `waygent resume --last`
- "검증 통과한 것만 적용해줘" -> `waygent apply --run <run_id>`

Stop rules:

- If the plan is missing or `--latest` is ambiguous, ask for the plan path.
- If apply reports `dirty_source_checkout`, report the blocker and do not retry.
- If verification fails, use `waygent explain --last` before resume.
