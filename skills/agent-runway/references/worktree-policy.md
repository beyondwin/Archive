Source-of-truth: the design document wins when this reference and code disagree.

# Worktree Policy

`workspace_id` is derived from the shared git common dir, remote URL, and primary branch ref.

The dirty source check refuses uncommitted work unless explicitly allowed. Cross-workspace identity belongs in `registry.sqlite` for production hardening.

## Quality-First Hybrid Lifecycle

AgentRunway keeps worktree reduction subordinate to review and verification
quality.

- Run main: one persistent worktree per run, registered as
  `run_main_persistent`, and the only place candidates are merged.
- Implementer: one isolated worktree per candidate. Selected candidates are
  retained for apply; non-selected candidates are converted to archived
  evidence before cleanup eligibility.
- Reviewer: default mode is `diff`. High-risk tasks, schema or migration
  surfaces, generated-code surfaces, and `needs_context` responses use
  `full_tree`. Successful reviewer worktrees are cleanup eligible after the
  review artifact is captured; failed reviewer worktrees are retained for
  diagnosis.
- Verifier: always starts from the candidate head so tests see candidate files.
  Successful verifier worktrees are cleanup eligible after evidence capture;
  failed or malformed verifier worktrees are retained for diagnosis.

The `worktree_registry` table records path, workspace, run, branch, and
lifecycle. Retention planning may remove only `cleanup_eligible` and
`evidence_archived` worktrees; `retained_for_diagnosis` worktrees stay until an
operator explicitly removes them or the policy changes.

## Evidence Archival

Before a non-selected implementer worktree becomes cleanup eligible,
AgentRunway writes `commits.json`, `changed_files.json`, and `worker.json`
under the candidate artifact directory. This preserves auditability after disk
cleanup.

## Checkpointed Run Main

Run main is checkpointed after creation and after every selected candidate merge.
Worker worktrees are created from the latest applicable run-main checkpoint.
Dependent tasks must not start until every declared dependency has a successful
checkpoint. This preserves isolation while ensuring later tasks see accepted
earlier work.

## Checkpoint Dispatch

Runtime dispatch starts workers from run main after the latest successful
checkpoint. Dependent tasks wait until their dependencies have checkpoint rows.
Conflicting file claims, high-risk tasks, serial tasks, broad claims, and
shared resource keys are serialized by the checkpoint scheduler.

## Lazy Worker Worktrees

Worker worktrees are created only after the durable projection places a task in
`safe_wave`. Tasks withheld by blocked dependencies, missing checkpoints, stale
activities, or missing resume handlers must not create mutable worker
worktrees. Successful tasks merge into run-main immediately and create a
`merged:<task_id>` checkpoint before dependent work is released.
