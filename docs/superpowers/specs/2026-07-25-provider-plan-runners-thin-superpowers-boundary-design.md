# Provider Plan Runners Thin Superpowers Boundary Design

**Date:** 2026-07-25

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surfaces:**

- `skills/kws-codex-plan-runner/`
- `skills/kws-claude-plan-runner/`
- `scripts/agent/check-plan-runner-parity`
- `scripts/agent/fixtures/plan-runner-contract-v1.json`

## 1. Summary

The Codex and Claude plan runners must be thin durability wrappers around the
installed Superpowers workflow. They must not reproduce Superpowers task
tracking, review findings, fix loops, or completion semantics in a second
runtime database.

The current runners violate that boundary in two material ways:

1. a runner-global `task_ledger` mirrors task IDs, task statuses, and evidence
   already owned by the plan-scoped Superpowers SDD ledger;
2. a runner-owned `finalization -> final_review_fix -> finalization` workflow
   repeats the final review and fix loop already owned by Superpowers.

The corrected design removes both workflow replicas. Superpowers owns each
plan from task discovery through its final review. The runner owns immutable
inputs, the isolated worktree, process and session lifecycle, exact Git
identity, bounded external recovery, exact verification receipts, ordered
plan handoffs, and truthful terminal status.

Codex and Claude remain independent runtime implementations. They adopt the
same version 2 boundary contract so their externally meaningful completion
semantics remain equivalent without sharing production code.

## 2. Design Principles

The governing rule is:

> Superpowers owns engineering workflow meaning. The runner seals external
> execution facts.

The runner may prove that:

- the assigned current plan returned a handoff;
- the handoff names the actual clean HEAD;
- prior plan handoff commits remain ancestors of that HEAD;
- protected refs and the source repository identity did not drift;
- exact declared verification commands succeeded at the accepted HEAD;
- the provider process and session transitions followed the bounded recovery
  contract.

The runner may not decide that:

- a task is complete;
- a task review finding is addressed;
- a review severity is blocking;
- another fix round should run;
- a Superpowers ledger entry represents material progress;
- a second whole-branch review is needed after Superpowers completed its own.

## 3. Evidence Behind the Change

### 3.1 Runner-owned task state

The current result schema requires `task_ledger`. The state stores it globally,
provider packets send it back to later sessions, recovery treats newly
`reported_done` task IDs as progress, and final acceptance requires every
entry to be `reported_done`.

This duplicates the plan-scoped Superpowers ledger semantically even though
the runner does not parse `progress.md` directly. It is also incorrectly
run-scoped: multiple plans commonly reuse identifiers such as `Task 1`, so a
task identity from one plan can leak into the next plan's packet.

### 3.2 Runner-owned final review workflow

The current engine dispatches:

1. a fresh finalization controller;
2. a structured whole-branch review result;
3. a separate `final_review_fix` implementation controller when findings
   remain;
4. another finalization controller.

Installed Superpowers SDD already owns one final whole-branch review, one
bundled fix dispatch, one scoped re-review, and residual-finding adjudication.
The runner therefore duplicates both the policy and the cost of the quality
loop.

### 3.3 Private Superpowers layout in provider preflight

The public documentation claims a dependency on the SDD entrypoint and the
`sdd-workspace`, `task-brief`, and `review-package` helpers. Provider preflight
also hardcodes private prompt filenames:

- `implementer-prompt.md`;
- `task-reviewer-prompt.md`;
- `re-review-prompt.md`;
- `requesting-code-review/code-reviewer.md`.

This makes a private Superpowers layout change look like a provider capability
failure even when the public workflow contract remains valid.

### 3.4 Safety and recovery wording

`--ignore-rules` disables user and project execpolicy `.rules` files. It does
not disable `AGENTS.md`, but it means the runner cannot claim that project
command deny rules are enforced.

Dirty checkpointing seals identity and detects drift. It does not preserve a
restorable copy of modified files. The correct promise is safe reuse of an
unchanged partial worktree, not backup or data restoration.

## 4. Goals

1. Make Superpowers the only owner of task, review, and fix-loop semantics.
2. Remove runner-global task state and all runner-owned review-fix routing.
3. Preserve durable ordered multi-plan execution in one branch and worktree.
4. Preserve exact Git, ref, process, session, and receipt integrity.
5. Preserve bounded recovery from controller interruption and provider session
   loss without re-dispatching completed SDD tasks.
6. Perform no extra agent review after the final Superpowers review.
7. Execute the minimum exact final verification necessary to prove the
   accepted HEAD.
