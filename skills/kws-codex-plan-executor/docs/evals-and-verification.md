# Evals And Verification

Run deterministic checks before shipping skill changes:

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
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_recovery_policy.py
python3 evals/check_trajectory_projection.py
python3 evals/check_progress_ledger.py
python3 evals/check_operational_run_quality.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

The fixture harness copies the skill under test into a fixture repository, then
uses deterministic runners to generate prompt/handoff outputs and execution
repository/state artifacts. `check_prompt.py` and `check_execution.py` still
validate the generated outputs, state, context snapshots, and forbidden edits.

The execution-hardening evals cover prompt cache boundaries, optional provider
cache observations, Graphify freshness evidence, and deterministic subagent
pre-dispatch decisions.

The quality-loop evals also cover task packet component accounting, filtered
decision context, structured blocker/failure state, recovery policy decisions,
trajectory JSONL projection, and progress ledger stall detection.

`check_operational_run_quality.py` covers v2.22 optional state fields,
delegation policy enums, execution-worktree provenance, static fixture emission
of run-quality fields, and recent inspection summary behavior.
