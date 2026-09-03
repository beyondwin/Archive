# CLAUDE.md - Archive

Read `AGENTS.md` first. This file only adds Claude-specific notes.

## Start

1. `AGENTS.md`
2. Nearest subtree `AGENTS.md`

## Notes

- Subagents do not write Lens events. Waygent owns drain and emission.
- Do not recreate `components/agentlens`.
- Keep `.claude/` out of git.
- For a Waygent run, use `apps/cli/src/index.ts` or the installed `waygent`
  command. Do not coordinate workers from chat.

## Checks

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
cd apps/console && bun test src && bun run build
cd native/kernel && cargo test --workspace
```

Use the smallest check that proves the change.
