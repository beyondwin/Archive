# kws-agent-orchestrator

`kws-agent-orchestrator` (`kao`) executes approved Superpowers plans through a deterministic Python runner.

Source of truth:

- Design: `docs/superpowers/specs/2026-05-20-kws-agent-orchestrator-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-20-kws-agent-orchestrator.md`

The runner stores state in SQLite under `~/.kao/runs`, does implementation work in isolated git worktrees under `~/.kao/worktrees`, and emits bounded AgentLens events under the `kws.kao.*` namespace. The MVP includes a deterministic local adapter for tests and dry runs plus Claude/Codex process adapter wrappers.

## Quick Start

```bash
python3 skills/kws-agent-orchestrator/scripts/kao.py run --plan plan.md --spec spec.md --planning-only
python3 skills/kws-agent-orchestrator/scripts/kao.py status --run <run_id>
```

Use `--adapter local --fake-success` for deterministic end-to-end smoke runs without model calls.
