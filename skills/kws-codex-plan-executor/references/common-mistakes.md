# Common Mistakes

## Using CPE For A Small Task

CPE is justified by durable, multi-document, interruptible execution. A bounded
same-session change should use direct Superpowers.

## Treating CLI Order As Authority

Repeated spec and plan order is not precedence. Only explicit source
supersession or a recorded answer can resolve incompatible authorities.

## Editing Original Inputs During A Run

Children read immutable snapshots. Changing the source path does nothing until
resume --refresh-inputs creates a new generation.

## Asking The User To Debug Ordinary Failures

Product defects, test failures, review findings, technical choices, safe
refactors, local dependency setup, and interrupted children are standing
autonomy. Preserve evidence and change strategy. Use waiting_authority only for
one of the six allowlisted codes.

## Repeating The Same Failed Strategy

A materially repeated failure requires a fresh investigation and a distinct
strategy key. Do not weaken requirements, delete covering tests, or silently
reuse unusable evidence.

## Redispatching Durable Work

Resume must first reconcile the outbox, indexed artifacts, result, events, and
Git commit. A completed task or review is not launched again merely because the
parent process stopped before its next loop iteration.

## Overlapping Writers

Task, fix, and integration-fix roles share one writer lease. Do not bypass it
with manual worker launch or a second queue engine.

## Trusting A Child Quality Claim

Children cannot write queue state or forge the launcher-owned integration
handoff. Validate result schema, artifact digests, commit ancestry, worktree
cleanliness, audit revision, and terminal verification before completion.

## Repeating Verification

The implementer runs focused checks. A reviewer reads that current-revision
evidence and does not rerun an identical command. The Program Final Integrator
runs the one full verification; CPE does not run it again.

## Treating completed As A Pass Verdict

completed means a terminal artifact was durably published. Read that artifact's
quality_verdict, verification exit, auditor verdicts, and limitations.

## Deleting Mapping Attempts By Age

Never delete evidence selected by map.generation_created. Unselected
Program Mapper attempts are already bounded to one per generation
through durable index tombstones. Removing files manually, changing the cap by
age, or bypassing strict partial-group identity checks can corrupt replay.

## Resuming Schema 3 With CPE 4

Inspect is read-only. Resume intentionally returns
legacy_run_requires_historical_cpe. Choose the historical Git revision
explicitly instead of converting local run bytes.
