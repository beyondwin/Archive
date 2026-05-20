Source-of-truth: the design document wins when this reference and code disagree.

# Merge Queue

The merge queue accepts candidates only after worker result validation,
diff-scope checks, review approval, and verification pass.

Ungated candidates stay `pending_review`. Reviewer `changes_requested` marks
the previous candidate `changes_requested`; verifier `failed` marks it
`verification_failed`. Those statuses are retained as evidence and are never
eligible for cherry-pick. The retry path creates a new implementer worker,
new worktree, and new candidate.

Apply semantics use git cherry-pick from worker commits into
`agentrunway/<run_id>/main` and validate changed files against claims. A merge conflict
aborts the cherry-pick and records `merge_conflict`; production policy
allows one fresh re-dispatch from updated run main before blocking with
`recurring_merge_conflict`.

`agentrunway apply` is separate from the merge queue. It copies already merged
run-main commits into the source checkout only when explicitly invoked.
