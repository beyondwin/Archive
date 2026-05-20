Source-of-truth: the design document wins when this reference and code disagree.

# Failure Policy

Failure categories include malformed result, method audit failure, review
rejection, review changes requested, verification failure, merge conflict,
adapter crash, and blocked dependency.

Gate retry budgets are role-specific. A reviewer `changes_requested` outcome
creates one fresh implementer attempt with review findings in the retry prompt.
A verifier `failed` outcome creates one fresh implementer attempt only when the
verification evidence is actionable. `rejected`, verifier `blocked`, exhausted
budgets, and unresolved critical failures mark the task blocked.
