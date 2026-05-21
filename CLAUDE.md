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
- Do not let subagents write Lens events directly. Waygent owns candidate-drain
  and event emission.
- Do not route active Lens work into `components/agentlens`; that Python tree is
  legacy and scheduled for deletion after explicit blocker resolution.
- Keep Claude runtime files under `.claude/` out of git.
- If a task asks for execution through Waygent, invoke `waygent` through
  `apps/cli/src/index.ts` or the installed `waygent` command rather than
  coordinating worker prompts manually.
- If a task asks for plan execution through the KWS Claude executor, use
  `skills/kws-claude-multi-agent-executor/SKILL.md` as the contract.

## Useful Checks

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
cd apps/console && bun test src && bun run build
cd native/kernel && cargo test --workspace
cd skills/kws-claude-multi-agent-executor && ./evals/run.sh
git diff --check
```

Use narrower checks when they prove the change more directly.
