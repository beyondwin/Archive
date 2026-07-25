# Changelog

## 2.0.0 - 2026-07-25

- Publishes the thin Superpowers boundary: specifications and plans remain
  immutable, Superpowers owns task/review/fix meaning, and the runner owns only
  exact external facts.
- Starts every plan with a fresh root and bounds recovery to one healthy root
  resume plus one fresh-root fallback.
- Makes the final plan carry all immutable requirements and own the single
  final whole-branch review.
- Sets `integration_policy=keep`; the runner still never merges, pushes, or
  deploys and reports `integration=not_observed`.
- Clarifies that `--ignore-rules` disables Codex execpolicy rules for controlled
  provider launches.
- Defines dirty checkpoints as drift detection, not backups; they cannot
  restore files.
- Version 1 state is inspect-only. Active execution requires Version 2.

## 1.1.0 - 2026-07-25

- Introduced the thin wrapper, strategic recovery shell, checkpoint-before-
  result handling, serialized admission, volatile Codex ref repair, and
  capability-based Superpowers v6.2.0 discovery.
- Added audited `execution_profile_transition` records, protected prior-plan
  ancestry, and the repository-wide `bun run agent:verify` gate.

## 1.0.0 - 2026-07-23

- Initial greenfield Codex plan-runner release.
- Added ordered multi-spec/multi-plan execution, durable recovery, exact
  verification, and candidate-HEAD review.
- Used an independent uv-managed CPython 3.13 runtime.
- This release does not claim compatibility with legacy run state.