8. Keep Codex and Claude runtime implementations independent while aligning
   their external version 2 semantics.
9. Cut over without silently reinterpreting version 1 task or review state.
10. State residual security and recovery limits precisely.

## 5. Non-Goals

The change does not:

- modify or fork the installed Superpowers workflow;
- parse a Superpowers `progress.md` ledger;
- introduce a new task graph, reviewer rubric, or finding database;
- add a generic command proxy or claim hostile same-UID containment;
- back up or restore dirty worktree contents;
- automatically migrate version 1 state into version 2;
- merge, push, deploy, publish, or delete assigned product worktrees;
- change Waygent or kernel isolation;
- make Codex and Claude share a production runtime;
- add more live canaries to compensate for redundant architecture.

## 6. Installed Superpowers Contract

The design is based on the installed `subagent-driven-development` workflow,
not a version string alone.

For each plan, Superpowers owns:

- one plan-scoped workspace;
- the `progress.md` recovery ledger;
- task brief generation;
- one implementer per task;
- TDD and task verification;
- task review;
- bounded task fix and scoped re-review loops;
- deferred and parked finding adjudication;
- one final whole-branch review;
- one bundled final-review fix wave and scoped re-review;
- cleanup of the plan-scoped SDD scratch workspace.

The runner must not mirror those facts. A fresh provider session recovers
plan-internal progress by following Superpowers and its ledger in the unchanged
worktree.

### 6.1 Host-managed finishing

Superpowers normally transitions to `finishing-a-development-branch` after its
final review. A plan-runner invocation already establishes a narrower
integration policy:

- keep the assigned branch and product worktree;
- do not merge;
- do not push;
- do not create a pull request;
- report `integration=not_observed`.

The public runner contract therefore defines one supported integration policy,
`keep`, and documents that invoking `runner run` selects it before the
provider starts. This is the operator's answer to the finishing decision, not
a model inference. The packet carries `integration_policy=keep`; the provider
must not wait for another integration menu inside a headless run. There is no
runner option that can select merge, push, pull-request creation, discard, or
cleanup. Superpowers still owns engineering completion and final review; the
host runner owns the preserved handoff.

## 7. Ownership Boundary

| Concern | Owner |
| --- | --- |
| Plan meaning and task discovery | Superpowers |
| SDD workspace and `progress.md` | Superpowers |
| Implementers, TDD, task review, fix rounds | Superpowers |
| Final whole-branch review and bundled fix | Superpowers |
| Task and finding status | Superpowers |
| Immutable spec and plan snapshots | Runner |
| Ordered plan selection | Runner |
| Worktree, branch, base commit, refs, and HEAD | Runner |
| Provider process and root-session lifecycle | Runner |
| Exact dirty checkpoint identity | Runner |
| Bounded external resume and fresh-session fallback | Runner |
| Exact verification command execution and receipts | Runner helper |
| Plan and branch handoff artifacts | Runner |
| Merge, push, deploy, or release | External integration workflow |

## 8. Normal Execution

### 8.1 Run creation

The runner:

1. validates and snapshots ordered specs and plans;
2. creates one isolated branch and worktree;
3. seals the source commit, protected refs, runtime identity, and immutable
   execution profile;
4. starts the current plan at index zero.

Specs remain common immutable context. Plans execute sequentially. There is no
positional spec-to-plan pairing.

### 8.2 Current plan controller

Each plan starts with a fresh root provider session. The packet contains:

- all immutable specification snapshots;
- the current plan snapshot;
- prior implemented plan handoffs;
- prior plan verification-set references;
- the assigned worktree and Git identity;
- bounded external recovery context;
- the runner-helper descriptor;
- the host-managed finishing policy.

The packet does not contain:

- a task ledger;
- task IDs or statuses;
- review findings;
- fix-round state;
- future plan paths;
- runner instructions that prescribe Superpowers subagent topology.

The provider invokes installed Superpowers SDD for the current plan. SDD
continues until the plan workflow is complete or it reaches a genuine blocker.

### 8.3 Plan handoff

The provider emits one minimal plan result:

```json
{
  "status": "implemented",
  "head_commit": "0123456789abcdef0123456789abcdef01234567",
  "summary": "Bounded plan handoff summary.",
  "verification_set_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "blocker": null
}
```

The only provider-declared statuses are:

- `implemented`;
- `blocked`.

The schema applies these status conditions:

- `implemented` requires a verification-set digest and requires
  `blocker=null`;
- `blocked` requires `verification_set_digest=null` and one recognized
  blocker;
