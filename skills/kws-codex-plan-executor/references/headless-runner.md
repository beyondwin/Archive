# Headless Runner

Headless mode runs the same executor contract in a fresh process. It must parse
invocation args once, create the worktree/run-dir layout, run local-env preflight,
write `plan.json`, build `spec_manifest.json` when a spec exists, build task
packets before task execution, and avoid nested `codex exec`.

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
RUN_ID="${PLAN_SLUG}-$(date -u +%Y%m%d-%H%M%S)"
WORKTREE="$CODEX_HOME/worktrees/$RUN_ID"
RUN_DIR="$CODEX_HOME/orchestrator/$RUN_ID"
STATE_PATH="$RUN_DIR/state.json"
mkdir -p "$CODEX_HOME/worktrees" "$RUN_DIR/hooks" "$RUN_DIR/learning_events"
```

Before worktree creation, run `scripts/inspect_runs.py` for the target plan. If
one unambiguous active run exists and the invocation did not request resume,
stop and ask whether to resume or start a new run. If multiple active runs
exist, stop with the stale-run report. Do not mutate stale runs automatically.

Before task execution, create the git worktree under `$WORKTREE`; if the branch
name already exists, append the run_id or another unique suffix. Do not implement from `main`.
Do not implement from the caller's original checkout.

When `CODEX_EVAL_HOME` is present, the current `codex exec --cd` repository is
already the isolated execution workspace. In that eval runtime, do not run
`git worktree add` or write git refs. Use the current repository for edits,
record the logical `$WORKTREE` path in state, and keep all orchestrator
artifacts under `$CODEX_EVAL_HOME/.codex/orchestrator/<run_id>`.

The headless prompt must include `using-superpowers` and
`test-driven-development`, must explain that this is not a headless-only rule,
and must instruct the target: `Do not launch another nested codex exec`.
Do not launch another nested `codex exec`.

Map `headless_sandbox=<value>` to `HEADLESS_SANDBOX=<value>`, with supported
values `workspace-write` and `read-only`. In `read-only`, run preflight and
prompt verification only.

Write final JSON using `templates/headless-output-schema.json` with `status`,
`run_id`, `state_path`, `summary`, `changed_files`, `verification`, `open_gaps`,
`residual_risk`, `context_artifacts`, and `next_action`. `context_artifacts`
contains `spec_manifest_path`, `task_packet_dir`, and `decisions_path` as
strings or nulls.
