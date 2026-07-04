# Evals And Verification

Run deterministic checks before shipping skill changes:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_eval_harness.py
python3 evals/check_baseline_utils.py
python3 evals/check_release_contract.py
python3 evals/check_run_diffs.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_task_packet_view.py
python3 evals/check_context_summary.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_repair_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_validate_state_modular_parity.py
python3 evals/check_markdown_golden_cases.py
python3 evals/check_verification_bundle.py
python3 evals/check_recovery_policy.py
python3 evals/check_trajectory_projection.py
python3 evals/check_progress_ledger.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
python3 evals/check_recent_run_rubric.py
python3 evals/check_superpowers_compatibility.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

`./evals/run.sh` is the default full harness verification command. It builds a
temporary generated baseline and compares it with `evals/baselines/v<version>.json`
while ignoring the top-level `date` field, but it does not update the tracked
baseline file. When fixture output intentionally changes, review the generated
output and then run `./evals/run.sh --update-baseline` to update the baseline.
Focused fixture runs such as `./evals/run.sh fixtures/01-prompt-only.yaml`
compare only the executed fixture entries; focused update runs replace only
those fixture entries and preserve unexecuted fixtures.
`evals/baseline_utils.py` owns the baseline compare and subset merge semantics,
with direct coverage in `evals/check_baseline_utils.py`.

`check_release_contract.py` verifies CPE release metadata and docs alignment:
`SKILL.md` semantic version, matching baseline file, matching baseline version,
current `HISTORY.md` section, release-process docs, and maintainer cross-links.
The check is read-only and never updates baselines.

The fixture harness copies the skill under test into a fixture repository, then
uses deterministic runners to generate prompt/handoff outputs and execution
repository/state artifacts. `check_prompt.py` and `check_execution.py` still
validate the generated outputs, state, context snapshots, and forbidden edits.

The execution-hardening evals cover prompt cache boundaries, optional provider
cache observations, Graphify freshness evidence, deterministic subagent
pre-dispatch decisions, and run-readiness repair hints for malformed write
scopes.

Plan executability evals cover the read-only audit that runs before task
contracts or edits. They verify green current Superpowers-compatible task
packets, yellow docs-only acceptance gaps, red missing files as
`blocked_unsupported_plan_shape`, red broad write scopes, non-docs missing
acceptance with `subagent_reason=acceptance_command_missing`,
lockfile/operator-review risk as `operator_review_required`, legacy header
blocking without auto-support, and thin-stateful-bridge summary counts.

Adaptive dispatch evals cover docs-only local fast path, multi-file delegation
when spawn policy is available, dirty overlap blocking, broad write-scope
blocking, packet hash mismatch blocking, and risky lockfile blocking.

The quality-loop evals also cover task packet component accounting, filtered
decision context, structured blocker/failure state, recovery policy decisions,
trajectory JSONL projection, and progress ledger stall detection.

`check_recent_run_rubric.py` covers `scripts/analyze_recent_runs.py` and
synthetic green/yellow/red recent-run aggregation. It verifies full-spec
fallback and expected local fallback counts without reading raw transcripts.

`check_validate_state_modular_parity.py` covers the public `validate_state.py`
CLI while validation logic is routed through `cpe_state_validation` domain
modules. It keeps representative valid and invalid states stable across
validator refactors.

Human-readable harness evals cover generated task packet markdown views,
one-line hot-tail summaries, markdown policy golden cases, and structured
verification bundle evidence. The initial markdown cases cover dirty related
worktrees, ambiguous resume selection, unsafe verification substitutes,
subagent local fallback, and task packet human-view parity.

`check_operational_run_quality.py` covers v2.22 optional state fields,
delegation policy enums, execution-worktree provenance, static fixture emission
of run-quality fields, and recent inspection summary behavior. `check_inspect_runs.py`
also covers actionable quality followups for stale non-terminal runs and missing
execution worktrees.

`check_cpe_replay.py` covers `scripts/normalize_cpe_run.py`, including
completion status, run-quality grade, plan-audit count summary,
dispatch-decision reason counts, structured residual risk classes,
verification evidence classes, verification bundle names, task summary counts,
hot-tail summary counts, AgentLens status, prompt/Graphify status, and
forbidden durable-output patterns.
`docs/eval-coverage-cpe.md` maps these checks to the CPE run-quality cleanup
failure modes.

`check_superpowers_compatibility.py` covers the current Superpowers contract
surface and verifies that CPE recommends `thin_stateful_bridge` only when the
required brainstorming, planning, subagent review, and completion-verification
contracts are present.

`check_plan_executability_audit.py` covers
`scripts/audit_plan_executability.py` and is part of `./evals/run.sh`, so the
full harness rejects plan-audit regressions even when no dynamic model session
runs.