- no other field combination is valid.

Transport loss, malformed output, schema rejection, context overflow, session
loss, and stall are runner-observed outcomes. The provider does not declare a
generic `failed` result or submit a free-form recovery strategy.

A blocked result contains one bounded blocker with a recognized external
authority or irreconcilable-requirement kind.

### 8.4 Mechanical plan acceptance

The runner accepts an implemented plan only when all of these are true:

- the result belongs to the current plan index;
- `head_commit` equals the observed worktree HEAD;
- the worktree is clean;
- the source commit is an ancestor;
- every prior plan handoff HEAD remains an ancestor;
- commit identity policy passes;
- protected refs match the sealed observation;
- the verification-set digest resolves to a helper-sealed artifact;
- required verification receipts exist at the result HEAD;
- the Superpowers root controller returned the implemented contract.

The runner does not inspect the Superpowers ledger or review report to reach
this decision.

## 9. Version 2 State and Artifacts

### 9.1 State

New runs use `format_version=2` and `contract_version=2`.

Version 2 retains:

- immutable configuration and runtime identity;
- repository, branch, worktree, and source commit;
- ordered input and plan records;
- `current_plan_index`;
- per-plan `pending`, `running`, or `implemented` status;
- sessions and provider attempts;
- artifact references;
- bounded failure state;
- integration state.

Each implemented plan records a `handoff_digest`. The full handoff remains an
immutable artifact rather than duplicated mutable state.

Version 2 removes:

- top-level `task_ledger`;
- task-status enums;
- `reported_done_evidence`;
- resolved-finding progress;
- mutable final-review findings;
- `finalization` review state;
- `final_review_fix` attempt mode;
- runner-owned final-review receipts.

### 9.2 Artifact vocabulary

The retained artifact kinds are boundary artifacts:

- immutable input snapshot;
- provider result;
- plan verification set;
- verification receipt;
- plan handoff;
- branch handoff;
- recovery audit;
- execution-profile transition;
- supported volatile-ref repair evidence.

No artifact stores a runner interpretation of Superpowers task or review
progress.

## 10. Verification Without Duplicate Review

### 10.1 Plan verification declaration

Before a plan can return `implemented`, its controller declares a
plan-scoped verification set through the runner helper. The declaration is
bound to:

- run ID;
- plan ID;
- candidate HEAD;
- exact argv commands and deadlines; or
- a non-empty structured rationale that no executable verification applies.

The helper executes commands directly without a shell and seals receipts.
Focused implementation tests remain inside Superpowers and its subagents; they
are not mirrored as runner evidence.

### 10.2 Intermediate plans

An intermediate plan must have successful same-HEAD receipts for its declared
set before handoff. The next plan receives only the immutable handoff and
verification-set references, not task or review state.

For an intermediate plan, the result's `verification_set_digest` names that
plan's declared set.

### 10.3 Final plan

The final plan is also the run closer:

- its existing Superpowers final whole-branch review is given every immutable
  spec and every ordered plan as requirements;
- it remains the single final agent review;
- the helper executes the exact union of all plan verification sets at the
  final candidate HEAD;
- duplicate exact argv entries are canonicalized and run once;
- no second finalization or final-review-fix controller is dispatched.

For the final plan, the helper seals a run verification set whose inputs are
the ordered plan-set digests and whose commands are their canonical exact
union. The final result's `verification_set_digest` names this run-level set,
and the branch handoff records the same digest. This removes any ambiguity
between the final plan's local declaration and the accepted run declaration.

If a verification command fails, the same Superpowers controller owns
diagnosis, correction, appropriate review, and another declaration at the new
HEAD. The runner supplies the failed exact receipt but does not interpret the
defect.

Any HEAD change invalidates receipts for the old HEAD. It does not cause the
runner to create another review workflow. The final controller completes its
own Superpowers review contract and returns only when the final HEAD has the
required receipts.

## 11. External Recovery

### 11.1 What recovery may observe

Material progress consists only of:

- a previously unseen Git HEAD or worktree tree digest;
- a new successful verification receipt digest;
- advancement to the next plan handoff.

Task IDs, finding IDs, narrative summaries, heartbeat repetition, and
free-form strategy text are not material progress.

### 11.2 Fixed recovery sequence

For one stable external failure signature:

1. prefer one explicit resume when the same-plan session is recorded healthy;
2. use one fresh root session when resume fails, the session is invalid,
   context is contaminated, the signature repeats, or no healthy session is
   available;
