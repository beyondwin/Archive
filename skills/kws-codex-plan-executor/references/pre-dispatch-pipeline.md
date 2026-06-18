# Pre-Dispatch Pipeline

`subagents=on` is adaptive subagent-first. The executor first checks whether
delegation is safe, then checks whether delegation has value. Safe but small,
linear, low-risk tasks may use adaptive local fast path and record
`subagent_strategy.mode = local_fallback` with an adaptive reason. This is a
policy decision, not a failed dispatch.

Before task contracts and edits, run the aggregate readiness audit over the
generated task packets. The audit is read-only and reports fixable metadata
issues such as missing acceptance commands, full-spec fallback, context budget
pressure, and malformed write scopes. It does not expand allowed write globs or
weaken safety gates.

1. Run the deterministic preflight decision:
   `python3 scripts/preflight_dispatch.py --state "$STATE_PATH" --task-id "$TASK_ID" --task-packet "$CURRENT_TASK_PACKET_PATH" --repo-root "$WORKTREE_ABS" --write-scope "$WRITE_SCOPE" --spawn-policy "$SPAWN_POLICY" --explicit-delegation-requested "$EXPLICIT_DELEGATION_REQUESTED" --requested-subagents "$REQUESTED_SUBAGENTS" --requested-source "$REQUESTED_SOURCE" --output "$RUN_DIR/dispatch-$TASK_ID.json"`.
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

| Decision | Meaning | Required follow-through |
| --- | --- | --- |
| `delegate` | Delegation is safe and useful. | Spawn from task packet, then parent reviews diff and state. |
| `local_fallback` with adaptive reason | Local fast path is safer or cheaper for a small linear task. | Execute locally with task contract, diff check, acceptance, reconcile, and validate. |
| `local_fallback` with policy/tool reason | Delegation is unavailable or not explicitly allowed. | Execute locally and record the concrete policy reason. |
| `block` | Safety gate failed. | Do not execute until dirty scope, packet drift, broad write scope, or risky scope is resolved. |

If any prerequisite fails under `subagents=on`, run the task locally only after
recording `subagent_strategy.mode = local_fallback` on the task with the exact
failed prerequisite or safety reason. If delegation succeeds, record
`subagent_strategy.mode = delegated` with the accepted `subagent_runs` ids.
Finished state cannot carry unresolved `dispatch_decisions[].decision = block`.

`--spawn-policy` is `available`, `unavailable`, `explicit-request-required`, or
`unknown`. `--requested-source` is `default`, `explicit`, `natural_language`, or
`resume_state`. When the spawn policy is `explicit-request-required` and the
invocation did not carry explicit delegation intent, the decision is
`local_fallback` with failed prerequisite
`spawn_policy_requires_explicit_user_request`. That is a policy fallback, not a
task failure.
