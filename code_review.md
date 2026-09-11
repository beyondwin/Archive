# Code review

Read `AGENTS.md` and the nearest subtree `AGENTS.md` first. Lead with concrete
findings and file refs.

## Look for

- Correctness against the requested behavior
- Regression risk: CLI, schemas, workflows, runtime state
- Checks: `bun run agent:verify` ran, with exact results and skipped
  optional checks
- Scope: no unrelated refactors, generated files, caches, or local runtime
  artifacts
- Secrets, transcripts, credentials, screenshots, sensitive local paths
- For Lens/Waygent: saved files, event schemas, non-blocking behavior

## Lens

- JSON is the saved record; SQLite is a cache you can rebuild
- Internal Lens failures must not change the wrapped command's exit code
- Schema changes are additive unless a versioned migration is designed
- Dashboard/API type drift: `bun run typecheck` plus contract, view, and
  consumer tests when relevant

## Runtime

- Providers do not write SQLite or Lens directly
- Scheduler changes respect safe task groups, dependency checkpoints, and
  failure barriers
- Recovery stops on missing handlers or human-decision classes. No fake
  progress.
- Behavior changes need targeted tests or scenario coverage

## Docs

- Local Markdown targets resolve without the network
- Required live proof stays optional and is reported separately

## Output

1. Findings first, by severity
2. File and line refs
3. Open questions
4. Short check summary

If there are no findings, say so, and name leftover risk.
