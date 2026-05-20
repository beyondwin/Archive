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

## Invocation Shortcuts

The internal Python script remains supported, but normal use should go through
the short resolver forms:

```bash
agentrunway run --topic <topic> --adapter codex
agentrunway run --latest --adapter claude
agentrunway status --last
agentrunway inspect --last --json
agentrunway apply --last
```

`--topic` resolves a complete Superpowers design/plan pair under
`docs/superpowers/specs/` and `docs/superpowers/plans/`. Ambiguous topics fail
before dispatch and print candidates. `--last` is scoped to the current
workspace id, not the whole machine.

## Operations Evidence

Every non-planning run writes a frozen `contract.json`, `artifact_graph.json`,
`coverage.json`, and `events.jsonl` under `~/.agentrunway/runs/<workspace>/<run_id>/`.
The contract records the exact Superpowers spec and plan paths, hashes, parsed
tasks, file claims, acceptance commands, adapter, model profile, and `spec_refs`
coverage.

Use:

```bash
python3 skills/agent-runway/scripts/agentrunway.py status --run <run_id>
python3 skills/agent-runway/scripts/agentrunway.py inspect --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py events --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py resume --run <run_id> --dry-run --json
```

AgentLens emission is best-effort. Local evidence remains authoritative when
AgentLens is disabled or unavailable.

## Production Supervisor

`agentrunway run --adapter codex` and `agentrunway run --adapter claude` launch worker
processes through the production supervisor. The runner creates worker worktrees,
writes task packets and prompts, supervises process lifecycle, collects
`worker_result.json`, validates committed changed files against file claims,
runs `review_result` and `verification_result` gates, and cherry-picks accepted
commits into the run main worktree.

Reviewer `changes_requested` and verifier `failed` outcomes create one bounded
implementer redispatch with the gate evidence threaded into the next prompt.
The previous candidate remains in the merge queue with a non-mergeable status;
only a later verifier `passed` outcome can promote a fresh candidate to
`merge_ready`.

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

Graphify navigation remains a generated project layer. Completion evidence
should record the `graphify update .` command result rather than checking
`graphify-out/` into this skill package.
