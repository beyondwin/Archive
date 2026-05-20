Source-of-truth: the design document wins when this reference and code disagree.

# Merge Queue

The merge queue accepts candidates only after worker result validation,
diff-scope checks, review approval, and verification pass.

Apply semantics use git cherry-pick from worker commits into
`agentrunway/<run_id>/main` and validate changed files against claims. A merge conflict
aborts the cherry-pick and records `merge_conflict`; production policy
allows one fresh re-dispatch from updated run main before blocking with
`recurring_merge_conflict`.

`agentrunway apply` is separate from the merge queue. It copies already merged
run-main commits into the source checkout only when explicitly invoked.
