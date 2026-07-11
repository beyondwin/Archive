# History

## Unreleased

- 2026-07-11: Aligned active documentation with the integrity-closure runtime:
  seven focused owners, immutable packet/digest consumption by every role,
  measured Git revisions, canonical integrity/completion profiles, explicit
  retry and repair semantics, machine-readable public exits, and the maintained
  public-CLI behavior harness. Historical experiment entries below remain
  descriptions of their release and are not active executable guidance.
- 2026-07-10: Corrected the 3.0.0 release claim to
  `integrity-closure-pending; paid-live-pending`. This is an evidence
  correction while audited fail-closed gaps are closed, not an architectural
  rollback from the event-sourced v3 runtime.

## 3.0.0 - 2026-07-10 (integrity-closure-pending; paid-live-pending)

- Replaced mutable v2 execution surfaces with v3 manifest, evidence, event,
  projection, validation, reconciliation, repair, inspection, and fixed model routing.
- Added reproducible dependency reporting and deterministic migration dry-run evidence.
- Added a cost-free, injectable 4x8 migration aggregator with an enforced
  `$50.00` cap. Paid live execution still requires explicit approval and a
  passing report before release closeout.

## 2.27.0 - 2026-07-05

- Split recent-run operational-quality followups into actionable and
  informational taxonomy while keeping durable state grades limited to
  `green`, `yellow`, and `red`.
- Added report-level `green-with-info` for completion-passed runs that only
  have informational followups.
- Recorded advisory would-have dispatch evidence when spawn policy prevents
  actual delegation, without changing final dispatch decisions.
- Added deterministic packet-owned next-action guidance for full-spec fallback
  context debt.

## 2.26.0 - 2026-07-04

- Added recent-run operational-quality rubric reporting with
  `scripts/analyze_recent_runs.py`.
- Added full-spec fallback diagnosis fields for task packets, readiness audits,
  and plan executability audits.
- Added run-level delegation capability evidence and AgentLens status
  classification.
- Extended normalized replay and deterministic eval coverage for prompt,
  Graphify, AgentLens, and delegation capability status.
- Added validator modular parity coverage and routed the public state validator
  through `cpe_state_validation` domain modules while preserving CLI behavior.

## 2.25.1 - 2026-07-03

- Fixed plan executability audit blocker reasons so blocked tasks report the
  real blocking issue instead of stale adaptive local-fast-path reasons.
- Added current Superpowers plan support classification:
  `current_superpowers_compatible`, `cpe_fixable_metadata`,
  `operator_review_required`, and `blocked_unsupported_plan_shape`.
- Documented that CPE treats Superpowers as an external contract and does not
  provide legacy plan auto-support.

## 2.25.0 - 2026-07-03

- Added release-process documentation and deterministic release-contract eval
  coverage for version, history, baseline, and maintainer-doc alignment.
- Fixed release baseline update ordering so `./evals/run.sh --update-baseline`
  can create the first baseline for a newly bumped version.
- Added shared CPE audit semantics for dependency aliases and write-scope
  formatting.
- Added generated task packet markdown views for handoff, prompt, and subagent
  readability.
- Added optional one-line completed-task summaries for hot-tail context.
- Added markdown golden-case evals for operator-readable policy regressions.
- Added structured verification bundle evidence and advisory residual risk
  classes.
- Extended normalized replay to summarize bundle classes and summary counts.
- Improved task packet spec mapping with YAML `spec_refs`, manifest task
  mappings, and dependency aliases.
- Split expected local fallback from prevented delegation in run-quality debt,
  and added missing dispatch evidence follow-up.
- Added structured residual risk object validation and raw/effective plan audit
  count parity checks.
- Added normalized CPE replay deterministic eval coverage and
  `docs/eval-coverage-cpe.md`.

## 2.24.0 - 2026-06-25

- Added stable CPE run-quality debt follow-ups for AgentLens gaps, missing
  execution worktrees, readiness fixable issues, full-spec fallback, and
  delegation policy local fallback.
- Clarified that `completion_audit.passed=true` can coexist with
  `run_quality.grade=yellow` when product verification passed but executor
  operational follow-up remains.
- Added read-only Superpowers plan executability audit design and runtime
  contract for CPE task packet readiness summaries.
- Added deterministic plan-audit coverage for broad write scopes so `**/*` and
  similar scopes become red audit blockers before task contracts or edits.

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
- Tightened finished completion audits so checklist, verification evidence, and
  residual risk remain list-shaped for downstream inspection.
- Required finished operational-quality states to embed `run_quality` with
  readiness, dispatch consistency, context quality, and verification quality
  summaries.
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
