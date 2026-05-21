# AgentLens Architecture

## Role In Waygent

AgentLens observes and evaluates Waygent evidence. Waygent owns active
scheduling, provider execution, verification, recovery, and apply readiness.

AgentLens is the component for recording, querying, evaluating, and visualizing
agent-run evidence. It gives operators replayable context without becoming the
runtime scheduler.

## Durable Artifacts

Filesystem JSON artifacts remain the durable source for run evidence. SQLite
indexes are rebuildable caches. AgentLens keeps local state under
`~/.agentlens/` or `$AGENTLENS_HOME`; workspace-local `.agentlens/` directories
are runtime pointers and must not be committed.

## Projections

Lens projections summarize timelines, trust signals, failures, artifact health,
and apply evidence for API and console surfaces. Projections should be
rebuildable from events, run state, and artifact files.

## Evaluation And Trust

AgentLens evaluates evidence quality, missing finalization, residual risk,
schema drift, failure patterns, and trust reports. It can report blockers and
confidence, but Waygent runtime state decides whether a run can resume or
apply.

## Boundaries

AgentLens must not be framed as the active scheduler, provider runner, or apply
readiness owner. It stores and evaluates evidence emitted or owned by Waygent.
