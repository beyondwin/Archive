# Execution Cycle

1. Resolve explicit plan, optional spec/docs, workspace, and mode.
2. Parse tasks and acceptance commands; supplied specs require explicit
   per-task `spec_refs`.
3. Run read-only dependency, capability, dirty-scope, and method preflight.
4. Allocate a unique run ID, isolated worktree, and run directory.
5. Freeze the manifest, initialize the event journal, and create task packets.
6. Run dependency-ready write tasks sequentially. Bounded independent scouts
   may run concurrently under Terra/high read-only policy.
7. For each task, use separate Sol/high implementation, review, verification,
   and repair attempts as required. Persist results through the kernel.
8. Run a Sol/high whole-diff review, repository acceptance checks, and
   reconciliation.
9. Validate manifest, event chain, replay parity, evidence, git scope, model
   attestation, task status, and completion evidence.

No edit starts without a task contract containing scope, inspected files,
allowed and forbidden edits, and an acceptance command or honest substitute.
Repeated failures are bounded by root cause; unresolved safety or evidence
gaps block rather than fabricate completion.
