# agent-runway

`agent-runway` (`agentrunway`) executes approved Superpowers plans through a deterministic Python runner.

Source of truth:

- Design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-20-agent-runway.md`

The runner stores state in SQLite under `~/.agentrunway/runs`, does implementation work in isolated git worktrees under `~/.agentrunway/worktrees`, and emits bounded AgentLens events under the `agentrunway.*` namespace. The MVP includes a deterministic local adapter for tests and dry runs plus Claude/Codex process adapter wrappers.

## Quick Start

```bash
python3 skills/agent-runway/scripts/agentrunway.py run --plan plan.md --spec spec.md --planning-only
python3 skills/agent-runway/scripts/agentrunway.py status --run <run_id>
```

Use `--adapter local --fake-success` for deterministic end-to-end smoke runs without model calls.

## Production Supervisor

`agentrunway run --adapter codex` and `agentrunway run --adapter claude` launch worker
processes through the production supervisor. The runner creates worker worktrees,
writes task packets and prompts, supervises process lifecycle, collects
`worker_result.json`, validates committed changed files against file claims,
runs `review_result` and `verification_result` gates, and cherry-picks accepted
commits into the run main worktree.

Use fake CLI fixtures for deterministic tests:

```bash
PATH="$PWD/evals/fixtures/fake-bin:$PATH" ./evals/run.sh
```

Use real Codex/Claude smoke runs only when the local CLIs are authenticated and
model usage is intended. AgentLens emission is best-effort; runner state and
local event artifacts remain authoritative.

`agentrunway apply --run <run_id>` is explicit. It refuses a dirty source
checkout by default and records applied commits in SQLite. Merge conflict
handling aborts the cherry-pick and records the candidate state for retry or
operator review.
