# CPE v3 Integrity Closure Design

**Status:** Approved

**Date:** 2026-07-10

**Target:** Preserve the event-sourced v3 architecture and restore trustworthy
deterministic readiness.

## Summary

CPE v3 has a strong foundation: an immutable manifest, hash-chained events,
atomic state projection, fixed model routes, and isolated worktrees. The current
`3.0.0` release candidate is not yet a trustworthy deterministic executor.
Public execution can report completion after negative or stale review evidence,
task ownership is not enforced from the actual per-attempt diff, normal blocked
runs cannot resume, task packets are neither consumed nor integrity-checked,
and major release evals bypass the public CLI or return constant success.

This design keeps v3 and closes those failures as one integrity-first patch
release. It introduces revision-bound evidence, typed verdicts, real Git delta
capture, hashed task packets, phase-aware recovery, one canonical validator,
and public-CLI integration and mutation tests.

While the work is open, `3.0.0` records
`integrity-closure-pending; paid-live-pending`. The next release is `3.0.1`.
It may record `deterministic-ready; paid-live-pending` only after all cost-free
gates in this document pass.

## Evidence Basis

The design follows a read-only audit of `origin/main` at
`93c7730df45ab661df23f420b7b145e0aa5579df`.

These checks passed:

- `./evals/run.sh`
- Python compile and Bash syntax
- release and documentation contract checks
- repository-level `bun run check`
- `git diff --check`
- Graphify freshness with `fresh=true`

The same audit reproduced these release blockers:

1. A critical task-review finding and missing verification evidence were
   ignored; final review then changed accepted content from `good` to `bad`, and
   scheduler plus validator still reported completion.
2. A blocked task failed resume with
   `ValueError: task transition from mismatch`.
3. One task changed another task's claimed file and the run still validated.
4. A completed run's task packet was modified and validation still passed.
5. The approved v3 plan failed the public parser with
   `task_1 has no Files block`.
6. Public export broke its one-fenced-block contract on a real plan containing
   nested fences.
7. Nine wired evals returned hard-coded passing payloads without exercising the
   named behavior.
8. The public headless result did not satisfy its tracked schema.
9. Advertised repair actions recorded audit entries without repairing projected
   attempt or evidence state.

The paid live model matrix was not run. Paid evidence is a separate follow-up
and cannot explain or waive these deterministic failures.

## Goals

1. Make false completion impossible when review, verification, evidence, diff
   scope, model attestation, or state integrity is unresolved.
2. Bind every successful verdict to the exact current worktree revision.
3. Enforce each task's claims from CPE-measured Git deltas.
4. Make task packets immutable, manifest-bound, and mandatory worker inputs.
5. Resume blocked and interrupted work through explicit phase-aware events.
6. Distinguish healthy incomplete state from integrity drift.
7. Test public `run`, `resume`, `export`, `headless`, validation, repair, and
   inspection paths directly.
8. Derive release metadata from current evidence.

## Non-Goals

- Adding model routes, aliases, profiles, or fallbacks.
- Changing Sol/high core or Terra/high read-only scout routing.
- Integrating CPE with Waygent.
- Resuming, repairing, or migrating v2 state.
- Adding a graphical operator interface.
- Executing the paid live matrix during this closure.
- Automatically applying a completed worktree to the source checkout.
- Allowing workers to create commits, rewrite history, or clean a worktree.

## Principles

1. Evidence exists before a status transition can rely on it.
2. CPE-owned filesystem, process, event, and command evidence outranks worker
   self-report.
3. A later write invalidates earlier acceptance and verdict evidence.
4. Review and verification are read-only; requested changes return to repair.
5. Resolved failures remain historical without remaining active blockers.
6. Integrity validation and completion validation are separate profiles.
7. Public paths, not self-fulfilling test runners, are the integration subject.
8. Release claims cannot be stronger than the verified evidence bundle.

## Architecture

