# Incident Report: Codex Plan Runner Replays Completed Work in New Runs Instead of Preserving Recoverable Progress

## Document status

| Field | Value |
| --- | --- |
| Status | Confirmed systemic recovery and run-lineage defect; fix not yet implemented |
| Suggested severity | High |
| Affected component | `skills/kws-codex-plan-runner` |
| Affected release | `1.0.0` |
| Runner repository HEAD inspected | `0f657980ccef445b3693180a3cf1a5d8cd67b574` |
| Incident date | 2026-07-24 |
| Evidence reviewed | 2026-07-24 |
| User-visible outcome | Repeated `codex-plan/<new-run-id>` branches restart the same ordered plan at Task 0 |
| Confirmed repeated scope | Calm Craft Tasks 0 and 1 were independently replayed after prior successful commits and receipts |
| Product data-loss status | No confirmed file loss; completed work and evidence are stranded across runner branches |
| Remote exposure | No merge, push, or deploy observed |
| Integration status | `not_observed` |

## Issue title suitable for a tracker

> Codex plan runner has no progress-preserving recovery or successor protocol,
> so terminal integrity errors cause duplicate runs, branches, commits, and
> verification replay from Task 0

## Executive summary

The Codex plan runner promises durable recovery:

- one ordered plan sequence;
- one isolated worktree and branch;
- durable state, Git HEAD, task ledger, and receipts as authority;
- same-run `resume` for recoverable interruption or failure;
- exit `0` only at `ready_for_integration`.

The implementation does not provide a safe continuation path after a run is
classified as a terminal integrity failure, even when:

- the implementation branch contains clean, useful commits;
- completed task ledger entries exist;
- verification receipts exist;
- the failure was caused by host/runtime behavior rather than product content;
- the exact candidate HEAD and worktree still exist.

The only public commands are:

```text
run
resume
inspect
```

`resume` correctly fails closed when the immutable Git contract does not match.
However, there is no:

- explicit audited repair command;
- duplicate-intent detection at `run`;
- run-family or supersession model;
- progress-preserving successor command;
- safe candidate adoption protocol;
- operator-visible warning that an equivalent run already exists.

As a result, the practical workaround has been to call `run` again. Every call
generates a new UUID, branch, worktree, empty task ledger, and provider session
from the source repository's current HEAD. The new provider therefore starts
the ordered plan at Task 0 and independently recreates work already committed
and verified in a previous runner branch.

This is not ordinary retry behavior. It is loss of durable execution continuity.
The source files may still exist, but the controller discards their execution
identity and makes the provider repeat them.

## Bottom-line ownership assessment

This incident belongs to `kws-codex-plan-runner`.

An operator or agent should prefer `resume`, but command discipline alone
cannot fix this defect:

1. a terminal integrity state rejects ordinary resume;
2. the runner offers no narrower repair operation;
3. `run` does not detect an equivalent existing run;
4. `run` always creates a new branch at the source workspace HEAD;
5. the new state has no lineage or trusted progress import;
6. the provider is correctly instructed to execute the plan from its first
   pending task, which is Task 0 in the new empty ledger.

The repeated new runs were triggered by separate sandbox, provider, and
protected-ref defects. Those triggers must be fixed. The absence of a
progress-preserving recovery protocol is an additional controller defect that
magnifies every trigger into duplicate work.

## Confirmed incident chain

All observed runs used:

```text
source repository:
/Users/kws/source/web/canvas-clone

source commit:
4d0153c3ec347dbdaff32642426c466c5b7a607d

spec:
docs/superpowers/specs/2026-07-24-calm-craft-responsive-reference-integration-design.md

plan:
docs/superpowers/plans/2026-07-24-calm-craft-responsive-reference-integration.md
```

The runner created seven durable run directories for the same implementation
intent:

| Run suffix | Durable outcome | Progress before stop |
| --- | --- | --- |
| `21fbe848…` | `failed` | Dirty partial worktree stranded without an exact checkpoint |
| `097667ba…` | `blocked` | Task 0 implementation existed; helper verification blocked |
| `fc6482a5…` | `failed` | Task 0 running with two receipt artifacts; protected-ref failure |
| `5df1b73c…` | `resumable` | Task 0 commit existed; controller was stopped |
| `4a0eb1db…` | `failed` | Provider result shape failure before durable task completion |
| `24101285…` | `failed` | Tasks 0 and 1 reported done; Task 2 running |
| `eb8347dd…` | `running` when inspected | Tasks 0 and 1 independently reported done again; Task 2 running |

