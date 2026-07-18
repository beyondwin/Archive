# Code Review Guide

Read `AGENTS.md` and the nearest subtree `AGENTS.md` first. This checklist is a
thin review adapter; lead with concrete findings and file references.

## Review Priorities

- Correctness: Does the change satisfy the requested behavior?
- Regression risk: Could existing workflows, schemas, CLI contracts, or runtime
  state be broken?
- Verification: Was `bun run agent:verify` run, with exact command results and
  skipped opt-in evidence reported?
- Scope control: Are unrelated refactors, generated files, caches, or local
  runtime artifacts excluded?
- Security and privacy: Are secrets, transcripts, credentials, screenshots, or
  sensitive local paths avoided?
- Observability: For AgentLens/Waygent changes, are durable artifacts,
  event schemas, and non-blocking behavior preserved?

## AgentLens Checks

- JSON artifacts remain the source of truth; SQLite stays a rebuildable cache.
- AgentLens internal failures must not change the wrapped command exit code.
- Schema changes are additive unless a versioned migration is explicitly
  designed.
- Dashboard/API type drift is checked with `bun run typecheck` plus targeted
  contract, projector, and consumer tests when relevant.

## Waygent Runtime Checks

- Providers do not write SQLite or AgentLens directly.
- Scheduler changes respect safe waves, dependency checkpoints, and failure
  barriers.
- Recovery paths stop on missing handlers or human-decision classes instead of
  recording fake progress.
- Runtime behavior changes include targeted tests or scenario harness coverage.

## Documentation Checks

- Local Markdown targets resolve without network access.
- Explicitly required live evidence stays opt-in and is reported separately
  from deterministic offline verification.

## Output Format

For review responses:

1. Findings first, ordered by severity.
2. File and line references when possible.
3. Open questions or assumptions.
4. Short verification summary.

If there are no findings, say that directly and mention any residual risk.
