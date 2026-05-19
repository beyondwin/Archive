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
- `subagents=auto`
- `headless_sandbox=workspace-write`
- `context_mode=auto`
- `context_budget=60000`
- `manifest_fallback=full_spec_on_blocker`

Pass `subagents=on` to explicitly permit subagents, or `subagents=off` for a
local-only run.

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
```

`evals/run.sh` uses deterministic fixture runners for prompt, handoff,
interactive, and headless fixture outputs, then validates those artifacts with
`check_prompt.py` or `check_execution.py`. This keeps local evals stable without
launching nested model sessions.

Prompt and handoff modes are export-only and must not create worktrees or
orchestrator artifacts.
