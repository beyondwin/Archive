# History

## Unreleased

- Tightened state validation so finished runs must record a concrete
  `timestamps.completed_at` ISO timestamp.
- Tightened state validation so `current_task` must reference an existing task
  whenever the run state has task records.
- Changed context snapshot budgeting for task-packet runs so budget status is
  based on the largest packet instead of oversized source plan/spec sections,
  while preserving summed packet estimates for auditability.
- Added `--context-threshold` support to context snapshot generation so tuned
  invocation settings apply consistently beyond task packet construction.
- Aligned task packet `--context-threshold` validation with the invocation
  contract's `[0.05,0.95]` range.
- Added execution hardening for prompt cache boundaries, optional cache
  observations, Graphify freshness audits, and deterministic subagent
  pre-dispatch decisions.
- Changed the default `subagents=on` behavior from permission-only to
  subagent-first execution for eligible write-capable tasks, with task-level
  `subagent_strategy` audit records for delegated and local-fallback outcomes.
- Added parser support for fenced `yaml waygent-task` and
  `yaml agentrunway-task` execution contracts, including file claims and
  dependencies.
- Added execution guardrails for resolving local skill paths from the active
  registry/root mapping instead of hard-coded roots.
- Added graphify freshness guidance: compare `GRAPH_REPORT.md` built commit
  with `git rev-parse HEAD`, run `graphify update .` after code changes, and
  record the evidence in completion audit.
- Added CPE subagent quality controls: phase-plan acceptance parsing,
  component-level task packet budgets, spec mapping signals, decision
  filtering, acceptance/unit manifests, packet-quality preflight gates,
  structured blocker/failure state, recovery policy classification, trajectory
  projection, progress ledger updates, and richer run inspection output.
- Tightened headless result and state validation so blocked/failed runs expose
  structured blocker or failure decisions and finished runs cannot hide open
  blockers, open recovery attempts, or unacknowledged unknown observations.

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
