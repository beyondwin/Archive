# Codex best loop

Use Waygent, not CPE, host subagents, or chat-managed worker loops:

```bash
bun run waygent -- run \
  --plan docs/superpowers/plans/<implementation-plan>.md \
  --spec docs/superpowers/specs/<design>.md \
  --profile max-quality
```

In a Codex host this is Codex provider + `multi-agent`. `--profile max-quality`
means:

| Setting | Value |
| --- | --- |
| main model | `gpt-5.5` / `xhigh` |
| implement / review / verify / repair | `gpt-5.5` / `high` |
| plan preflight | `full` |
| spec slicing | `manifest` |
| hooks | `builtin` |
| method evidence | required |

Waygent already owns the task graph, worktrees, file claims, preflight,
packets, verify, checkpoints, completion audit, and apply. Import the
discipline from Superpowers / Spec Kit style workflows; do not replace the
runtime with them.

## Variants

```bash
# offline rehearsal
bun run waygent -- run --provider fake --plan <plan.md> --spec <design.md>

# skip full preflight while debugging a malformed plan
bun run waygent -- run --plan <plan.md> --profile max-quality --plan-preflight off

# turn off spec slicing only if slicing itself looks wrong
bun run waygent -- run --plan <plan.md> --spec <design.md> --profile max-quality --spec-slice off
```

## Closeout

```bash
bun run waygent -- explain --last
bun run waygent -- review --last
bun run waygent -- resume --last
bun run waygent -- apply --last
```

Do not apply worker patches from chat.