The branch history visibly contains repeated subjects:

```text
test: lock Calm Craft reference integrity
test: enforce Calm Craft surface coverage
refactor: expose product content catalogs
```

The repeated subjects are not merely multiple attempts within one runner
branch. They are commits on separate `codex-plan/<run-id>` branches created
from the same source commit.

### Direct durable evidence

Run `24101285…` recorded:

```json
{
  "status": "failed",
  "failure": {
    "reason_code": "state_integrity_failed",
    "detail": "protected ref mutation detected"
  },
  "task_ledger": [
    {"task_id": "task-0", "status": "reported_done"},
    {"task_id": "task-1", "status": "reported_done"},
    {"task_id": "task-2", "status": "running"}
  ]
}
```

Its recorded candidate sequence included:

```text
4d0153c3ec347dbdaff32642426c466c5b7a607d
5a2be2995d7b4f810f368d8db8d733b2a9d2dbd2
```

Instead of continuing that execution lineage, run `eb8347dd…` started again
from `4d0153c3…` and independently reached:

```text
fab3f0dccf2e6c9d8a437ee76955c4fb47aa7469
a444f12e406f7155add98f79f4a604bdba51e54a
```

Its ledger again recorded Tasks 0 and 1 as completed work. No durable state
relationship identifies `eb8347dd…` as a successor of `24101285…`, and no
receipt provenance connects the replayed tasks.

## User impact

### Confirmed impact

- Multiple runner-owned branches represent the same implementation intent.
- Task 0 was implemented or attempted repeatedly.
- Task 1 was committed and verified on more than one branch.
- Task 2 work exists on more than one branch.
- Provider time, model tokens, local CPU, and verification time were spent
  replaying completed scope.
- Independent commits for the same task have different object IDs.
- Reviewers cannot treat the newest branch as automatically containing the
  strongest version of every earlier attempt.
- Receipts and task ledgers are fragmented across run roots.
- Git history and visual branch tooling show misleading parallel lines of work.
- The user cannot easily tell which branch is authoritative.
- Repeated replay increases the chance of semantic drift between attempts.
- A long plan may repeatedly fail near the same host boundary and never reach
  later tasks, despite substantial correct work on disk.

### Potential impact

- A later replay may accidentally omit a fix present in an earlier attempt.
- Independent reimplementation may produce behavior differences that are hard
  to detect from identical commit subjects.
- A provider may consume stale or contradictory context from multiple branches.
- Manual cherry-picking may combine commits whose receipts were produced for
  different candidate HEADs.
- An operator may delete a branch believed to be obsolete while it contains the
  only copy of a useful partial implementation.
- A broad cleanup may remove forensic evidence needed to design a safe repair.

## Expected behavior

For one approved implementation intent:

1. `run` creates one run, branch, worktree, and immutable input snapshot.
2. Ordinary defects and provider failures recover inside that run.
3. Interruptions resume the exact sealed partial worktree.
4. A host-only, provably benign integrity delta is repaired through an
   explicit audited same-run operation.
5. If same-run repair is impossible, a successor run preserves the exact clean
   candidate commits and records lineage instead of replaying Task 0.
6. A new unrelated run is created only when inputs, source authority, or the
   requested execution intent truly changes.

The default response to failure must be:

```text
resume -> bounded retry -> audited repair -> progress-preserving successor
```

It must not be:

```text
run -> new UUID -> new branch -> Task 0 replay
```

## Current implementation analysis

### New run creation is unconditional

`PlanRunner.create_run()`:

1. validates arguments;
2. computes a new run ID with `_run_id()`;
3. constructs `codex-plan/<run-id>`;
4. reads the source workspace HEAD;
5. snapshots inputs;
6. creates an empty state store;
7. creates a new Git worktree and branch;
8. executes the first plan.

`_run_id()` always appends `uuid.uuid4()`. There is no search for an existing
run with the same:

- Git common directory;
- source commit;
- input snapshot digest;
- ordered spec and plan identities;
- sandbox/model execution contract.

### A new run starts from the source workspace, not prior progress

`create_run()` calls `_source_head(workspace)` and then:

```text
git worktree add -b <new-branch> <new-worktree> <starting-head>
```

