# Phase 1: Parallel Sub-Flow (P2)

> **Loaded by**: `references/phases/phase-1-task-cycle.md` — Read when the current
> parallel group from `<active>.execution_plan` has size ≥ 2.
>
> **Scope**: multi-task parallel dispatch — pre-group SHA, sub-worktree creation
> with byte-identical settings.json, batched Implementer dispatch, result
> aggregation, out-of-scope checks, serial ESCALATE resolution, cherry-pick onto
> the parent worktree, serial per-task Reviewer + Verifier, and per-task cleanup.
> Combined Reviewer and Verifier still run sequentially after the parallel merge.
>
> **Why extracted**: the parallel path fires only for multi-task waves; keeping
> it out of the hot per-task cycle keeps the resident prefix smaller. v2.21 D005.

---

### Parallel Sub-Flow (P2 — multi-task parallel group)

Triggered when the current parallel group from `<active>.execution_plan` has size ≥ 2.

**Pre-flight invariant:** all tasks in the group have disjoint `Files:` sets (Phase 0 Step 6 partition guarantees this). If you observe the group has size ≥ 2 but the tasks share any file: halt — `execution_plan` is corrupt; do not proceed.

**Step P.0: Record pre-group SHA**

```bash
git -C <worktree_path> rev-parse HEAD
```
Persist the SHA to **`state.current_pre_group_sha`** via atomic R-M-W of state.json (write-then-readback per the State-file write guardrail). Every task in the group branches off this SHA. Resume protocol: if the orchestrator crashes during a parallel group, the resume path reads this field to identify the rollback target before reconstructing the group. Cleared to `null` after Step P.8 (group complete) or after group abort.

The Cross-Plan Trigger reset list (Phase 2 Step -1 step 4 — the `plan_chain` swap) also clears `current_pre_group_sha` alongside `current_pre_task_sha`.

**Step P.1: Create sub-worktrees + copy settings.json**

For each task `task_<N>` in the group:
```bash
mkdir -p <worktree_path>/.parallel
git -C <worktree_path> worktree add \
  <worktree_path>/.parallel/task_<N> \
  HEAD
# Copy the worktree-local settings.json so claude code in the sub-worktree
# finds the same PreToolUse/PostToolUse/SubagentStop hook bindings.
mkdir -p <worktree_path>/.parallel/task_<N>/.claude
cp <worktree_path>/.claude/settings.json \
   <worktree_path>/.parallel/task_<N>/.claude/settings.json
```
Leave settings.json byte-identical to the parent — its hook `command` strings reference absolute paths under `<orch_dir>/hooks/...`, which lives outside every worktree, so all sub-worktrees hit the same hook scripts. Do not rewrite paths.

**Step P.2: Dispatch all Implementers in one Orchestrator message**

In a single assistant message, emit N `Agent` tool calls — one per task in the group. Each Agent dispatch:
- Uses the same Implementer Prompt Template, with `{implementer_model}` filled from `state.implementer_model.used` (same value for all parallel siblings — the field is run-level, not task-level).
- **Sets the Agent tool `model` parameter to `state.implementer_model.used`** under the same rule as the sequential Step 1 dispatch — `sonnet` may omit the parameter, `opus` MUST set it explicitly. Forgetting this here silently downgrades every parallel-dispatched task to Sonnet regardless of the run's selection (v2.12 regression risk).
- Has `{worktree_path}` set to the **sub-worktree** path (`<worktree_path>/.parallel/task_<N>`), NOT the parent worktree
- Has `{deps_for_this_task}` set to the dependency list (which by definition only includes earlier-WAVE tasks, all already merged into the parent before P.0)

Collect all N tool results.

**Step P.3: Aggregate results**

For each sub-worktree task:
- `STATUS: DONE` → record the sub-worktree commit SHA from the `COMMIT:` line; record `FILES_CHANGED:` for merge verification.
- `STATUS: ESCALATE` → defer the escalation; continue collecting other results. The escalations are handled sequentially in P.5.

If at least one ESCALATE: do NOT merge any sub-worktree until all escalations are resolved (P.5). Keep all sub-worktrees intact.

**Step P.4: Out-of-scope file check (guardrail)**

For each DONE sub-worktree:
- Read its `FILES_CHANGED:`. Confirm every file is within the task's declared `Files:` block.
- Confirm that across ALL DONE sub-worktrees in this group, the union of `FILES_CHANGED` has no duplicates.

If any out-of-scope edit OR duplicate file: halt the entire group. Remove all sub-worktrees with `git worktree remove --force`. Re-dispatch the offending task sequentially in the main worktree under standard flow with `## Fix Required\n<out-of-scope file list>`.

**Step P.5: Resolve ESCALATEs serially**

For each ESCALATE from P.3: handle via the standard Escalation Protocol. The escalation may resolve via spec edit (continue to P.6), AMBIGUITY edit, or hit the escalation cap (skip that task; remove its sub-worktree).

**Step P.6: Cherry-pick onto parent worktree**

In task-ID order (numeric ascending), for each successful sub-worktree:
```bash
git -C <worktree_path> cherry-pick <sub_worktree_commit_sha>
```

If a cherry-pick fails (should be impossible given the disjoint-files guarantee, but defensively):
- `git -C <worktree_path> cherry-pick --abort`
- Halt the group. Report the conflict path to the user; do NOT proceed to Reviewer/Verifier.

After all cherry-picks succeed:
```bash
git -C <worktree_path> worktree remove --force <worktree_path>/.parallel/task_<N>  # for each N
rm -rf <worktree_path>/.parallel
```

**Step P.7: Per-task Reviewer + Verifier (serial)**

For each task in the group, in task-ID order, run Steps 2 (Combined Reviewer) and 3 (Verifier) from the standard flow. The diff is computed from `current_pre_group_sha` to the post-cherry-pick HEAD scoped to this task's `FILES_CHANGED`.

If a Reviewer FAIL or Verifier FAIL occurs for any task: reset the offending task ONLY by reverting its specific cherry-picked commit (`git revert <commit_sha>` — single-commit revert) and re-dispatch sequentially in the main worktree under the standard flow. Other tasks' commits stay in place.

**Step P.8: Agent Cleanup per task**

Run Step 4 (Agent Cleanup) for each task in the group, writing per-task state entries normally. The first task in the group writes the compaction-point check; subsequent tasks bypass it (the boundary is the LAST task of the group).

**Failure isolation guarantee (P2):** if any single sub-worktree dies (Implementer ESCALATE or out-of-scope edit), only that task is rolled back. The other parallel commits stay. This is the core wall-time win — independent failures don't restart the whole wave.
