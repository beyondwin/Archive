# KWS Codex Plan Executor

`kws-codex-plan-executor` executes implementation plans or exports fresh-session
prompts from the same plan inputs.

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

`subagents=on` is the subagent-first default. Eligible write-capable tasks run
through task-packet-scoped subagents by default, with parent post-diff and state
review before acceptance. Pass `subagents=auto` for conservative spawning only
after an explicit delegation or parallel-work request, or `subagents=off` for a
local-only run. A `subagents=on` local fallback must record the concrete reason
in task `subagent_strategy`.

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

Task packets now include `context_components`, component budget breakdown,
acceptance commands, unit manifests, spec mapping evidence, and filtered
decisions. Recovery helpers classify command observations into bounded
`retry`, `bootstrap`, `block`, `fail`, or `continue` actions, and compact
trajectory/progress helpers make stalled runs inspectable without rereading raw
transcripts.

## Design Notes

- `docs/experiments/v2.20-context-intelligence/PLAN.md`
- `docs/experiments/v2.20-context-intelligence/IMPLEMENTATION.md`
- `docs/experiments/v2.21-cache-friendly-execution/PLAN.md`
- `docs/experiments/v2.21-cache-friendly-execution/IMPLEMENTATION.md`
- `docs/experiments/v2.22-operational-run-quality/PLAN.md`
- `docs/experiments/v2.22-operational-run-quality/IMPLEMENTATION.md`

v2.22 records effective delegation policy, bootstrap suggestions, execution
worktree provenance, and read-only run-quality summaries so operators can trust
recent runs without reading raw transcripts.
