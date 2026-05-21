# AgentLens Documentation

## Role In Waygent

AgentLens records, queries, evaluates, and visualizes agent-run evidence.
Waygent owns active scheduling, provider execution, verification, recovery, and
apply readiness.

Inside Waygent, AgentLens is the observability and evaluation component. It
should not be treated as the scheduler, provider runner, or owner of apply
readiness.

## Durable State

Filesystem JSON artifacts are the durable source of truth. SQLite indexes are
rebuildable caches. AgentLens state belongs under `~/.agentlens/` or
`$AGENTLENS_HOME`; workspace-local `.agentlens/` directories are runtime state
and must stay out of git.

## CLI And Dashboard

- [CLI](./cli.md)
- [Dashboard](./dashboard.md)

The CLI and dashboard expose run evidence, timelines, failures, risks, and
trust projections for operators and reviewers.

## Security

- [Security](./security.md)

AgentLens docs and tooling should preserve local-state boundaries, redact
sensitive evidence where appropriate, and avoid committing runtime artifacts or
full transcripts.

## Related Waygent Docs

- [Waygent architecture](../../../docs/architecture/waygent.md)
- [AgentLens architecture](../../../docs/architecture/agentlens.md)
- [Waygent operations](../../../docs/operations/waygent.md)
- [Event contracts](../../../docs/contracts/events.md)
