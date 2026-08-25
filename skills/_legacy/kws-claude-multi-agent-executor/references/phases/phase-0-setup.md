# Phase 0: Setup — v3.0 (SETUP: plan → state assembly)

> **v3.0 cutover.** `kernel.py init` (SKILL.md §②) already does the v2 setup that
> used to live here — dirty-tree check, RUN_ID derivation, `git worktree add`,
> worktree-hook materialization, `<orch_dir>` subdir creation, and the initial
> `state.json` write (schema_version 3, `status:"SETUP"`, empty task tables). This
> doc is now the **SETUP assembler**: the plan→state assembly the orchestrator MUST
> perform between `kernel.py init` and the first `kernel.py next`.

Why this step exists: `init` writes EMPTY `tasks` / `execution_plan` / `risk_levels`
/ `compaction_points` / `spec_manifest`. `kernel.py next` on that state returns
`{"action":"halt","reason":"no_dispatchable_task"}`. There is deliberately **no
`kernel.py setup` subcommand** — the assembly is driven by the orchestrator using the
kernel library modules under `scripts/kernel/` (importable Python, no CLI).

## SETUP sequence (run once, after init, before the first `next`)

1. **Parse the plan.** `planparse.parse(plan_text)` → a list of task dicts
   (`id`, `title`, `files`, `body`, `acceptance`) plus structural-validation errors.
   A missing `Files:` block, a missing task header, or an out-of-repo path is a
   **halt to the user** — never infer a correction.

2. **Assign risk.** `gate.assign_risk(tasks, override)` → `risk_levels` (per-task
   `low|mid|high`). A run-level `risk=` arg overrides all tasks.

3. **Partition waves.** `gate.partition_waves(tasks, risk, parallel)` → `execution_plan`
   as **`list[list[str]]`** — e.g. `[["task_1"], ["task_2","task_3"]]`. This is the
   EXACT shape `transitions.decide` iterates (`for group in execution_plan: for task_id
   in group`). A `list[dict]` silently breaks dispatch. `parallel=off` produces
   singleton groups.

4. **Build packets.** For each task, `packets.build_packet(task, manifest, spec_text,
   budget_chars)` → write one packet to `<orch_dir>/packets/<task_id>.json`.
   `dispatch.build` reads these at dispatch time for context-budgeted spec sections.

5. **Preflight each task.** `gate.preflight(task, packet, state)` is the **single
   source of dispatch decisions** — `delegate_serial` / `delegate_parallel` / `block`.
   Never bypass it. A `block` on a safety gate (write-scope too broad, packet budget
   red, file-claim collision) or a trust/risk trigger (risk_markers, un-reviewed spec
   fallback) surfaces to the user via `escalate_to_user`. Contention that can't be
   proven parallel-safe falls through to the DEFAULT `delegate_serial` (D001;
   `serialization_reason` is NOT wired — do not claim it is produced).

6. **Baseline.** Run the baseline test command against the fresh worktree HEAD and
   record pass/fail counts into `state.baseline` (this is a setup-time `run_command`,
   NOT a `decide()` action).

7. **Assign compaction_points** (optional). If the plan warrants mid-run compaction,
   set `state.compaction_points` to the boundary task ids — `transitions.decide` reads
   this to emit the `compact` action. Nothing in the kernel WRITES it, so an empty list
   simply means no in-run compaction.

8. **Write spec_manifest** and set `status:"RUNNING"`. Persist all of the above
   (`tasks`, `execution_plan`, `risk_levels`, packets, `spec_manifest`,
   `compaction_points`, `baseline`) into `state.json`.

After SETUP, enter the SKILL.md §③ loop. The kernel cannot dispatch a task that SETUP
did not write into `state.execution_plan` + `state.tasks`.

## Multi-plan chains

For a `plan_chain` run, SETUP repeats per active plan (the Cross-Plan Trigger inside
`kernel.py finalize` / the orchestrator advances `active_plan` and re-assembles the
next plan against the previous plan's HEAD as the new baseline). Chain field-split and
`<active>` resolution: [`../cross-cutting/state-schema.md`](../cross-cutting/state-schema.md).
