# Pre-Dispatch Pipeline

Before delegating work:

1. Confirm explicit user request or `subagents=on`.
2. Confirm `current_task_packet_path` exists and is readable.
3. Confirm declared files are non-empty.
4. Confirm dirty files do not overlap the task.
5. Confirm state is writable.
6. Assign a disjoint write scope equal to or narrower than packet
   `write_policy.allowed_write_globs`.
7. Tell the worker it is not alone in the codebase and must not revert edits
   made by others.
8. Record the delegation in `subagent_runs`.
9. Give each worker only the task id, task packet path, state path, write
   scope, and verification expectation.
10. After completion, run `scripts/check_run_diffs.py` and perform post-diff
    and state review before accepting subagent output.
