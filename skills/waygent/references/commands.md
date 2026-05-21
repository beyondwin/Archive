# Waygent Commands

```bash
waygent run --plan <path> --spec <path>
bun run waygent -- run --plan <path> --spec <path>
waygent run --plan <path> --spec <path> --provider fake
waygent run --plan <path> --provider codex --execution-mode multi-agent
waygent run --plan <path> --provider claude --execution-mode multi-agent
waygent run --latest --provider codex --execution-mode multi-agent
waygent run --topic <topic> --provider claude --main-model opus --main-reasoning high
waygent status --last
waygent status --run <run_id>
waygent events --run <run_id> --json
waygent inspect --last --json
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
```

Codex app and Codex CLI invocation default `waygent run` to Codex provider and
`multi-agent` execution. Use `--provider fake` explicitly for deterministic
test runs. `waygent demo` is offline-only and rejects live providers.

Runtime verification helpers:

```bash
bun run waygent:scenarios
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Stop rules:

- Ask for a plan path when `--latest` is ambiguous.
- Stop on ambiguous active runs; do not choose one from chat context.
- Stop when the selected live provider CLI is unavailable or unauthenticated.
- For explicit Waygent implementation requests, do not use host `spawn_agent`
  or direct file edits instead of `waygent run`; the runtime must create the
  run state and worktree data.
- Run `waygent explain --last` before `waygent resume --last` after failed
  verification.
- `apply` is explicit, must refuse `dirty_source_checkout`, and must block
  without a verified checkpoint.
