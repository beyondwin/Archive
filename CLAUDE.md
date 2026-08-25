# CLAUDE.md - Archive

Claude Code should treat `AGENTS.md` as the primary repository instruction
file. This file only adds Claude-specific notes after that canonical guidance.

## Start Here

1. Read `AGENTS.md`.
2. Read the nearest subtree `AGENTS.md` before changing a subtree.
3. Read the target skill's `SKILL.md` before changing that skill.

## Claude-Specific Notes

- If the user names the legacy executor tree, follow
  `skills/_legacy/kws-claude-multi-agent-executor/AGENTS.md`.
- Do not let subagents write Lens events directly. Waygent owns candidate-drain
  and event emission.
- Do not route active Lens work into `components/agentlens`; that legacy Python
  tree has been removed from this checkout.
- Keep Claude runtime files under `.claude/` out of git.
- If a task asks for execution through Waygent, invoke `waygent` through
  `apps/cli/src/index.ts` or the installed `waygent` command rather than
  coordinating worker prompts manually.

## Useful Checks

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
cd apps/console && bun test src && bun run build
cd native/kernel && cargo test --workspace
cd skills/_legacy/kws-claude-multi-agent-executor && ./evals/run.sh
git diff --check
```

The MAE eval is opt-in, not default routing. Use narrower checks when they
prove the change more directly.