It has no argument for an audited predecessor candidate. Even a clean,
committed, reviewed candidate on a prior runner branch is ignored.

### A new state store has no lineage

`StateStore.create()` records the new run and repository identity but does not
record:

- predecessor run ID;
- superseded/superseding relationship;
- inherited candidate HEAD;
- adopted task ledger;
- receipt provenance;
- reason the predecessor could not resume.

The controller therefore cannot distinguish a legitimate independent run from
an accidental replay of the same intent.

### Exit 65 is safe but operationally terminal

`PlanRunner._execute()` catches `ValueError`, records
`state_integrity_failed`, and returns exit `65`. That fail-closed behavior is
necessary for real Git or state corruption.

The public CLI provides no integrity-specific recovery command. `resume`
rechecks the same immutable contract and rejects the same mismatch. The only
remaining callable path is a new `run`, which loses continuity.

### The skill contract is incomplete at this boundary

`SKILL.md` says:

- durable state, Git HEAD, ledger, and receipts are canonical;
- same-plan resume is preferred;
- exit `65` means state, Git, receipt, or helper integrity failure.

It does not define:

- how to distinguish repairable host drift from real product-state mutation;
- how to preserve progress when exit `65` is caused by a runner defect;
- whether equivalent new runs must be rejected;
- how to link a necessary successor run;
- how completed tasks and receipts are revalidated after succession.

The documented recovery model ends precisely where the repeated replay begins.

## Root causes

### Primary root cause: no audited same-run repair surface

The controller has enough durable material to validate narrowly scoped repair
in some cases, but exposes no command that can:

- require the exact failed state revision;
- confirm no live controller/provider;
- compare exact HEAD, tree, branch, and porcelain digests;
- classify a bounded external delta;
- record immutable before/after evidence;
- update only the explicitly repairable contract field;
- resume the same run.

### Contributing cause: no equivalent-run admission control

`run` does not ask whether the same implementation intent already has:

- a running run;
- a resumable run;
- a blocked run;
- a failed run with useful committed progress;
- a ready-for-integration run.

It therefore permits unlimited equivalent branches.

### Contributing cause: no progress-preserving successor protocol

Some integrity failures are intentionally non-repairable. The runner still
needs a safe last-resort path that carries committed progress forward without
pretending the predecessor remained valid.

### Contributing cause: no run-family visibility

State, `inspect`, and error output do not show that multiple runs share one
input/source identity. Operators see separate UUIDs rather than one execution
family with a clear authoritative member.

### Contributing cause: provider task replay is locally correct

Given a new empty ledger, the provider is correct to begin at Task 0. Prompt
changes cannot solve missing controller lineage. The controller must provide a
trusted progress contract before the provider can safely skip completed tasks.

## Required fix 1: equivalent-run admission control

Before generating a UUID or creating state, `create_run()` must compute an
execution-intent key:

```text
sha256(
  format version
  + git common directory identity
  + source commit
  + ordered input snapshot digest
  + provider
  + sandbox
  + model identity
)
```

It must scan bounded state metadata for matching runs.

### Default decisions

| Existing matching state | Required `run` behavior |
| --- | --- |
| `running` or `recovering` | Reject; report live matching run ID |
| `resumable` | Reject; instruct exact same-run `resume` |
| `blocked` | Reject; instruct exact same-run `--retry-blocked` |
| `failed` without proven terminal integrity | Reject; instruct exact same-run `--retry-failed` |
| `failed` with terminal integrity and useful progress | Reject; require repair or explicit successor |
| `ready_for_integration` | Reject duplicate intent and report candidate HEAD |
| No match | Create a new independent run |

The error must be machine-readable, for example:

```json
{
  "status": "blocked",
  "reason_code": "matching_run_exists",
  "matching_run_ids": ["..."],
  "recommended_action": "resume"
}
```

Do not silently select a run. The caller must use the exact returned run ID.

### Concurrency requirements

Admission control and run creation must be serialized per execution-intent key.
Two controllers launched concurrently must not both pass the scan and create
equivalent runs.

Use a private lock outside any candidate worktree, validate lock ownership, and
re-scan after acquisition. Bound stale-lock recovery and record it.

## Required fix 2: explicit same-run forensic repair

Add a public command with a narrow contract, for example:

```text
runner repair \
  --run-id RUN_ID \
  --expected-revision REVISION \
  --repair-kind volatile-codex-turn-refs
```

This command must not be a general “accept current state” switch.