3. stop when the same signature repeats without material progress after the
   fresh-session attempt.

The fresh session uses the same logical run, plan, worktree, branch, HEAD, and
checkpoint. It follows Superpowers and the plan-scoped SDD ledger to discover
where to resume.

The provider no longer supplies changed-strategy prose. Operator-authorized
`--retry-failed` may retain a bounded strategy note as audit evidence for a
new external attempt, and an explicitly authorized sandbox or model transition
remains a same-run profile transition.

### 11.3 Controller interruption

`SIGINT` and `SIGTERM` stop and reap the provider process group before the
runner exposes `resumable`.

If the worktree is dirty, the runner seals:

- HEAD;
- branch;
- porcelain digest;
- bounded content/tree digest;
- attempt and process identity.

Resume accepts that tree only while every sealed identity remains unchanged.
Any drift fails closed before provider launch.

This is drift detection, not a backup. The runner does not claim it can restore
overwritten or externally modified files.

### 11.4 Repair surface

The version 2 runtime retains only the narrow, revision-guarded volatile Codex
turn-ref repair when its exact evidence contract still applies.

The disabled `unsealed-provider-partial` compatibility repair is removed from
the version 2 public CLI and state vocabulary. The runner must not retain a
non-actionable command merely to appear recoverable.

## 12. Provider Capability Boundary

Preflight verifies the public capability surface required by the runner:

- the installed SDD entrypoint is discoverable;
- `sdd-workspace` is available;
- `task-brief` is available;
- `review-package` is available.

Private prompt and reviewer-template filenames are not runner compatibility
gates. If Superpowers changes its private layout while preserving the public
workflow, runner preflight continues to pass.

The runner does not parse the SDD skill text to infer a semantic version. A
missing public entrypoint or helper is `provider_capability_blocked`.

## 13. Security Boundary

Codex initial and resumed sessions use one consistent noninteractive profile.
The current CLI exposes `--ignore-rules` but no separate option for injecting a
minimal destructive-command deny policy.

The design therefore:

- keeps isolated worktrees;
- strips non-required credentials and Git routing variables;
- disables accidental remote routing;
- preserves protected-ref checks;
- preserves exact Git identity and clean-handoff checks;
- documents that user/project execpolicy `.rules` files are not applied;
- does not claim complete prevention of local destructive commands;
- does not add a large command proxy that would become another policy engine.

Hard containment of same-UID execution remains a Waygent/kernel
responsibility. `danger-full-access` remains an explicit operator choice and
does not imply TCC, Keychain, GUI, or host authority.

## 14. Version 1 Cutover

Version 1 state must not be rewritten into version 2. Task and review fields
have different ownership semantics and cannot be safely converted.

The 2026-07-25 inventory found eight Codex version 1 run states:

- three `resumable`;
- one `blocked`;
- four `failed`.

Before the version 2 cutover, every nonterminal version 1 run receives an
explicit per-run decision using the version 1 runner:

- complete it;
- retain it as historical evidence;
- or retire it with separate operator authorization.

The cutover does not auto-delete state or worktrees. The implementation
workflow must record the exact inventory and decision evidence.

After cutover:

- version 2 is the only format created by default;
- version 1 remains read-only inspectable;
- version 2 does not resume or repair version 1;
- a version 1 resume request returns a precise
  `legacy_contract_requires_v1_runner` result;
- no field is silently reinterpreted.

## 15. Codex and Claude Parity

The two runners continue to share no production runtime. Both implement the
same version 2 external semantics:

- identical plan-result shape;
- identical plan-handoff meaning;
- identical verification-set and receipt meaning;
- identical ordered ancestry requirement;
- identical terminal status meaning;
- identical absence of runner-owned task and review state.

The root parity fixture compares boundary outcomes only. It must not require
provider-private session fields, stream details, or internal code structure to
match.

## 16. Validation Strategy

### 16.1 Contract tests

Required regressions prove that:

- `task_ledger` is absent from production state, packets, results, and schema;
- task status enums are absent;
- `final_review_fix` is not a provider mode;
- no runner code parses review finding severity;
- material progress uses only Git, receipts, and plan advancement;
- no separate finalizer is dispatched after the final plan;
- private Superpowers prompt filename changes do not block preflight;
- missing public SDD capabilities block precisely;
- version 1 is never interpreted as version 2;
- Codex and Claude parity compares boundary results only;
- a HEAD change invalidates verification receipts without creating a review
  workflow.

Production-code vocabulary checks apply to active runner code and schemas.
Historical design, incident, and changelog documents may retain old terms as
evidence.

