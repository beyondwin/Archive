# CPE vNext Partial Implementation Handoff

Status: partial major runtime rewrite, intentionally stopped and merged for
preservation. This document is not a completion or release claim.

## Merge basis

- Required program base: `144c80b7c326d8979cdea13f32ee177d7934ffdf`.
- Partial implementation head: `dcf8c76134bdc44391fb02fa47374fd201d7f08b`.
- Feature branch: `codex/cpe-vnext-quality-first-workflow`.
- Completed implementation tasks: 8 of 14, plus the pre-task contract alignment.
- Included scope: Plan 1 Tasks 1-4 and Plan 2 Tasks 1-4.
- Not started: Plan 2 Task 5 and all five Plan 3 tasks.
- Credentialed provider/model/network calls: zero.

The branch contains 26 commits after the program base: 7 `feat`, 16 `fix`,
and 3 `docs`. The base-to-head delta is 70 files with 27,721 additions and
5,283 deletions. Large tracked inputs include Graphify projections and the
exact 13-file Canvas source fixture. The substantive Python delta is 23
runtime files (+4,566/-227) and 14 eval files (+4,484/-38).

## Implemented surfaces worth preserving

1. Git-object release trust and tracked release-root validation.
2. Release evidence, review-artifact, closure, and disposition contracts.
3. Immutable workspace-relative `DocumentSet` compilation.
4. Qualified multi-plan `PlanGraph` compilation, Canvas fixture binding,
   ownership authority, checkpoint, and invalidation contracts.
5. Graph-authoritative task contracts, packets, manifests, and plan
   checkpoints.
6. Transition-kernel, phase-executor, evidence-store, and crash-point
   foundations.

These surfaces have focused tests and repeated independent review history.
They should be retained unless a replacement demonstrates a smaller contract
with equal fail-closed behavior.

## Known incomplete and high-risk areas

### Task 4 remains review-blocked

The committed Task 4 head is not a clean transition-kernel cutover. Review at
`dcf8c76` found that the active `run_task_cycle_v4` path called the new helper,
but projected into a temporary dictionary and discarded `_phase_projection`.
Existing `_task_transition`, wait/block/resume, and completion paths remained
the durable authority. The helper also did not yet prove durable external-call
registration before the side effect.

The following committed fixes are valid and should remain:

- unknown phases fail closed;
- `EvidenceStore` is the canonical vNext writer and old direct writers use its
  compatibility adapter;
- intermediate symlink read/write escapes are rejected;
- checkpoint values are structured instead of mixed string/dict values.

The authoritative durable integration was being developed but was not
committed because the user stopped further implementation.

### Preserved uncommitted continuation

The interrupted durable-integration work is preserved in the repository stash
whose message is:

```text
wip: authoritative transition kernel integration paused by user
```

At creation it was `stash@{0}` on `dcf8c76` and changed four files:
`check_transition_kernel_vnext.py`, `kernel.py`, `projector.py`, and
`scheduler.py` (+519/-129). Locate it by message rather than assuming the stash
index remains stable. It had a focused real-Kernel GREEN result for durable
first-pass, repair, failure, wait/resume, and checkpoint replay. It had not yet
implemented or verified the real external-operation registration/crash/replay
matrix, had not run the full skill eval, and must not be applied blindly.

### Other explicit debt

- Two inventory-excluded evals still call the removed
  `compile_run(plan=...)` interface and fail until migrated or retired.
- Additional inventory-excluded v4 fixtures contain schema or initial-state
  expectations already stale at the program base.
- `SKILL.md` and `README.md` have not been aligned with the vNext runtime.
  The skill change protocol therefore remains open.
- Plan 2 Task 5 clean-cut, validation consolidation, old-runtime removal,
  maintained-check inventory, operator docs, verification log closeout, and
  final Graphify refresh are incomplete.
- Plan 3 review deduplication, evidence reuse, prompt slimming, cost-free
  quality comparison, and the program final gate are entirely incomplete.
- No credentialed final proof or subscription sentinel has run.

## Complexity decision register

### Keep

- Git-object trust root and release-evidence bindings.
- Immutable document identities and complete graph-authority hashes.
- Qualified task IDs and graph-bound packet/manifest/checkpoint contracts.
- Exact Canvas bytes as provenance evidence while they remain the public
  representative multi-plan fixture.
- The sole-writer and symlink-safe evidence-store boundary.

### Reduce before adding new behavior

- Consolidate the large natural-language Canvas parser behind one reviewed
  adapter; do not add more fixture-specific branches.
- Collapse repeated graph/contract canonical serializers into one public
  canonical record function.
- Replace review-fix-specific negative tests with invariant-owned maintained
  suites after preserving their mutations.
- Make one durable transition path authoritative before adding more phase
  helpers or projector facades.

### Delete only after a clean replacement exists

- Secondary `run_task_cycle` and successful v4 execution/resume routes.
- Duplicate scheduler phase/verdict branches and temporary projection-only
  adapters.
- Stale inventory-excluded evals or fixtures after their invariant is moved to
  an active vNext maintained check.
- Successful legacy runtime fixtures; retain rejection-only historical
  artifacts required by the cutover contract.

## Safe continuation order

1. Create a new branch from the merged partial head.
2. Inspect the named stash; selectively apply it and re-run the focused
   transition eval before retaining any hunk.
3. Finish real durable command/outcome append and replay through `RunKernel`.
4. Register external operation keys before handlers and test crash/reconcile
   behavior with a counter-based fake operation, never a live provider call.
5. Prove real checkpoint publication and stale-chain rejection using replayed
   Kernel state.
6. Run caller search, targeted scheduler/checkpoint/event/run-diff regressions,
   one full skill eval, and independent review. Do not proceed while Critical
   or Important findings remain.
7. Reassess the total design before Plan 2 Task 5. Prefer deletion and
   consolidation over another compatibility layer.
8. If Task 5 proceeds, align `SKILL.md`, `README.md`, operator docs, maintained
   checks, verification log, and Graphify in the same checkpoint.
9. Start Plan 3 only as a separately confirmed program phase.

## Merge verification

The final merge gate commands and results are recorded in
`skills/kws-codex-plan-executor/docs/verification-log.md`. A successful merge
gate proves the partial snapshot is internally testable; it does not close the
incomplete tasks or risks above.