### Mandatory preconditions

- exact run ID and state revision;
- status is terminal integrity failure;
- no live controller, provider, helper, or descendant;
- run lock can be exclusively acquired;
- state digest chain is valid;
- input snapshots are unchanged;
- source repository and Git common directory match;
- registered worktree and assigned branch match;
- candidate HEAD, ancestry, tree digest, and porcelain digest match the last
  sealed observation;
- all product-protected refs match;
- every allowed delta belongs to the exact repair-kind allowlist;
- no symlink, path escape, non-regular file, or unbounded artifact;
- explicit operator authorization.

### Repair output

The command must write an immutable artifact containing:

- repair ID and timestamp;
- caller-selected repair kind;
- expected and actual state revision;
- old and new bounded observations;
- created, updated, and deleted ref entries;
- product-protected-ref equality proof;
- worktree identity proof;
- state digest before and after;
- runner executable identity;
- authorization provenance.

Only after that artifact is durable may state become `resumable`.

## Required fix 3: progress-preserving successor

If same-run repair is impossible but the predecessor has a clean committed
candidate, add an explicit last-resort command:

```text
runner succeed \
  --from-run PREDECESSOR_RUN_ID \
  --expected-revision REVISION \
  --strategy-note "why same-run repair is impossible"
```

The final command name may differ, but it must be distinct from ordinary
`run`.

### Successor safety contract

The successor may be created only when:

- the predecessor has no live processes;
- its durable state and artifacts are readable;
- its input snapshot digest is valid;
- the source repository and Git common directory are unchanged;
- the predecessor candidate is a descendant of the sealed source commit;
- the predecessor candidate worktree is clean;
- the candidate commit objects still exist;
- no protected product refs were changed;
- there is no unsealed dirty work to adopt;
- the successor uses the same immutable specs and plans;
- the lineage does not create a cycle.

### Git behavior

Create the successor branch at the predecessor's validated candidate HEAD, not
at the source workspace HEAD:

```text
source commit ---- Task 0 ---- Task 1 ---- candidate
                                      \
                                       successor branch starts here
```

The predecessor branch remains unchanged for forensic evidence.

### Ledger behavior

Do not blindly mark inherited tasks as fully verified.

Import each task as one of:

```text
inherited_committed_pending_review
inherited_receipt_reusable
inherited_receipt_stale
```

A receipt is reusable only if its complete identity remains valid, including:

- candidate HEAD;
- exact command and argv;
- input digest;
- executable identity;
- environment contract;
- producer version;
- artifact digest.

Otherwise rerun verification without reimplementing the task.

The provider packet must clearly state:

- predecessor run and candidate;
- inherited commits;
- which tasks require review only;
- which receipts are reusable;
- the first task requiring implementation.

### Lineage state

Add immutable fields such as:

```json
{
  "execution_intent_digest": "<digest>",
  "lineage": {
    "predecessor_run_id": "<run-id>",
    "predecessor_revision": 13,
    "predecessor_candidate_head": "<sha>",
    "succession_reason_digest": "<digest>",
    "inherited_artifact_manifest_digest": "<digest>"
  }
}
```

The predecessor should receive a separate immutable artifact pointing to the
successor. Do not rewrite historical state in place if that violates the
existing digest chain.

## Required fix 4: run-family inspection

Extend `inspect` or add a read-only `related` command:

```text
runner related --run-id RUN_ID
```

It should report:

- execution-intent digest;
- every matching run;
- lifecycle and candidate HEAD;
- predecessor/successor edges;
- completed task count;
- receipt count;
- authoritative active member;
- safe next command.

This removes the need to infer authority from a Git graph screenshot.

## Required fix 5: update the skill contract

`SKILL.md` must explicitly state:

1. never create a new equivalent run merely because `resume` returns exit
   `65`;
2. inspect and classify the integrity delta first;
3. use an audited same-run repair when the delta is proven repairable;
4. use an explicit progress-preserving successor only when repair is
   impossible;
5. never silently adopt dirty work;
6. never replay completed tasks when their validated commits can be inherited;
7. a fresh independent run requires a different execution-intent key or an
   explicit supersession contract.

The quick-reference table should add the precise repair/successor routing for
exit `65`.

## State and schema changes

Add a new state format version rather than silently extending old semantics.

Suggested additions:

```text
execution_intent_digest
ref_policy_version
lineage
repair_artifact_refs
inherited_task_ledger
inherited_receipt_manifest
```