### PlanCompiler

`PlanCompiler` owns read-only invocation resolution and preflight. It:

- accepts current Superpowers writing-plans tasks and explicit CPE task blocks;
- requires file claims, dependencies, acceptance commands, and explicit
  `spec_refs` when a spec exists;
- validates allowed and forbidden paths;
- classifies destructive, migration, release, and external-write commands for
  operator review;
- verifies dependencies and model-launch capability;
- audits current Superpowers plan, TDD, review, and completion capabilities;
- performs no worktree or durable run mutation before all blocking checks pass.

The approved CPE v3 plan becomes a permanent golden parse case. A future plan
format change must update that fixture before compatibility is claimed.

### PacketStore

`PacketStore` is the only task-packet builder and verifier. Legacy packet
builders, heuristic full-spec mapping, and parallel packet schemas are removed.
It returns canonical bytes and digest metadata to `RunKernel`; only
`RunKernel` may persist a packet and append it to the manifest index.

Each packet contains:

```json
{
  "schema_version": "3.1",
  "task_id": "T1",
  "task": {},
  "spec_sections": [],
  "execution_contract": {
    "scope": "bounded task scope",
    "files_to_inspect": [],
    "allowed_edits": [],
    "forbidden_edits": [],
    "acceptance_command_or_honest_substitute": "exact command"
  },
  "required_methods": ["using-superpowers", "test-driven-development"],
  "role_policy": {},
  "evidence_requirements": [],
  "source_hashes": {}
}
```

Packets use exclusive creation under `artifacts/task-packets/`. The manifest
indexes task ID, relative path, media type, and digest. Implementation, review,
verification, repair, and final review receive the exact packet reference and
digest. Missing, changed, or unindexed packets block dispatch and completion.

### AttemptController

`AttemptController` owns role policy, process launch, before/after evidence, and
result validation.

| Role | Filesystem | Verdict | Product writes |
| --- | --- | --- | --- |
| scout | read-only | no | no |
| implementation | workspace-write | no | yes |
| task_review | read-only | yes | no |
| verification | read-only | yes | no |
| repair | workspace-write | no | yes |
| final_review | read-only | yes | no |

Before each write attempt, CPE records HEAD, worktree status, cumulative patch
digest, and revision. After the attempt, CPE computes the real Git delta and
compares it with that task's allowed and forbidden claims. Worker
`changed_files` remains diagnostic only.

Workers cannot run `git commit`, `git reset`, or `git clean`, write durable run
artifacts, or touch the source checkout. CPE stores immutable patch evidence
instead of worker commits.

### RunKernel

`RunKernel` is the only durable state writer. It owns:

- immutable input and packet indexes;
- hash-chained event append;
- typed transition validation;
- atomic projection;
- blocker lifecycle;
- revision allocation;
- completion transition authorization.

Models and helper scripts never edit manifest, events, evidence indexes, or
state snapshots.

### CanonicalValidator

The validator exposes two profiles from shared checks:

- `validate_integrity(run_dir)` checks schema, manifest and packet hashes,
  event chain, replay parity, evidence, worktree identity, attempt structure,
  and Git scope for any lifecycle state.
- `validate_completion(run_dir)` additionally requires completed tasks,
  current-revision acceptance and passed verdicts, repository checks, no active
  blockers, and a complete audit.

Scheduler completion, CLI exit, reconciliation, repair, inspection, and the
standalone validator call these shared functions. They do not duplicate
completion rules.

### RecoveryEngine

`RecoveryEngine` applies typed compensating events, never direct state patches.
It owns interrupted-attempt detection, blocker resolution, retry scheduling,
hash-valid evidence reconnection, and snapshot or report rebuilds.

Each repair declares an expected projection delta. If replay does not produce
that delta, the repair returns `applied=false` and leaves the blocker open.

### PublicCLI

`PublicCLI` owns stable JSON and exit semantics. It:

