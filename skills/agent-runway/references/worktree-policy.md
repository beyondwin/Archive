Source-of-truth: the design document wins when this reference and code disagree.

# Worktree Policy

`workspace_id` is derived from the shared git common dir, remote URL, and primary branch ref.

The dirty source check refuses uncommitted work unless explicitly allowed. Cross-workspace identity belongs in `registry.sqlite` for production hardening.
