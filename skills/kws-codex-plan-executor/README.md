# KWS Codex Plan Executor

`kws-codex-plan-executor` executes implementation plans or exports fresh-session
prompts from the same plan inputs.

With current Superpowers installed, CPE acts as a thin stateful bridge. For
approved interactive implementation plans, run
`scripts/audit_superpowers_compatibility.py`; when it recommends
`thin_stateful_bridge`, use the Superpowers-native execution loop while CPE
preserves worktree isolation, run state, task packets, prompt cache evidence,
Graphify evidence, resume, and inspection.

## Runtime Layout

```text
~/.codex/
  worktrees/<plan-slug>-YYYYMMDD-HHMMSS/       # code and normal git worktree only
  orchestrator/<plan-slug>-YYYYMMDD-HHMMSS/    # state.json, context.json, hooks/, learning_events/
```

If a generated path already exists, append a short random suffix to the run id
before creating the worktree or orchestrator directory.

## Defaults

- `mode=interactive`
- `subagents=on`
- `headless_sandbox=workspace-write`
- `context_mode=auto`
- `context_budget=60000`
- `manifest_fallback=full_spec_on_blocker`

`subagents=on` is the adaptive subagent-first default. CPE delegates when the
task is safe and delegation has value. Small, low-risk, linear tasks may run
through local fast path with the same task contract, diff review, acceptance,
reconciliation, and state validation gates. Pass `subagents=auto` for
conservative spawning only after explicit delegation intent, or `subagents=off`
for local-only execution.

For interactive implementation work, this subagent policy is now routed through
the compatibility audit first. Prompt, handoff, headless, resume, and
inspection stay CPE-owned even when interactive implementation uses the current
Superpowers loop.

## Validation

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_eval_harness.py
python3 evals/check_run_diffs.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_task_packet_view.py
python3 evals/check_context_summary.py
python3 evals/check_markdown_golden_cases.py
python3 evals/check_verification_bundle.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_repair_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_validate_state_modular_parity.py
python3 evals/check_recent_run_rubric.py
python3 evals/check_cpe_replay.py
python3 evals/check_recovery_policy.py
python3 evals/check_trajectory_projection.py
python3 evals/check_progress_ledger.py
python3 evals/check_operational_run_quality.py
python3 evals/check_superpowers_compatibility.py
```

`evals/run.sh` uses deterministic fixture runners for prompt, handoff,
interactive, and headless fixture outputs, then validates those artifacts with
`check_prompt.py` or `check_execution.py`. This keeps local evals stable without
launching nested model sessions.

Prompt and handoff modes are export-only and must not create worktrees or
orchestrator artifacts.

When execution needs to read local skill files, resolve paths from the active
skill registry/root mapping and do not hard-code root directories. In repos that
declare graphify instructions, compare `graphify-out/GRAPH_REPORT.md` against
`git rev-parse HEAD`, run `graphify update .` after code changes, and preserve
that evidence in the completion audit.

Prompt cache hardening is checked with `scripts/audit_prompt_cache.py`.
Graphify freshness uses `scripts/check_graphify_freshness.py`, and subagent
readiness uses `scripts/preflight_dispatch.py`; all emit JSON evidence that
state validation can reject before a finished outcome.
Run readiness also reports deterministic `normalized_write_globs` and
`suggested_write_scopes` for comma-joined scope mistakes, so operators can
retry dispatch without hand-parsing the raw path string.
Superpowers compatibility is checked with
`scripts/audit_superpowers_compatibility.py`; it scores CPE-primary,
Superpowers-native-only, and thin-stateful-bridge routes and fails when required
current Superpowers contracts are missing.
Plan executability is checked with `scripts/audit_plan_executability.py`. It
summarizes whether the parsed plan is a current Superpowers-compatible plan,
which tasks are ready for CPE task packets, local fast path, delegation,
operator review, or blocking before task contracts or edits. CPE treats
Superpowers as an external contract and does not modify installed Superpowers
skills. Legacy plan auto-support is not provided: plans missing the current
`REQUIRED SUB-SKILL` header, task file scope, or other required execution shape
are classified as `blocked_unsupported_plan_shape`.
The compact state summary may preserve both raw audit counts and
operator-reviewed effective counts with `raw_blocking_issue_count`,
`raw_fixable_issue_count`, `operator_reviewed_blocking_issues`, and
`operator_decision`.
Normalized replay evidence is generated with `scripts/normalize_cpe_run.py`
and covered by `check_cpe_replay.py`; it records stable summaries and forbidden
pattern flags without raw prompts or transcripts.
Recent-run rubric reports are generated with `scripts/analyze_recent_runs.py`;
they read recent `state.json` files and summarize operational quality without
raw transcripts.

Run-state repair is separate from inspection and defaults to dry-run:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --recent 20 \
  --stale-hours 24 \
  --output /tmp/cpe-repair-plan.json
```

