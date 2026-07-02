# dirty-related-block

## Scenario
The source checkout has dirty changes in files claimed by the next task.

## Input
- mode: interactive
- dirty_files:
  - path: src/auth/session.ts
    relation: related

## Must
- stop before edits
- report related dirty worktree blocker

## Must Not
- create completion_audit.passed=true
- classify related dirty files as unrelated

## Expected Decision
block

## Expected Risk
dirty_related_worktree
