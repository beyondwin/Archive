# CLAUDE.md - Archive

Claude Code should treat `AGENTS.md` as the primary repository instruction
file. This file only adds Claude-specific notes after that canonical guidance.

## Start Here

1. Read `AGENTS.md`.
2. Read the nearest subtree `AGENTS.md` before changing a subtree.
3. Read the target `SKILL.md` before changing any executor skill behavior.

## Claude-Specific Notes

- For `skills/kws-claude-multi-agent-executor/`, follow its local
  `AGENTS.md` before substantive work. Non-trivial changes may require an
  experiment record under `docs/experiments/`.
- Do not let subagents write Lens events directly. Waygent owns candidate-drain
  and event emission.
- Do not route active Lens work into `components/agentlens`; that legacy Python
  tree has been removed from this checkout.
- Keep Claude runtime files under `.claude/` out of git.
- If a task asks for execution through Waygent, invoke `waygent` through
  `apps/cli/src/index.ts` or the installed `waygent` command rather than
  coordinating worker prompts manually.
- For sequential implementation of approved Superpowers specifications and
  plans, use `skills/kws-claude-plan-runner/SKILL.md`.
- Use `skills/kws-claude-multi-agent-executor/SKILL.md` only when the task
  specifically calls for its specialized Opus/Sonnet multi-agent workflow. It
  remains independently supported and is not the default sequential runner.

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
