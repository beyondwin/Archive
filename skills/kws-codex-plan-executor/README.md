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
```

Prompt and handoff modes are export-only and must not create worktrees or
orchestrator artifacts.

## Design Notes

- `docs/experiments/v2.20-context-intelligence/PLAN.md`
- `docs/experiments/v2.20-context-intelligence/IMPLEMENTATION.md`
