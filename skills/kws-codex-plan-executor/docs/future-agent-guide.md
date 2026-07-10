# Future Agent Guide

Before editing CPE, read [release-process.md](release-process.md),
[doc-update-protocol.md](doc-update-protocol.md), and
[change-protocol.md](../references/change-protocol.md). Add a failing
deterministic check before changing behavior or a skill contract.

Preserve the v3 boundaries: exactly two fixed routes; sequential writes;
explicit task-to-spec mapping; immutable manifest, event, and evidence records;
rebuildable state projection; one shared validator; dry-run repair; read-only
inspection; and byte-preserving `unsupported_schema` handling.

Keep product edits in the isolated worktree and executor artifacts under the
run directory. Update active docs and `docs/verification-log.md` in the same
change. Never mark paid release closeout passed without a current successful
live report produced after explicit cost approval.
