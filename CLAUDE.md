# CLAUDE.md - Archive

Claude Code should treat `AGENTS.md` as the primary repository instruction
file. This file adds Claude-specific routing and reminders.

## Start Here

1. Read `AGENTS.md`.
2. Read the nearest subtree `AGENTS.md` when working under `skills/`.
3. Read the target `SKILL.md` before changing any executor skill behavior.

## Claude-Specific Notes

- For `skills/kws-claude-multi-agent-executor/`, follow its local
  `AGENTS.md` before substantive work. Non-trivial changes may require an
  experiment record under `docs/experiments/`.
- Do not let subagents write AgentLens directly. The Waygent/AgentRunway
  orchestrator owns candidate-drain and AgentLens emission.
- Keep Claude runtime files under `.claude/` out of git.
- If a task asks for execution through AgentRunway, invoke the runner through
  `skills/agent-runway/scripts/agentrunway.py` or the installed `agentrunway`
  command rather than coordinating worker prompts manually.
- If a task asks for plan execution through the KWS Claude executor, use
  `skills/kws-claude-multi-agent-executor/SKILL.md` as the contract.

## Useful Checks

```bash
cd components/agentlens && python -m pytest -q
cd apps/console && bun test src && bun run build
cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
cd skills/kws-claude-multi-agent-executor && ./evals/run.sh
git diff --check
```

Use narrower checks when they prove the change more directly.
