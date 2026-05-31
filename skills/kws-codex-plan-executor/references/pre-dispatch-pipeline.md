# Pre-Dispatch Pipeline

`subagents=on` is subagent-first. Run this pipeline before each eligible
write-capable task and delegate when every prerequisite passes.

1. Run the deterministic preflight decision:
   `python3 scripts/preflight_dispatch.py --state "$STATE_PATH" --task-id "$TASK_ID" --task-packet "$CURRENT_TASK_PACKET_PATH" --repo-root "$WORKTREE_ABS" --write-scope "$WRITE_SCOPE" --output "$RUN_DIR/dispatch-$TASK_ID.json"`.
2. Confirm the resolved invocation has `subagents=on`, or has
   `subagents=auto` plus an explicit user request for subagents, delegation, or
   parallel work.
3. Confirm `current_task_packet_path` exists and is readable.
4. Confirm declared files are non-empty.
5. Confirm dirty files do not overlap the task.
6. Confirm state is writable.
7. Assign a disjoint write scope equal to or narrower than packet
   `write_policy.allowed_write_globs`.
8. Tell the worker it is not alone in the codebase and must not revert edits
   made by others.
9. Record the delegation in `subagent_runs`.
10. Give each worker only the task id, task packet path, state path, write
   scope, and verification expectation.
11. After completion, run `scripts/check_run_diffs.py` and perform post-diff
    and state review before accepting subagent output.

If any prerequisite fails under `subagents=on`, run the task locally only after
recording `subagent_strategy.mode = local_fallback` on the task with the exact
failed prerequisite or safety reason. If delegation succeeds, record
`subagent_strategy.mode = delegated` with the accepted `subagent_runs` ids.
Finished state cannot carry unresolved `dispatch_decisions[].decision = block`.