- turns expected runtime failures into structured results instead of raw
  tracebacks;
- validates headless output against the tracked schema;
- calls canonical completion validation before exit zero;
- uses one fresh-session template for prompt and handoff;
- exports paths and hashes instead of embedding a complete plan;
- chooses a quoted, content-derived heredoc delimiter absent from the payload;
- chooses an outer Markdown fence longer than any inner backtick run;
- creates no worktree or run artifacts in export modes.

## Sources Of Truth

The authority chain is:

```text
source paths and initial hashes
  -> immutable input snapshots
  -> immutable manifest and packet index
  -> hash-chained events and immutable evidence
  -> rebuildable state projection
  -> disposable inspection reports
```

The run directory contains:

```text
~/.codex/orchestrator/<run_id>/
  run_manifest.json
  events.jsonl
  state.json
  artifacts/
    inputs/
    task-packets/
    evidence/
    patches/
    prompts/
    reports/
```

Plan, spec, and docs are read once and copied to content-addressed internal
snapshots. Runtime uses those snapshots. A later source-plan edit is reported
as source drift but does not make an historical run unreplayable.

## Revision-Bound Evidence

`worktree_revision` starts at zero and increments once for every non-empty delta
observed after an implementation or repair attempt, even when that delta is
out of scope or the attempt later fails. Recording the revision invalidates
older success evidence before policy or acceptance decisions run. An invalid
delta opens a blocker; it is never hidden by retaining the previous revision.

Acceptance and verdict artifacts record:

```json
{
  "task_id": "T1",
  "worktree_revision": 3,
  "worktree_patch_sha256": "digest",
  "packet_sha256": "digest",
  "started_at": "ISO-8601 timestamp",
  "completed_at": "ISO-8601 timestamp"
}
```

A later write makes older verdicts stale. Stale evidence remains visible but
cannot satisfy completion.

## Typed Verdicts

Review and verification require one verdict:

- `passed`
- `changes_requested`
- `blocked`
- `inconclusive`

Schema rules are exact:

- critical findings or required missing evidence cannot coexist with `passed`;
- `changes_requested` requires an actionable finding;
- `blocked` requires an owner and resume condition;
- `inconclusive` requires a bounded next evidence action;
- a verdict from another revision is stale;
- scout and write roles cannot issue verdicts.

Final review is read-only. Changes requested there schedule repair and rerun
acceptance, task review, verification, and final review on the new revision.

## Event And Projection Model

The event vocabulary includes:

```text
run.status_changed
task.status_changed
task.retry_scheduled
attempt.started
attempt.completed
verdict.recorded
evidence.attached
worktree.revision_recorded
blocker.opened
blocker.updated
blocker.resolved
repair.applied
context.updated
completion.recorded
```

`state.json` projects lifecycle, current task and revision, tasks, attempts,
active blockers, blocker history, artifacts, packets, repairs, context health,
completion audit, usage totals, and last event.

Resolved blockers leave `active_blockers` and remain in `blocker_history`.
Failed attempts remain inspectable and require failure evidence. Only successful
core attempts require verified actual-model attestation.

## Execution Flow

### New Run

1. Resolve paths and explicit options.
2. Compile plan and explicit spec mappings.
3. Run dependency, model, method, command, and dirty-scope preflight.
4. Snapshot inputs and stage manifest plus packet index privately.
5. Allocate run ID and create the isolated worktree.
6. Atomically publish the initialized run and first event.
7. Dispatch only after manifest, packet, worktree, and projection integrity pass.

If initialization fails after worktree creation, CPE removes only the newly
created worktree and branch after verifying run ID and source HEAD. It never
deletes a pre-existing user path or worktree.

### Task Loop

1. Verify the current packet.
2. Run optional bounded read-only scouts.
3. Record the pre-write Git basis.
4. Run implementation or repair.
5. Compute the real task delta.
6. Increment revision and store patch evidence for every non-empty delta.
7. Validate the delta against the current task's claims and fail closed on a
   violation.