### Compatibility

- old runs remain inspectable;
- old immutable state is not automatically rewritten;
- new admission control can still detect equivalent old runs by deriving an
  intent digest from validated existing fields;
- old runs require explicit repair/successor commands;
- no old receipt is reused unless its full identity validates under the new
  code;
- `ready_for_integration` remains impossible with unresolved inherited review
  obligations.

## Failure classification changes

Do not use `state_integrity_failed` as a single undifferentiated terminal.

Classify at least:

```text
repairable_host_ref_drift
repairable_provider_protocol_failure
unsealed_dirty_candidate
product_protected_ref_mutation
state_digest_corruption
worktree_identity_corruption
artifact_or_receipt_corruption
```

The classification must not weaken fail-closed behavior. It determines which
explicit recovery command may be considered, not whether validation is skipped.

## Required deterministic tests

### Admission control

1. matching running run blocks new creation;
2. matching resumable run returns exact resume guidance;
3. matching blocked run returns retry-blocked guidance;
4. matching failed run returns retry-failed, repair, or successor guidance;
5. matching ready run reports candidate and blocks duplication;
6. different input order creates a different intent;
7. different source commit creates a different intent;
8. concurrent equivalent `run` calls create at most one run;
9. corrupt unrelated state does not cause unbounded scanning or unsafe bypass.

### Same-run repair

10. exact allowed volatile-ref delta repairs successfully;
11. product branch, tag, remote, stash, original, or unknown-ref delta rejects;
12. wrong revision rejects;
13. live controller rejects;
14. HEAD, tree, porcelain, branch, ancestry, or common-dir drift rejects;
15. symlink, path escape, special file, oversized delta, or invalid ref rejects;
16. repair artifact is immutable and bound to before/after state digests;
17. repaired run resumes at its existing task rather than Task 0.

### Progress-preserving successor

18. clean committed candidate becomes the successor start HEAD;
19. dirty unsealed candidate rejects;
20. different inputs, source repository, or Git common directory reject;
21. lineage cycles reject;
22. inherited task commits are not reimplemented;
23. stale receipts are rerun;
24. fully matching receipts are reused with explicit provenance;
25. final review covers all inherited diffs;
26. ready-for-integration binds successor candidate, lineage, and receipts.

### Run-family inspection

27. related runs are deterministically ordered;
28. authoritative member selection is unambiguous;
29. terminal predecessor and active successor are both visible;
30. unknown or corrupt lineage fails safely.

## Required live canaries

### Same-run recovery canary

1. create a disposable repository and plan;
2. complete and commit Task 0;
3. produce a focused receipt;
4. introduce only an allowed host-owned volatile-ref delta;
5. confirm ordinary resume fails closed;
6. run the explicit repair command;
7. resume the same run;
8. prove Task 0 is not reimplemented;
9. reach `ready_for_integration`.

### Successor canary

1. create a disposable predecessor run;
2. complete Tasks 0 and 1;
3. induce a deliberately non-repairable but non-content-corrupt terminal;
4. create an explicit successor;
5. prove the successor starts at the predecessor candidate;
6. prove Tasks 0 and 1 receive review/receipt treatment without code replay;
7. complete the remaining task;
8. inspect the run family and lineage;
9. prove no independent equivalent run was allowed.

The live canaries must remain separate from deterministic evaluation.

## Acceptance criteria

This incident is fixed only when:

- equivalent `run` calls are blocked by default;
- an existing run's exact next action is machine-readable;
- repairable host/runtime drift can be audited and resumed in the same run;
- a non-repairable predecessor with a clean candidate can create a linked
  successor at that candidate;
- inherited committed tasks are not reimplemented;
- stale evidence is invalidated without discarding valid code;
- real product-state corruption remains fail-closed;
- arbitrary dirty work cannot be adopted;
- `inspect` exposes one authoritative run family;
- `SKILL.md` defines the exit-65 recovery boundary;
- deterministic evaluation passes;
- both explicit live canaries pass;
- a repeated Calm Craft-class failure does not create another independent
  Task-0 branch.

## Immediate operational rule until fixed

For an active implementation intent:

