# Changelog

## 1.1.0 - 2026-07-25

- Defines the runner as a thin wrapper and strategic recovery shell around the
  public Superpowers v6.2.0 `subagent-driven-development` capabilities rather
  than a second task database.
- Preserves the effective `CODEX_HOME` while applying `--ignore-user-config`,
  `--ignore-rules`, strict config, `approval_policy="never"`, and the selected
  `danger-full-access` or workspace sandbox consistently to initial and resumed
  Codex sessions.
- Adds checkpoint-before-result handling, immutable Git identity, root-result
  validation, serialized `matching_run_exists` admission, and narrow volatile
  handling for the two Codex turn-diff ref prefixes.
- Adds the revision-guarded `volatile-codex-turn-refs` and
  `unsealed-provider-partial` repairs and documents the host-permission
  residual boundary.
- Uses `bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD` as the
  final repository gate; live Codex canaries remain separate evidence.
- Requires every prior plan handoff HEAD to remain an ancestor of the current
  candidate and strips Git routing variables from controller and provider
  subprocesses.
- Requires recorded process-group and descendant-PID quiescence before partial
  repair, and recognizes exact structured sandbox errors without free-text
  permission matching.
- Adds audited same-run `execution_profile_transition` records for explicitly
  authorized sandbox/model changes, legacy volatile-ref drift repair guidance,
  and the `provider_capability_blocked` taxonomy entry.
- Verifies the Superpowers v6.2.0 public `sdd-workspace`, `task-brief`, and
  `review-package` helper interfaces without depending on private workspace
  layout.

## 1.0.0 - 2026-07-23

- Initial greenfield Codex plan-runner release.
- Adds ordered multi-spec/multi-plan execution, durable session-aware recovery,
  parent-owned exact verification, and candidate-HEAD final review.
- Uses an independent uv-managed CPython 3.13 runtime.
- This release does not claim compatibility with legacy run state.