### 16.2 Deterministic fault tests

Deterministic tests cover:

- healthy explicit resume;
- invalid-session fresh fallback;
- repeated same-signature exhaustion;
- same Task numbers in consecutive plans;
- dirty checkpoint acceptance while unchanged;
- dirty checkpoint drift rejection;
- process and descendant quiescence;
- protected and volatile ref behavior;
- verification failure and same-HEAD receipt reuse;
- old-HEAD receipt invalidation;
- version 1 read-only inspection;
- equivalent-run admission under version 2.

### 16.3 Live canary A: multi-plan ownership

A disposable repository contains two plans. Both use `Task 1` and `Task 2`,
but modify different files and create different commits.

Acceptance:

- plan snapshots and SDD workspaces are distinct;
- both plans execute fully;
- the second plan does not inherit or skip task IDs;
- each plan starts a fresh root session;
- prior handoff HEAD remains an ancestor;
- runner state contains no task or finding database;
- the final Superpowers review covers all immutable specs and plans;
- the exact union verification and branch handoff bind to the same HEAD;
- the run ends `ready_for_integration`;
- `integration=not_observed`;
- no finalization or `final_review_fix` session exists.

### 16.4 Live canary B: interruption

A disposable plan is interrupted with `SIGINT` after Task 1 commits and while
Task 2 is in progress.

Acceptance:

- the runner returns `resumable`;
- the provider process group is quiescent;
- an unchanged dirty tree has an exact sealed checkpoint;
- resume prefers the healthy recorded session;
- Superpowers does not re-dispatch completed Task 1;
- the run finishes with a clean handoff and same-HEAD receipts.

Fresh-session fallback is proven deterministically rather than by destructive
mutation of a real provider home.

### 16.5 Final gates

During implementation, run focused tests only. At the final candidate HEAD:

1. run the Codex deterministic eval once;
2. run the Claude deterministic eval once;
3. run the root parity and contract gate;
4. run the two explicit live canaries;
5. run:

   ```bash
   bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
   ```

Live canaries do not replace deterministic validation.

## 17. Cutover Order

1. Inventory and explicitly resolve nonterminal version 1 runs.
2. Add version 2 contract tests and confirm RED.
3. Remove runner-owned workflow state from Codex.
4. Apply the same external semantics independently to Claude.
5. Update the root parity fixture and documentation.
6. Run focused deterministic tests during each change.
7. Run live canaries only after both deterministic implementations are green.
8. Run final gates once at the final candidate HEAD.
9. Cut over default launchers to version 2.

## 18. Rejected Alternatives

### 18.1 Plan-scope the runner task ledger

Adding `task_ledger_plan_id` and clearing the ledger between plans would fix
the immediate collision but preserve duplicate ownership. A later
Superpowers ledger change would require another runner migration.

### 18.2 Keep a runner final reviewer but remove only the fixer

This would still pay for and depend on a second whole-branch review. It would
also leave the runner interpreting findings produced after Superpowers already
completed its own final review.

### 18.3 Treat the entire provider as one opaque multi-plan session

This is the smallest wrapper but loses useful plan boundaries, fresh-session
isolation, ordered handoff ancestry, and bounded recovery from a damaged
long-lived context.

### 18.4 Add a general destructive-command proxy

A proxy would need to understand shell indirection, alternate binaries,
scripts, language subprocesses, and future tool behavior. It would become a
new incomplete policy engine without providing a real same-UID security
boundary.

### 18.5 Preserve a version 1 execution engine inside version 2

Keeping two mutable workflow engines in the active skill would defeat the
thin-wrapper objective. Version 1 state remains evidence, but active version 1
runs must be resolved before cutover rather than silently routed through a
permanent compatibility runtime.

## 19. Acceptance Criteria

The design is implemented when:

- Codex and Claude create only version 2 state for new runs;
- runner production state contains no task or finding database;
- no runner-owned final review or review-fix session exists;
- installed Superpowers SDD is the only task/review/fix owner;
- each plan handoff is clean, ordered, and bound to exact verification
  evidence;
- the final plan's existing Superpowers review covers all specs and plans;
- no separate finalizer runs afterward;
- external recovery uses only Git, receipt, plan, process, and session facts;
- dirty checkpoint documentation makes no backup or restoration claim;
- private Superpowers prompt layout is not a runner compatibility contract;
- version 1 state is never auto-migrated;
- both live canaries and all final gates pass at the final candidate HEAD;
- successful handoff remains `integration=not_observed`.