8. Run deterministic acceptance.
9. Run read-only task review.
10. Run read-only verification.
11. On changes requested, schedule bounded repair and repeat from step 3.
12. On passed verdicts, complete the task at the current revision.

### Completion

1. Confirm all tasks are complete.
2. Run repository commands on the final revision.
3. Run read-only whole-diff final review.
4. Route requested changes through repair, invalidate revision-bound evidence,
   and loop back to repository commands in step 2.
5. Reconcile integrity.
6. Build the completion audit from indexed evidence.
7. Run canonical completion validation.
8. Append completion only when validation passes.
9. Revalidate before public exit zero.

## Error Handling

Every failure records category, root-cause key, recoverability, owner, evidence,
and next action.

| Category | Default behavior |
| --- | --- |
| `preflight` | Block before worktree creation |
| `environment` | Block with exact preparation guidance |
| `transient` | Retry the same root cause at most twice |
| `implementation` | Schedule bounded repair and fresh review |
| `review` | Repair on changes requested; block unresolved verdicts |
| `verification` | Preserve command evidence and schedule repair |
| `policy_violation` | Block immediately without automatic mutation |
| `state_integrity` | Stop execution and allow reconciliation only |
| `operator_review` | Wait for explicit operator action |

Public failure output includes status, run ID, category, summary,
recoverability, next action, and evidence references.

## Resume And Repair

Blockers follow:

```text
blocker.opened -> blocker.updated -> blocker.resolved
```

Resolution requires indexed evidence and a valid retry phase.
`task.retry_scheduled` records phase, root cause, revision, and evidence.

Resume behavior is deterministic:

- unresolved operator blocker: remain blocked;
- interrupted implementation: schedule new implementation;
- failed acceptance or review changes: schedule repair;
- interrupted verification: rerun acceptance first;
- missing worktree: block as workspace precondition;
- invalid event, manifest, packet, or evidence digest: reject resume.

Allowed repair actions are snapshot and report rebuild, provable stale-attempt
interruption, unique hash-valid evidence reconnection, evidence-backed blocker
resolution, and bounded retry scheduling.

Repair cannot change product files, hashes, model attestation, success evidence,
failed state to completed, a damaged event chain, or any v2 run.

## Verification Strategy

### L0: Static Contract

- Python compile and Bash syntax
- JSON schemas and Markdown links
- docs, `SKILL.md`, and public help consistency
- maintained-eval manifest
- public command smoke tests

### L1: Module Behavior

- manifest, packet, event, evidence, and input digests
- transitions and projection
- verdict consistency
- task-specific Git delta calculation
- blocker lifecycle
- integrity and completion profiles

Wired checks cannot be constant-success stubs. A meta-check requires each wired
checker to invoke a production module, public CLI, or real fixture assertion.
V2-only checks are ported or deleted rather than left unwired and failing.

### L2: Public CLI Integration

Tests enter through the public CLI and inject a deterministic fake Codex
executable at the provider boundary. They do not bypass plan compilation,
packets, events, resume, reconciliation, repair, or output serialization.

Cases cover the current writing-plans shape, preflight outcomes, interruption
at every phase, packet delivery and mutation, task-specific diffs, nested export
fences and delimiter collisions, headless schema, and consumer parity.

Fixture inputs and expected outcomes are separate. The runner cannot read the
oracle to decide which files to create or whether to block.

### L3: Fault And Mutation

Release regressions cover:

- negative review or missing evidence followed by false completion;
- final review changing accepted code;
- cross-task writes;
- packet, evidence, snapshot, and event mutation;
- scheduler and validator disagreement after recovery;
- blocked resume failure;
- repair with no projected effect;
- unexpected worktree HEAD changes;
- stale-revision completion evidence.

Every injected fault must make the suite fail closed.

