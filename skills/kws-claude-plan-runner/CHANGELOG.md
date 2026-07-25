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
- Version 1 state is inspect-only. Active execution requires Version 2.

## 1.0.0 - 2026-07-23

- Initial greenfield Claude plan-runner release.
- Added ordered multi-spec/multi-plan execution, durable recovery, exact
  verification, and candidate-HEAD review.
- Used an independent uv-managed CPython 3.13 runtime.
- This release does not claim compatibility with legacy run state.
