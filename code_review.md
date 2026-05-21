# Code Review Guide

Use this checklist when reviewing local changes, PRs, commits, or agent output.
Lead with concrete findings and file references.

## Review Priorities

- Correctness: Does the change satisfy the requested behavior?
- Regression risk: Could existing workflows, schemas, CLI contracts, or runtime
  state be broken?
- Verification: Are tests, lint, build, or honest substitutes run and reported?
- Scope control: Are unrelated refactors, generated files, caches, or local
  runtime artifacts excluded?
- Security and privacy: Are secrets, transcripts, credentials, screenshots, or
  sensitive local paths avoided?
- Observability: For AgentLens/AgentRunway changes, are durable artifacts,
  event schemas, and non-blocking behavior preserved?

## AgentLens Checks

- JSON artifacts remain the source of truth; SQLite stays a rebuildable cache.
- AgentLens internal failures must not change the wrapped command exit code.
- Schema changes are additive unless a versioned migration is explicitly
  designed.
- Dashboard/API type drift is checked with `npm run gen-types` when relevant.

## AgentRunway Checks

- Workers do not write SQLite or AgentLens directly.
- Scheduler changes respect safe waves, dependency checkpoints, and failure
  barriers.
- Recovery paths stop on missing handlers or human-decision classes instead of
  recording fake progress.
- Runner behavior changes include targeted tests or deterministic evals.

## Output Format

For review responses:

1. Findings first, ordered by severity.
2. File and line references when possible.
3. Open questions or assumptions.
4. Short verification summary.

If there are no findings, say that directly and mention any residual risk.
