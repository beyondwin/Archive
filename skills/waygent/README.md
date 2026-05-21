# Waygent Skill

Waygent is the active product skill for running local agent executions. The
skill is intentionally thin: it maps natural language to `waygent` CLI commands
and lets the runtime own state, scheduling, providers, verification, AgentLens
events, resume, and apply.

KWS executor skills may remain in this repository, but they are outside the
Waygent product boundary.

## Invocation Boundary

When this skill is explicitly invoked and the user asks to implement a plan,
execute multi-agent work, or run work from a design/plan pair, use `waygent run`
instead of host-managed workers. The Waygent runtime is responsible for
creating run state, worker worktrees, provider attempts, checkpoints, and
AgentLens events.

Do not replace a Waygent run with host `spawn_agent` calls or direct file edits.
If no `waygent run` occurs, no Waygent worktree will be created.

In the Codex app or Codex CLI, `waygent run` defaults to the Codex provider and
`multi-agent` execution when no provider or execution mode is specified. For a
repo-local invocation that does not depend on PATH setup, use
`bun run waygent -- run ...`.

## Host-Agent Model Policy

When Codex is asked to implement, review, or coordinate Waygent runtime work
from a plan or design, use extra-high reasoning for the main coordinating agent
when the host supports it. If a valid Waygent runtime execution or explicit
post-run review step creates implementation, review, or verification subagents,
prefer GPT-5.5 with high reasoning when explicit subagent model settings are
available.

If the host cannot change those settings, say so and use the strongest
available configuration. This is a host-agent execution preference only; it
does not make Waygent depend on KWS executor skills, authorize host
`spawn_agent` as the implementation path, or allow bypassing the Waygent
CLI/runtime boundary.

## Common Commands

```bash
waygent run --latest
bun run waygent -- run --latest
waygent run --plan docs/migration/example.md --provider fake
waygent run --plan docs/migration/example-plan.md --spec docs/architecture/example-design.md --provider codex --execution-mode multi-agent
waygent status --last
waygent events --run run_example --json
waygent inspect --run run_example --json
waygent explain --last
waygent resume --last
waygent apply --run run_example
```

`waygent demo` is offline-only and rejects live providers. Use `waygent run`
for Codex or Claude execution.

## Verification Commands

```bash
skills/waygent/evals/run.sh
bun run waygent:scenarios
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

The scenario gate is offline and deterministic. Live provider smoke is opt-in
and should remain skipped unless the selected provider CLI is installed and
authenticated.

## Stop Rules

- If a run selection is ambiguous, ask for a plan path or run id.
- If apply reports `dirty_source_checkout`, report the blocker and stop.
- If verification fails, run `waygent explain --last` before `waygent resume --last`.
- If apply reports no verified checkpoint, do not apply or retry from chat.
- Completed runs must have manifest-backed checkpoint artifacts before apply.
- `waygent resume --last` is the source of truth for whether apply is
  currently allowed.
- Missing or corrupted checkpoint artifacts require inspection or checkpoint
  regeneration; chat should not invent a patch or bypass the run state.
- If `WAYGENT_LIVE_PROVIDER` is set but the provider CLI is unavailable, fall
  back to the offline scenario gate.
