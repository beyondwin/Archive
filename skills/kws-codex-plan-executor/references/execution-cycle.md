# Execution Cycle

1. Resolve explicit plan, optional spec/docs, workspace, and mode.
2. Parse tasks and acceptance commands; supplied specs require explicit
   per-task `spec_refs`.
3. Run read-only dependency, capability, dirty-scope, and method preflight.
4. Allocate a unique run ID, isolated worktree, and run directory.
5. Freeze the manifest, initialize the event journal, export task packets once,
   and index every packet path and `packet_sha256`.
6. Run dependency-ready write tasks sequentially. Bounded independent scouts
   may run concurrently under Terra/high read-only policy.
7. Bind every `scout`, `implementation`, `task_review`, `verification`,
   `repair`, and `final_review` request to that indexed packet and current
   revision. Only implementation and repair may write.
8. For each task run `implementation -> acceptance -> task_review ->
   verification`. A typed non-pass routes to a bounded repair or blocker.
9. Run the ordered unique repository command bundle once, attach one
   `repository_check` result per task packet, then run `final_review` per task.
10. If repair advances `worktree_revision`, invalidate the old revision's
    acceptance and verdicts, and rerun the complete downstream suffix until all
    evidence binds the same `worktree_patch_sha256`.
11. Run `validate_integrity`, record the exact completion audit, run
    `validate_completion`, transition terminal status, then revalidate before
    public success.

No edit starts without a task contract containing scope, inspected files,
allowed and forbidden edits, and an acceptance command or honest substitute.
Repeated failures are bounded by root cause; unresolved safety or evidence
gaps block rather than fabricate completion.

Blocked work resumes only from the evidence-derived phase recorded by
`task.retry_scheduled`; there is no generic blocked-to-ready shortcut. Review,
verification, and final review are read-only even when they request changes.