1. designate one run ID as authoritative;
2. do not invoke `run` again for the same source and inputs;
3. while its controller is alive, monitor only its existing terminal stream;
4. use same-run resume/retry for exit `2`, `3`, or `4`;
5. on exit `65`, preserve the worktree, branch, state, ledger, and receipts;
6. classify the integrity delta before any further mutation;
7. fix or add the audited recovery path in the runner;
8. continue the same run or an explicit linked successor;
9. never create an unlinked fresh run as an automatic recovery strategy.

For the current Calm Craft execution family, the authoritative active run when
this report was written was:

```text
2026-07-24-calm-craft-responsive-reference-integ-eb8347dd-c9a0-4c6d-a237-31f1b9e24442
```

If that run fails, creating another independent UUID branch is specifically
prohibited by this operational rule.

## Non-fixes

The following are not acceptable fixes:

- telling the provider to “continue” while giving it an empty new ledger;
- creating another UUID and manually assuming it supersedes the old run;
- cherry-picking commits without candidate and receipt provenance;
- marking inherited tasks verified without reviewing their exact diff;
- copying receipt files without validating their complete identity;
- silently updating immutable state;
- broadly disabling Git integrity checks;
- deleting old worktrees or branches before lineage is sealed;
- raising retry limits;
- restarting from Task 0 because it appears simpler;
- relying on chat memory to identify the authoritative branch.

## Relationship to other incident reports

This report covers the systemic progress-replay consequence and missing
recovery protocol.

Related trigger reports:

- `2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md`
  documents the unreachable helper transport and volatile Desktop ref
  classification defects.
- `2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md`
  documents failure to seal dirty provider output and the missing forensic
  repair boundary.
- `2026-07-24-codex-plan-runner-git-identity-isolation-incident.md`
  documents incorrect commit identity caused by isolated child configuration.

Fixing only the trigger defects reduces failures but does not close this
incident. The runner still needs admission control, same-run repair, explicit
successor lineage, and progress-preserving evidence rules.

## Remediation closeout (2026-07-25)

**Status:** resolved for equivalent-run refusal and the two approved same-run
repair shapes; the broader successor system proposed above was deliberately not
adopted.

The original forensic record remains the incident input. The final scope is
defined by the [approved remediation design](../superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md),
the [core-correctness plan](../superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md),
and the [permission/recovery plan](../superpowers/plans/2026-07-24-codex-plan-runner-permission-recovery.md).
The implementation range is inclusive from `3c93a09e` through `c3a30f61`.

Focused regressions cover serialized equivalent-intent admission, refusal of
failed or ready matching runs, exact recommended actions, tampered or missing
admission evidence, atomic provider-outcome acceptance without commit replay,
and CAS-bound repair evidence in `evals/test_engine.py`,
`evals/test_storage.py`, and the repository Codex/Claude parity scenarios.

The disposable candidate canary used one run ID, one plan, one SDD subagent,
and one implementation commit. After a bounded finalization compatibility
repair, the same preserved run resumed rather than creating another run and
reached `ready_for_integration` at
`1773ba770e2b69d975675762cd3b466592a30dd6`. Its structured final review had no
findings or open obligations.

The canonical final deterministic gate is:

```bash
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

The deliberate lightweight boundary supersedes the report's proposed general
successor graph, run-family UI, receipt-reuse optimizer, and corresponding
successor canary. The supported recovery surface is equivalent-run refusal,
ordinary same-run resume/retry, and only
`volatile-codex-turn-refs` or `unsealed-provider-partial` repair when every
load-bearing proof matches.

## Whole-review hardening addendum (2026-07-25)

Follow-up commits `1248ab56` and `95d4d23e` close the remaining continuity
gaps while retaining the deliberately small same-run model:

- every durable prior-plan handoff HEAD must remain an ancestor of the accepted
  current candidate, so a later plan cannot reset or drop earlier work;
- an authorized blocked or failed retry can change the effective sandbox or
  model without creating another logical run;
- the initial immutable profile remains unchanged and each effective change is
  sealed as an `execution_profile_transition` with the triggering failure and
  strategy-note digest;
- a transition always starts a fresh provider session, and a missing, changed,
  unauthorized, or tampered transition fails before provider launch;
- legacy state with no volatile-ref policy stays readable while observations
  match; recognized volatile-only drift receives the exact current observation
  and revision-guarded repair action instead of silent reinterpretation.

Focused regressions include a two-plan case that deliberately resets or drops
plan 1 before reporting plan 2, same-run full-access/model transition and
tamper cases, and overlapping partial-plus-volatile repair ordering.