### L4: Repository Closeout

The cost-free closeout bundle is:

```bash
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
bun run check
git diff --check
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . --update-ran --output /tmp/cpe-v3-integrity-graphify.json
```

Closeout also validates public result schemas and a clean tracked worktree.

### L5: Paid Live Migration

Paid execution is a follow-up after L0-L4. Provider runner and aggregator remain
separate. A paid run requires same-session approval, four treatments, eight
cases, and the `$50` cap. Without a current passing external report digest,
`release_ready=false` remains mandatory.

## Release State

1. Start with `3.0.0` at
   `integrity-closure-pending; paid-live-pending` and `release_ready=false`.
2. Record failing P0 and P1 regressions before implementation fixes.
3. Pass L0-L4 on the final implementation commit.
4. Release `3.0.1` as `deterministic-ready; paid-live-pending`.
5. Make no live-quality, cost-efficiency, or context-reduction completion claim
   before L5 passes.

The verification log records version, final commit, commands, exit codes,
passing counts, skipped paid gates, and residual risk. Release validation checks
those fields rather than a date string.

## Documentation Impact

Implementation keeps these surfaces aligned:

- `SKILL.md`, `README.md`, `ARCHITECTURE.md`, and `HISTORY.md`
- state, event, execution, mode, packet, repair, inspection, and command refs
- fresh-session prompt and headless schema
- operator and Korean mental-model guides
- eval coverage and verification docs
- release process, risks, decisions, and verification log
- Graphify output

Stale helpers, dead tests, and duplicate packet or prompt paths are removed or
marked historical-only. Active docs cannot name removed behavior as executable.

## Acceptance Criteria

1. V3 remains the only active CPE runtime.
2. `3.0.0` is not described as deterministic-ready during closure.
3. The current writing-plans shape compiles through public CPE.
4. Every packet is manifest-indexed, digest-verified, and consumed by all roles.
5. Workers cannot alter durable state or Git history.
6. Review, verification, and final review are read-only.
7. Critical findings, missing evidence, and non-passed verdicts block completion.
8. Acceptance and verdicts match the current worktree revision.
9. A later write invalidates earlier success evidence.
10. Real attempt deltas stay inside the current task's claims.
11. Cross-task writes fail before the next task begins.
12. Blocked and interrupted tasks resume through explicit retry phases.
13. Resolved blockers leave active state but remain in history.
14. Repair verifies its declared projection delta.
15. Healthy running state can pass integrity without passing completion.
16. Scheduler, validator, reconciler, repair, inspector, and CLI agree.
17. Export is one valid fenced block with a collision-free delimiter and no run
    artifacts.
18. Headless output validates against its schema.
19. Public execution cannot return zero before canonical completion validation.
20. Every maintained eval executes real behavior and is wired.
21. All reproduced completion, scope, packet, resume, and repair failures fail
    closed.
22. L0-L4 pass on final `3.0.1` with fresh Graphify and a clean tracked tree.
23. Paid live remains pending without an approved external report.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Event expansion causes replay drift | Version payloads and preserve historical v3 fixtures |
| Diff capture adds cost | Hash cumulative state and store patches only at write boundaries |
| Read-only review cannot fix code | Route changes through repair and refresh evidence |
| Plans contain commit steps | Treat them as orchestration metadata and forbid worker commits |
| Source plan changes | Run from internal snapshots and report source drift separately |
| Resume selects the wrong phase | Require explicit evidence-backed retry events |
| Harness becomes self-fulfilling | Separate runner inputs from oracle assertions and mutation-test it |
| Scope expands into model evaluation | Keep paid execution outside L0-L4 |

## Planning Boundary

The implementation plan must use independently reviewable tasks with exact
files, RED and GREEN commands, packet and event migrations, public-CLI
fixtures, docs updates, Graphify evidence, and release closeout. It must not
start paid live execution or add model routes.
