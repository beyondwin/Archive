# History

## 2.23.0 - Unreleased

- Added `scripts/repair_runs.py` for dry-run CPE repair planning and explicit
  single-run `mark-blocked-stale` apply.
- Added deterministic repair-flow eval coverage in `evals/check_repair_runs.py`.
- Documented the stale blocked repair state fields and non-deletion safety
  boundary.
- Added a deterministic Superpowers compatibility audit that scores CPE-primary,
  Superpowers-native-only, and thin-stateful-bridge routes.
- Updated interactive routing guidance so approved implementation plans prefer
  the current Superpowers execution loop when the audit recommends
  `thin_stateful_bridge`, while CPE retains state, prompt/handoff, headless,
  resume, inspection, and audit ownership.
- Added run readiness auditing before execution edits.
- Added deterministic repair hints for comma-joined write scopes in run
  readiness output.
- Preserved acceptance source metadata in task packets.
- Tightened finished-state validation for dispatch and final subagent strategy
  consistency.
- Tightened finished-state validation so `graphify_audit` must be referenced
  from `completion_audit.verification_evidence`.
- Expanded run quality schema for readiness, context quality, dispatch
  consistency, and verification quality.
- Expanded read-only run inspection quality summaries with actionable
  follow-ups for stale non-terminal runs and missing execution worktrees.
- Added adaptive dispatch policy evidence so `subagents=on` delegates only when
  the task is safe and delegation has value.
- Added local fast path reasons for small docs-only, small-scope, linear, and
  low-parallel-value tasks while preserving task contract, diff review,
  acceptance, reconciliation, and state validation gates.
- Extended state validation and deterministic evals for adaptive local fast
  path, delegate, and block outcomes.
- Changed `evals/run.sh` so default verification compares against the tracked
  baseline without rewriting it; intentional baseline updates now require
  `--update-baseline`, and focused fixture updates preserve unexecuted fixture
  entries.
- Extracted eval baseline compare and subset merge semantics into a direct
  helper with deterministic coverage.

## 2.22.0 - 2026-06-09

- Added explicit delegation intent parsing so default `subagents=on` is not
  confused with a user delegation request.
- Added deterministic dispatch policy fallback evidence for spawn policies that
  require explicit user delegation intent.
- Expanded local environment preflight with package-manager bootstrap
  suggestions and environment capability detection.
- Added optional v2.22 state validation for `execution_worktree`,
  `command_cwd_evidence`, `delegation_policy`, `preflight_bootstrap`, and
  `run_quality`.
- Extended run inspection with all-plan recent quality reports, stale-run
  summaries, validation drift, JSONL output, and delegation/local-fallback
  counters.
- Updated static execution fixtures and eval coverage to emit operational run
  quality fields.

## 2.21.0 - 2026-05-31

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
- Fixed plan parsing for machine-readable implementation docs that use `Eval:`
  verification sections, multi-line acceptance command blocks, and Korean
  `새 파일 ...` file-scope bullets.

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
