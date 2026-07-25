# Changelog

## 2.0.0 - 2026-07-25

- Publishes the thin Superpowers boundary: specifications and plans are
  immutable inputs handed unchanged to Superpowers; Superpowers owns task
  decomposition, SDD dispatch, TDD, task review, fixes, and the final
  whole-branch review.
- Limits runner ownership to exact external facts.
- Starts every plan with a fresh root, with one healthy root resume and one
  fresh-root fallback.
- Makes the final plan carry all immutable requirements and own the single
  final whole-branch review.
- Sets `integration_policy=keep` and keeps integration unperformed.
- Defines dirty checkpoints as drift detection, not backups; they cannot
  restore files.
- Persists the current provider process-group identity on each root attempt so
  interruption canaries bind SIGINT evidence to the live attempt.
- Binds final receipts to the complete command, executable, environment,
  candidate, and worktree identity.
- Adds provider-backed `ownership` and `interruption` canaries for the
  `2.0.0` release gate.
- Version 1 state is inspect-only. Active execution requires Version 2.

## 1.0.0 - 2026-07-23

- Initial greenfield Claude plan-runner release.
- Adds ordered multi-spec/multi-plan execution, durable session-aware recovery,
  parent-owned exact verification, and candidate-HEAD final review.
- Uses an independent uv-managed CPython 3.13 runtime.
- This release does not claim compatibility with legacy run state.