Apply is intentionally narrow:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --run-id <run_id> \
  --action mark-blocked-stale \
  --apply
```

The first repair action only marks one stale non-terminal run as blocked when
its execution worktree is missing and state validation passes before and after
the patch. It does not delete worktrees, run directories, or finished states.

Task packets now include `context_components`, component budget breakdown,
acceptance commands, unit manifests, spec mapping evidence, and filtered
decisions. Recovery helpers classify command observations into bounded
`retry`, `bootstrap`, `block`, `fail`, or `continue` actions, and compact
trajectory/progress helpers make stalled runs inspectable without rereading raw
transcripts.

Task packet human views are generated markdown derivatives for operators,
handoff recipients, and subagents. The JSON packet remains the source of truth;
the markdown view must preserve files, task body, AC, verification, forbidden
globs, context budget, and full-spec fallback warnings.

## Release Contract

`docs/release-process.md` defines the CPE package versioning and release
closeout contract. `SKILL.md` metadata is the official version source of truth;
`HISTORY.md`, `evals/baselines/v<version>.json`, and
`docs/verification-log.md` must stay aligned with it when a release is closed.

## Design Notes

- `docs/user-guide.ko.md` - Korean operator guide for modes, subagent policy,
  Superpowers bridge, readiness audits, run quality, repair, Graphify, and
  verification.
- `docs/mental-model.ko.md` - Korean junior-friendly mental model with
  flowcharts, UI-style run panels, and a glossary for understanding how CPE
  executes plans safely.
- `docs/how-it-works.md` - execution flow overview.
- `docs/human-readable-harness-flow.ko.md` - Korean before/after explanation
  of the human-readable harness flow and junior-friendly diagrams.
- `docs/state-and-logging.md` - state fields, Graphify/dispatch evidence,
  plan executability audit, run quality, and repair state.
- `docs/evals-and-verification.md` - deterministic eval and harness guide.
- `docs/eval-coverage-cpe.md` - deterministic coverage map for run-quality
  cleanup failure modes.
- `docs/risks-limitations-deferrals.md` - known limits and conservative
  operator boundaries.
- `docs/verification-log.md` - compact verification history.
- `docs/experiments/v2.20-context-intelligence/PLAN.md`
- `docs/experiments/v2.20-context-intelligence/IMPLEMENTATION.md`
- `docs/experiments/v2.21-cache-friendly-execution/PLAN.md`
- `docs/experiments/v2.21-cache-friendly-execution/IMPLEMENTATION.md`
- `docs/experiments/v2.22-operational-run-quality/PLAN.md`
- `docs/experiments/v2.22-operational-run-quality/IMPLEMENTATION.md`

v2.22 records effective delegation policy, bootstrap suggestions, execution
worktree provenance, and read-only run-quality summaries so operators can trust
recent runs without reading raw transcripts.
Current run-quality debt distinguishes
`delegation_policy_expected_local_fallback` from
`delegation_policy_prevented_all_delegation` and reports
`delegation_policy_missing_dispatch_evidence` when a finished write-capable
task lacks dispatch evidence.
