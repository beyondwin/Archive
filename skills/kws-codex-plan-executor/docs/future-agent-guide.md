# Future Agent Guide

Before editing this skill, read [release-process.md](release-process.md) and
[doc-update-protocol.md](doc-update-protocol.md), then update tests first. Keep
the active contract aligned across `SKILL.md`,
`templates/fresh-session-prompt.txt`, references, scripts, docs, evals, history,
and baselines.

Do not reintroduce repository-local executor state. Code belongs in the
worktree; orchestration belongs under the Codex home directory.
