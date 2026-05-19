# History

## 2.20.0 - 2026-05-19

- Changed the CPE default back to `subagents=on`; `subagents=off` remains
  local-only and `subagents=auto` remains the conservative explicit-request
  mode.
- Added context-intelligence artifacts: spec manifests, task packets,
  decisions register rendering, and packet-aware context snapshots.
- Added deterministic invocation parsing for key/value args and Korean/English
  natural-language hints.
- Added read-only local environment preflight and stale-run inspection.
- Extended state validation for v2.20 packet, timing, warning, decision, and
  compaction fields while preserving v2.19 state compatibility.
- Constrained opt-in subagent dispatch to task packets with parent post-diff
  and state review.
- Updated headless result output with context artifact paths and wired
  deterministic prompt/execution fixture runners into the harness so evals do
  not depend on nested `codex exec` model calls.

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
