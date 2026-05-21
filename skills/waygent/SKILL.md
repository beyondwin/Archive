---
name: waygent
description: Translate natural-language Waygent run, status, explain, resume, and apply requests into stable CLI commands.
---

# Waygent

Use this skill when the user asks to run, inspect, resume, explain, or apply a
Waygent execution from natural language.

Waygent is the user-facing orchestrator. The skill is intentionally thin: it
resolves intent and calls the CLI. It must not implement scheduling, worktree
mutation, recovery policy, trust scoring, provider runtime behavior, or direct
AgentLens writes.

## Mapping

- Latest approved plan: `waygent run --latest`
- Topic run: `waygent run --topic "<topic>"`
- Provider selection: add `--provider codex|claude|fake`
- Multi-agent mode: add `--execution-mode multi-agent`
- Status: `waygent status --last`
- Explain blocked run: `waygent explain --last`
- Resume: `waygent resume --last`
- Apply accepted checkpoint: `waygent apply --last`

## Examples

```text
"최근 승인된 플랜 실행해줘"
-> waygent run --latest

"bun rust 플랫폼 계획 Codex로 멀티에이전트 실행해줘"
-> waygent run --topic "bun rust platform" --provider codex --execution-mode multi-agent

"이번엔 Claude Opus high로 돌려줘"
-> waygent run --latest --provider claude --main-model opus --main-reasoning high --subagent-model opus --subagent-reasoning high

"마지막 실행 왜 막혔는지 설명해줘"
-> waygent explain --last

"검증 통과한 것만 적용해줘"
-> waygent apply --last
```
