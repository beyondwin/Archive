# Pre-Dispatch Pipeline

Before any worker launch, prove that the task is dependency-ready and its packet
has an ID, bounded prompt, explicit file claim, acceptance command, required
spec refs, evidence requirements, and allowed route.

Write-capable implementation, review, verification, and repair attempts are
queued sequentially and use Sol/high. A scout can be dispatched concurrently
only when it is independent, read-only, has no write claim, and cannot emit a
verdict. Any uncertainty routes the evidence back to Sol.

The parent records the dispatch decision through the kernel and later checks
the worker result, worktree boundary, diff scope, evidence digest, and route
attestation before accepting it.
