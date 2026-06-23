# Evals And Verification

Run deterministic checks before shipping skill changes:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_eval_harness.py
python3 evals/check_baseline_utils.py
python3 evals/check_run_diffs.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
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
python3 evals/check_recovery_policy.py
python3 evals/check_trajectory_projection.py
python3 evals/check_progress_ledger.py
python3 evals/check_operational_run_quality.py
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

The fixture harness copies the skill under test into a fixture repository, then
uses deterministic runners to generate prompt/handoff outputs and execution
repository/state artifacts. `check_prompt.py` and `check_execution.py` still
validate the generated outputs, state, context snapshots, and forbidden edits.

The execution-hardening evals cover prompt cache boundaries, optional provider
cache observations, Graphify freshness evidence, deterministic subagent
pre-dispatch decisions, and run-readiness repair hints for malformed write
scopes.

Adaptive dispatch evals cover docs-only local fast path, multi-file delegation
when spawn policy is available, dirty overlap blocking, broad write-scope
blocking, packet hash mismatch blocking, and risky lockfile blocking.

The quality-loop evals also cover task packet component accounting, filtered
decision context, structured blocker/failure state, recovery policy decisions,
trajectory JSONL projection, and progress ledger stall detection.

`check_operational_run_quality.py` covers v2.22 optional state fields,
delegation policy enums, execution-worktree provenance, static fixture emission
of run-quality fields, and recent inspection summary behavior. `check_inspect_runs.py`
also covers actionable quality followups for stale non-terminal runs and missing
execution worktrees.

`check_superpowers_compatibility.py` covers the current Superpowers contract
surface and verifies that CPE recommends `thin_stateful_bridge` only when the
required brainstorming, planning, subagent review, and completion-verification
contracts are present.
