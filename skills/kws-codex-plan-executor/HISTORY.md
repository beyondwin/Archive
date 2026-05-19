# History

## 2.19.1 - 2026-05-19

- Changed `subagents` default to `auto`; subagent spawning now requires an
  explicit user request or `subagents=on`.
- Fixed AgentLens outcome mapping and redacted run identity payload guidance.
- Made `reconcile_state.py --check` non-mutating.
- Tightened state validation for delegated owner tasks, write scopes, changed
  files, active overlaps, and write-capable unit manifests.
- Tightened eval harness checks for fixture failure propagation, isolated state
  homes, and headless sandbox mapping.
- Added parser task/file line numbers and broadened task/dependency heading
  aliases for better diagnostics.

## 2.19.0 - 2026-05-19

- Moved execution code worktrees to `~/.codex/worktrees/<plan-slug>-YYYYMMDD-HHMMSS`.
- Moved orchestration state and runtime artifacts to
  `~/.codex/orchestrator/<plan-slug>-YYYYMMDD-HHMMSS`.
- Changed subagents to default on; `subagents=off` now selects local-only
  execution.
- Removed retired local replay and learning helpers from the active contract.
- Tightened deterministic evals around path separation and legacy rejection.
