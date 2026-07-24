# Incident Report: Codex Plan Runner Strands a Dirty Worktree After Provider-Result Failure

## Document status

| Field | Value |
| --- | --- |
| Status | Confirmed implementation defect and recovery coverage gap |
| Suggested severity | High |
| Affected component | `skills/kws-codex-plan-runner` |
| Affected release | `1.0.0` |
| Runner repository HEAD inspected | `39fa7799c18c0513ecd81275cfa6d88dee254fce` |
| Incident date | 2026-07-24 |
| Evidence reviewed | 2026-07-24 |
| User-visible outcome | Run permanently fails pre-launch with `dirty worktree has no exact resumable checkpoint` |
| Data-loss status | No confirmed file loss; partial implementation is stranded and untrusted by the runner |
| Integration status | `not_observed` |

## Issue title suitable for a tracker

> Codex plan runner fails to seal a dirty worktree when provider output is malformed, leaving the run permanently non-resumable

## Executive summary

The Codex plan runner can enter an unrecoverable state when all of the following
are true:

1. a provider attempt modifies the assigned worktree;
2. the provider then exits without a valid plan-result envelope, or its JSONL
   stream is classified as malformed;
3. the controller routes the invalid result directly through
   `_integrity_failure`;
4. `_fail_closed` replaces the failure object with only `reason_code` and
   `detail`;
5. no `partial_worktree` checkpoint is recorded for the modified tree.

The next `resume` invocation observes a dirty worktree and requires an exact
sealed checkpoint. Because the earlier integrity-failure path did not create
one, the run fails before another provider can launch:

```text
state_integrity_failed
dirty worktree has no exact resumable checkpoint
```

This final rejection is a correct fail-closed safety response. The defect is
the earlier transition that allowed a provider-created dirty tree to become
terminally unsealed.

The incident was triggered by provider/runtime problems, including file-based
authentication not being available in the isolated child HOME, an oversized
tool-output event, and a later provider session that used collaboration
subagents but did not produce a valid final result. Those triggers should be
recoverable. The runner converted the last trigger into a permanent dead end
because only the explicit `controller_stopped` signal path can seal a dirty
partial worktree.

## Bottom-line ownership assessment

This is primarily a `kws-codex-plan-runner` recovery defect.

The provider behavior triggered the failure, but provider loss, malformed
output, session loss, context damage, and other child failures are expected
operational events for a durable controller. The runner owns the boundary that
must preserve enough exact state to retry safely.

The Calm Craft specification, implementation plan, and product repository did
not cause the dead-end transition.

## User impact

The affected run:

- did not complete Task 0 through Task 18;
- did not produce a sealed plan result;
- did not produce verification receipts;
- did not produce local implementation commits;
- left 16 tracked files modified;
- left 6 untracked files;
- remained at its starting HEAD;
- cannot launch another provider through the public `resume` command;
- cannot reach `ready_for_integration`;
- cannot be repaired through any advertised public runner command.

The partial changes remain on disk, so this is not confirmed data loss.
However, they are operationally stranded because the runner cannot prove that
the current tree is the exact tree produced by the failed provider attempt.

## Affected run

| Field | Observed value |
| --- | --- |
| Run ID | `2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c` |
| State revision | `29` |
| Top-level status | `failed` |
| Current plan index | `0` |
| Plan status | `running` |
| Source commit | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |
| Current worktree HEAD | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |
| Assigned branch | `codex-plan/2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c` |
| Runner-computed clean flag | `false` |
| Runner-computed porcelain digest | `36df7da3288bb76b5eabc26873d3d2e9fd754ac146d6bc521490b856359c0483` |
| Runner-computed tree digest | `eb16daeed455742ec0d314c1f05401e3df136a10ac5dc6ad67dd7507804e46a0` |
| Final failure | `state_integrity_failed` |
| Final detail | `dirty worktree has no exact resumable checkpoint` |
| `partial_worktree` in failure state | Absent |
| Live controller/provider | None observed |
| Integration | `not_observed` |

### Forensic locations

These paths are local evidence locations. They are not intended as portable
runtime interfaces.

```text
State:
$HOME/.codex/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c/state.json

Worktree:
$HOME/.codex/worktrees/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c
```

## Current partial worktree inventory

### Tracked modifications

```text
package.json
scripts/verification/leaf-registry.mjs
scripts/verification/leaf-registry.test.mjs
scripts/verification/path-impact.mjs
scripts/verification/path-impact.test.mjs
scripts/verification/stage-graph.test.mjs
src/editor/components/EditorShell.tsx
src/editor/i18n/catalog.en.ts
src/editor/i18n/catalog.ko.ts
src/editor/i18n/messageKeys.ts
src/editor/pages/PageActionsMenu.tsx
src/editor/platform/styles/chrome.css
src/editor/platform/styles/tokens.css
src/editor/shell/EditorViewportNotice.tsx
src/editor/shell/__tests__/layoutModel.test.ts
src/editor/shell/layoutModel.ts
```

Tracked diff summary:

```text
16 files changed, 157 insertions(+), 60 deletions(-)
```

### Untracked files

```text
scripts/validate-calm-craft-reference.mjs
scripts/validate-calm-craft-reference.test.mjs
src/editor/preferences/editorViewPreferences.ts
src/platform/identity/IdentityGateway.ts
src/platform/sharing/SharingGateway.ts
src/platform/sharing/sharingCapabilities.ts
```

### Limited local checks

```text
git diff --check
```

Result: exit `0`.

This whitespace check does not validate correctness and must not be interpreted
as implementation evidence.

## Evidence classification

The report separates confirmed observations from plausible but not fully
proven causal details.

| Claim | Classification | Evidence |
| --- | --- | --- |
| The final state is revision 29 and has no `partial_worktree` | Confirmed | `state.json` |
| The worktree is dirty and still at the source commit | Confirmed | Runner `GitWorkspace.require_identity()` and Git |
| Two provider attempts remain `completed: false` | Confirmed | `state.json` attempts |
| Recovery revisions 21 and 25 failed with `plan result shape is invalid` | Confirmed | Immutable recovery-audit artifacts |
| Revision 27 failed because a worktree symlink was present | Confirmed | Immutable recovery-audit artifact |
| The authenticated provider produced a tool result reporting 218,577 original tokens | Confirmed | Provider session rollout |
| The 65,536-byte JSONL line limit was exceeded by that event | Strong operator attribution, not independently byte-reconstructed from raw stdout | Immutable strategy note and adapter limit |
| The later provider emitted a schema-shaped `implemented` commentary message before doing work | Confirmed | Provider session rollout |
| The later provider spawned three collaboration subagents | Confirmed | Provider session rollout |
| Collaboration/asynchronous messages prevented the correct final envelope | Strong operator attribution; the absence of a valid final envelope is confirmed, the exact CLI-internal selection cause is not | Strategy note, rollout ending, and recovery audit |
| The runner never seals dirty work on result-validation failure | Confirmed | `engine.py` control flow |
| Repeating `resume` cannot repair the run | Confirmed | Public CLI surface and pre-launch Git contract |

## Incident timeline

Times below use provider-rollout UTC timestamps where available. State revisions
are more authoritative than conversational recollection.

### Phase 1: clean run creation

The runner created an isolated worktree from:

```text
4d0153c3ec347dbdaff32642426c466c5b7a607d
```

The baseline progress digest recorded by all implementation attempts was:

```text
b69f38bfc42513ac5d22b02870f62f4ce5e2c65d465798db4717fd31609e93a2
```

There is no evidence that the source checkout was dirty when the run was
created.

### Phase 2: provider authentication failures

The first four attempts ended as:

```text
outcome: transport_failed
provider_code: controller_transport_failed
```

An isolated-HOME provider probe showed `401 Missing bearer`. The installed Codex
authentication was file-backed in the normal user home, while the runner
intentionally changed `HOME` to a run-private directory.

The existing local `auth.json` was copied into the run-private child home with
mode `0600`, and a direct provider probe then authenticated successfully.

This fixed the immediate provider-access issue, but it exposed a compatibility
gap between file-backed Codex authentication and the runner's isolated-HOME
policy.

### Phase 3: oversized provider event and invalid plan result

Provider session:

```text
019f93b3-b2ee-7c52-b778-2c24414322c5
```

At `2026-07-24T10:38:05.885Z`, a recursive `.superpowers` inspection returned:

```text
Original token count: 218577
Total output lines: 12059
```

The runner adapter bounds one JSONL line to 65,536 bytes. The operator recovery
record attributes the next invalid result to that large event crossing the
adapter boundary.

Recovery audit at failed revision 21:

```json
{
  "reason_code": "state_integrity_failed",
  "detail": "plan result shape is invalid"
}
```

The worktree was still clean at this stage.

### Phase 4: second authenticated provider performs partial work

Provider session:

```text
019f93b5-911e-7041-a2b9-66eae5962c58
```

At `2026-07-24T10:39:44Z`, before its first tool call, the root provider emitted
this assistant commentary:

```json
{
  "status": "implemented",
  "head_commit": "4d0153c3ec347dbdaff32642426c466c5b7a607d",
  "summary": "Starting bounded inspection of the execution packet, Superpowers guidance, repository instructions, and immutable plan/spec sources.",
  "task_ledger": [],
  "open_obligation_ids": [],
  "failure_signature": null,
  "strategy_note": "Avoiding recursive or unbounded output per recovery context.",
  "blocker": null
}
```

Although schema-shaped, this was a commentary-phase progress message and not a
truthful implementation result.

The same provider session then:

1. inspected the repository and plan;
2. spawned three collaboration subagents:
   - `foundation`;
   - `features`;
   - `ui_closure`;
3. attempted dependency installation;
4. received asynchronous agent messages;
5. modified product files through the shared worktree;
6. created an untracked `node_modules` symlink while attempting to recover the
   dependency environment;
7. ended without a valid final plan-result envelope.

Recovery audit at failed revision 25:

```json
{
  "reason_code": "state_integrity_failed",
  "detail": "plan result shape is invalid"
}
```

At this point the worktree was dirty.

### Phase 5: unsafe symlink blocks recovery

The next recovery attempt detected the untracked `node_modules` symlink:

```json
{
  "reason_code": "state_integrity_failed",
  "detail": "symlink worktree entries are not allowed"
}
```

This was failed revision 27.

The symlink itself was moved intact to a temporary recovery location. Its
target and product files were not removed. This resolved the unsafe-path
condition but did not create the missing dirty-worktree checkpoint.

### Phase 6: current terminal dead end

The next `resume --retry-failed` reached the Git contract before launching a
provider.

The worktree was:

- on the expected assigned branch;
- at the expected source HEAD;
- dirty;
- composed of regular tracked and untracked files after symlink removal;
- missing a sealed `partial_worktree` state record.

The runner therefore raised:

```text
dirty worktree has no exact resumable checkpoint
```

The resulting state is failed revision 29.

Repeated later inspections reported the same revision and failure. These were
not three independent corruptions. They were repeated observations of the same
unchanged terminal state.

## Intended recovery contract

The approved design states that a live controller should checkpoint before
relaunching a child and should automatically continue recoverable provider
failures:

> If the controller process remains alive, child stall, transport failure,
> session loss, and other recoverable child failures enter `recovering`. The
> controller checkpoints before relaunching and automatically continues the
> bounded changed-strategy loop without asking the user.

The design also explicitly requires deterministic scenarios for:

- provider stream truncation;
- malformed final envelopes;
- process interruption and checkpoint recovery;
- live-controller child failure entering `recovering`;
- dirty-worktree rejection.

The implementation covers these cases independently but does not cover their
important composition:

> provider modifies worktree + provider output becomes invalid

That composition is the incident.

## Actual control flow

### Provider outcome validation occurs before outcome checkpointing

In
[`engine.py`](../../skills/kws-codex-plan-runner/scripts/plan_runner/engine.py),
`_execute_current_plan` performs this sequence:

```python
outcome = self._launch(...)

if outcome.kind in {"implemented", "blocked", "failed"}:
    try:
        self._validated_plan_result(outcome.result)
    except ValueError as error:
        return self._integrity_failure(store, str(error))

if outcome.kind == "controller_stopped":
    return self._pause_resumable(...)

self._checkpoint_outcome(...)
```

For an invalid result:

1. `_validated_plan_result` raises;
2. `_integrity_failure` runs immediately;
3. `_checkpoint_outcome` never runs;
4. the attempt remains incomplete;
5. the post-provider dirty tree is not sealed.

This ordering is the central implementation defect.

### The generic integrity-failure path discards recoverable context

`_integrity_failure` delegates to `_fail_closed`:

```python
state["status"] = "failed"
state["failure"] = {
    "reason_code": reason_code,
    "detail": str(detail)[:512],
}
```

The replacement failure object does not preserve:

- attempt ID;
- mode;
- plan index;
- session lineage;
- next session action;
- post-provider HEAD;
- branch;
- porcelain digest;
- tree digest;
- clean/dirty flag;
- a resumable partial-worktree checkpoint.

### Dirty partial work is sealed only for controller signals

`_pause_resumable` records the exact worktree identity only when:

```text
outcome.kind == "controller_stopped"
```

It then sets the attempt outcome to `controller_stopped` and writes:

```json
{
  "partial_worktree": {
    "version": 1,
    "attempt_id": "...",
    "mode": "implementation",
    "plan_index": 0,
    "head": "...",
    "branch": "...",
    "porcelain_digest": "...",
    "tree_digest": "...",
    "clean": false
  }
}
```

Malformed provider output, invalid structured results, transport failure,
context overflow, and stall do not use this path.

### Resume correctly rejects the unsealed tree

Before a provider launch, `_require_git_contract` observes the worktree. If the
tree is dirty, `_require_sealed_partial_worktree` requires:

- the exact checkpoint key set;
- matching HEAD;
- matching branch;
- matching porcelain digest;
- matching tree digest;
- `clean: false`;
- mutation-allowed mode;
- a matching attempt;
- attempt outcome `controller_stopped`.

If the checkpoint is absent, it raises:

```text
dirty worktree has no exact resumable checkpoint
```

This guard is correct in isolation. Weakening it to accept arbitrary dirty
state would create a state-confusion and user-change-adoption vulnerability.

## Failure sequence diagram

```text
Provider               Codex adapter              PlanRunner engine              Durable state / Git
   |                         |                            |                               |
   | modifies worktree      |                            |                               |
   |------------------------+----------------------------+------------------------------>|
   |                         |                            |                     tree becomes dirty
   | emits malformed or      |                            |                               |
   | incomplete result       |                            |                               |
   |------------------------>|                            |                               |
   |                         | returns failed/result=None |                               |
   |                         |--------------------------->|                               |
   |                         |                            | validate result                |
   |                         |                            | -> ValueError                  |
   |                         |                            | -> _integrity_failure          |
   |                         |                            |------------------------------>|
   |                         |                            |              failure overwritten
   |                         |                            |              no partial checkpoint
   |                         |                            |                               |
   |                         |       later resume         |                               |
   |                         |                            | read dirty tree                |
   |                         |                            | read missing checkpoint        |
   |                         |                            | fail before provider launch    |
   |                         |                            |------------------------------>|
   |                         |                            |              terminal failed state
```

## Root-cause analysis

### Primary root cause

The engine validates the semantic provider result before durably checkpointing
the provider attempt and post-provider worktree identity.

When validation fails, the engine exits through a failure writer that does not
preserve or create partial-worktree recovery metadata.

### Contributing defect 1: result failure and state-integrity failure are conflated

An invalid provider envelope is currently surfaced as:

```text
state_integrity_failed
```

But these are different trust domains:

- **provider protocol failure**: the child did not return a valid result;
- **durable-state integrity failure**: runner-owned state or evidence has been
  corrupted or drifted.

A malformed provider result should not automatically imply that the runner can
no longer checkpoint the exact post-provider Git identity.

The current classification:

- loses diagnostic precision;
- bypasses automatic recovery;
- makes a child protocol fault look like runner-state corruption;
- causes the controller to abandon otherwise inspectable work.

### Contributing defect 2: file-backed Codex authentication is incompatible with isolated HOME

The adapter creates a run-private HOME:

```text
<run-root>/.codex-child-home
```

It preserves selected `OPENAI_` and `CODEX_` environment variables, but an
installed Codex session may authenticate through:

```text
~/.codex/auth.json
```

Changing HOME makes that file unavailable. The incident's initial provider
attempts therefore received `401 Missing bearer` until the auth file was
manually provisioned into the child home.

This did not cause the final dirty-checkpoint dead end, but it caused the first
four attempts and demonstrates that the live provider contract did not cover
the active authentication mode.

### Contributing defect 3: oversized JSONL events are treated as fatal stream corruption

The adapter rejects any single JSONL line larger than 65,536 bytes:

```python
MAX_JSONL_LINE_BYTES = 65_536
```

Codex CLI tool-result events can contain large bounded command output in one
JSON object. A single oversized non-critical event can therefore terminate the
provider even when:

- the session ID was already captured;
- later events could still be readable;
- the final structured result is written to a separate output file.

The limit itself is a valid resource-protection measure. The issue is that the
adapter cannot discard or classify an oversized event without destroying the
entire attempt, and the engine cannot preserve dirty work if that destruction
happens after a mutation.

### Contributing defect 4: structured output is not sufficiently separated from progress output

The second authenticated provider emitted a complete
`status: implemented`-shaped object as a commentary message before doing any
work. It then continued with tool calls and subagents.

This demonstrates that:

- schema-shaped assistant content is not necessarily a final result;
- `--output-last-message` must not be trusted without a completed root turn;
- collaboration events can change what is considered the last message;
- the prompt instruction to "Return only the enforced structured result" is
  insufficient as the only boundary.

### Contributing defect 5: deterministic tests cover the components but not the composition

Existing tests cover:

- malformed JSONL;
- oversized JSONL;
- invalid structured output;
- dirty SIGINT checkpoint creation;
- dirty SIGTERM checkpoint creation;
- exact dirty checkpoint resume;
- dirty checkpoint drift rejection.

They do not cover:

```text
provider modifies worktree
then emits malformed JSONL or invalid final output
then the same run resumes
```

The missing composition allowed all focused tests to pass while the live run
entered an unrecoverable state.

## Five whys

### 1. Why could the run not resume?

Because the worktree was dirty and the failure state had no exact
`partial_worktree` checkpoint.

### 2. Why was there no checkpoint?

Because the provider result failed schema validation, and that branch called
`_integrity_failure` before `_checkpoint_outcome` or `_pause_resumable`.

### 3. Why did schema validation fail after files were modified?

The provider session ended without a valid final plan-result envelope after
using tools and collaboration subagents. The preceding attempt also encountered
an oversized tool-output event.

### 4. Why did the controller not automatically recover the child failure?

The engine classified the missing/invalid provider result as state integrity
failure rather than a provider failure with exact partial work.

### 5. Why did the test suite not catch the dead end?

The tests separately covered malformed output and signal-based dirty recovery,
but omitted dirty work followed by malformed output.

## Why fail-closed behavior must remain

The fix must not weaken this invariant:

> An arbitrary dirty worktree must never be silently adopted as runner-owned
> partial work.

Without exact identity binding, a dirty tree could contain:

- unrelated user edits;
- edits from another process;
- tampering after the provider stopped;
- symlinks or paths escaping the worktree;
- protected-ref manipulation;
- a different branch or HEAD;
- changes made after the last durable runner revision.

The correct fix is to seal provider-created partial state earlier and more
generally, not to skip the resume check.

## Recommended target behavior

### Required invariant

After every provider process is fully reaped, and before semantic result
validation can terminate the attempt, the controller must durably record:

- attempt ID;
- provider outcome class;
- mode;
- plan index;
- session ID and health;
- expected assigned branch;
- HEAD;
- porcelain digest;
- bounded content/tree digest;
- clean/dirty flag;
- whether all paths satisfy regular-file and containment rules;
- protected-ref state;
- failure reason;
- intended next session action.

### Safe result matrix

| Provider outcome | Worktree | Required runner action |
| --- | --- | --- |
| Valid `implemented` result | Clean committed candidate | Continue normal acceptance |
| Valid `blocked` or `failed` result | Clean | Record attempt and use normal block/recovery policy |
| Transport/session/context/stall failure | Clean | Record attempt and enter automatic recovery |
| Malformed stream or invalid result | Clean | Classify as provider protocol failure and enter bounded recovery |
| Recoverable provider failure | Dirty but safe and mutation mode permits it | Seal exact partial tree, record failure provenance, continue recovery using same exact tree |
| Malformed stream or invalid result | Dirty but safe and mutation mode permits it | Seal exact partial tree as untrusted provider partial work, require a fresh session to inspect/review it, then continue |
| Any outcome | Dirty in non-mutating mode | Integrity failure |
| Any outcome | Symlink, path escape, protected-ref drift, wrong branch, wrong ancestry, or unbounded file | Integrity failure; do not make resumable |
| Resume | Exact sealed identity | Allow the declared recovery action |
| Resume | Any digest or identity drift | Reject before provider launch |

### Proposed state representation

The exact schema should be chosen with the existing state-version contract, but
the missing concept is a provider-failure partial checkpoint independent of
`controller_stopped`.

Example:

```json
{
  "status": "recovering",
  "failure": {
    "reason_code": "provider_result_invalid",
    "detail": "plan result shape is invalid",
    "mode": "implementation",
    "plan_index": 0,
    "attempt_id": "e8c49076-9ddd-425f-a05d-a6810ab8b8db",
    "next_session_action": "fresh_session",
    "required_strategy_change": true,
    "partial_worktree": {
      "version": 1,
      "attempt_id": "e8c49076-9ddd-425f-a05d-a6810ab8b8db",
      "attempt_outcome": "provider_failed_with_partial",
      "mode": "implementation",
      "plan_index": 0,
      "head": "4d0153c3ec347dbdaff32642426c466c5b7a607d",
      "branch": "codex-plan/...",
      "porcelain_digest": "<sha256>",
      "tree_digest": "<sha256>",
      "clean": false
    }
  }
}
```

The important property is not the field name. It is the atomic binding between
the failed attempt, the exact dirty tree, and the next permitted action.

## Proposed implementation changes

### P0: checkpoint post-provider state before semantic result validation

Refactor implementation, final-review-fix, and any other mutation-capable
provider paths to use one common sequence:

1. launch provider;
2. fully terminate/reap the provider process group;
3. capture the provider session and raw outcome class;
4. validate branch, HEAD, ancestry, protected refs, and worktree paths;
5. atomically checkpoint attempt and exact post-provider Git identity;
6. validate the semantic result envelope;
7. transition to accept, block, recover, or integrity failure.

This removes the current gap where step 6 can return before step 5.

### P0: generalize resumable partial-attempt outcomes

`_require_sealed_partial_worktree` currently requires:

```text
attempt.outcome == controller_stopped
```

Introduce a bounded allowlist for exact partial recovery, for example:

```text
controller_stopped
provider_failed_with_partial
provider_result_invalid_with_partial
provider_stalled_with_partial
```

Each outcome must have explicit mode and next-session rules. Do not accept an
arbitrary string or a generic `failed` attempt.

### P0: preserve failure provenance

Replace the destructive failure assignment with a helper that preserves
forensic and recovery fields when safe:

```python
state["failure"] = {
    **preserved_checkpoint_fields,
    "reason_code": reason_code,
    "detail": bounded_detail,
}
```

State-integrity failures caused by unsafe state may deliberately omit
resumability, but they should still preserve immutable recovery-audit artifacts.

### P0: separate provider protocol failures from state integrity failures

Add distinct reason codes, such as:

```text
provider_stream_malformed
provider_stream_oversized
provider_result_missing
provider_result_schema_invalid
provider_turn_incomplete
```

Reserve `state_integrity_failed` for runner-owned state, Git, artifact, receipt,
helper, or identity corruption.

This enables appropriate automatic recovery without weakening state checks.

### P1: harden oversized JSONL handling

Do not immediately terminate the provider merely because one non-session event
crosses the retained-line limit.

A safer bounded strategy is:

1. detect the oversized line without retaining it;
2. discard bytes until the next newline under a bounded discard counter;
3. record `provider_stream_oversized`;
4. do not grant activity credit for the discarded event;
5. continue reading later lifecycle events;
6. validate the separately written final output at process completion;
7. fail only if required lifecycle/result facts are missing or the discard
   bound is exceeded.

If the implementation continues to terminate on any oversized line, it must at
least seal a safe dirty worktree before recovery.

### P1: require a completed root turn before accepting output-last-message

The adapter should not accept the output file as a final provider result unless
all required lifecycle conditions hold, including:

- the expected session ID was captured;
- the root process exited successfully;
- a root `turn.completed` event was observed;
- the output file is regular, bounded, and not a symlink;
- the result matches the exact schema;
- `head_commit` and task evidence pass engine validation.

Progress commentary that happens to match the schema must never count as the
final result.

### P1: add collaboration-event live compatibility coverage

The design intentionally leaves subagent choice to the provider. The runner
therefore cannot solve this by banning subagents in normal operation.

Add an explicit live Codex canary that:

1. starts a root Codex session;
2. launches at least one collaboration subagent;
3. receives an agent message;
4. modifies a disposable worktree;
5. returns one root final structured result;
6. proves that `--output-last-message` contains the root final result;
7. proves that the runner does not terminate on the collaboration events.

The canary must remain separate from deterministic fake-provider tests.

### P1: support installed file-backed Codex authentication safely

Define and test supported authentication modes:

- provider token from approved environment variables;
- installed file-backed Codex authentication.

For file-backed authentication, use a security-reviewed bootstrap:

1. open the source auth file without following symlinks;
2. require expected ownership and a regular file;
3. copy only the minimum required file into the private child home;
4. write atomically with mode `0600`;
5. never include contents or hashes in state, logs, artifacts, or packets;
6. refresh or reprovision on resume as required;
7. fail as `provider_auth_blocked`, not generic transport failure, when auth is
   unavailable.

Do not broadly copy the user's `.codex` directory.

### P2: provide an explicit forensic repair command

The current public commands are:

```text
run
resume
inspect
```

They cannot repair an already unsealed dirty run.

Consider a narrowly gated command such as:

```text
runner repair \
  --run-id <RUN_ID> \
  --seal-current-worktree \
  --attempt-id <ATTEMPT_ID> \
  --strategy-note "<operator attestation and evidence>"
```

This must not be a convenience bypass. It should require:

- no live controller, provider, helper, or descendant process;
- exact failed state revision supplied or confirmed;
- exact source repository, Git common directory, branch, and HEAD;
- starting commit remains an ancestor;
- protected refs unchanged;
- no symlink, path escape, non-regular file, or unbounded file;
- a captured incomplete attempt for the same mode and plan;
- immutable repair audit artifact;
- exact porcelain and tree digests;
- explicit operator authorization;
- a fresh provider session that reviews the entire partial diff before
  continuing.

If those requirements cannot be proven, repair must fail closed.

## Deterministic regression reproduction

Add a fake-provider scenario named, for example:

```text
dirty-invalid-output
```

The fake should:

1. emit a valid `thread.started`;
2. emit a valid `turn.started`;
3. create `partial-provider-edit.txt` in the assigned worktree;
4. emit `item.started` and `item.completed`;
5. emit `turn.completed`, or provide a separate variant that omits it;
6. write an invalid object to `--output-last-message`;
7. exit.

### Current behavior to reproduce

Expected current result before the fix:

```text
run exit: 65
state.status: failed
state.failure.reason_code: state_integrity_failed
state.failure.detail: plan result shape is invalid
state.failure.partial_worktree: absent
worktree: dirty
attempt.completed: false
```

Then:

```text
resume --retry-failed exit: 65
detail: dirty worktree has no exact resumable checkpoint
provider launch count: unchanged
```

### Required behavior after the fix

For the same fake scenario:

```text
first controller:
  checkpoints the attempt before result validation terminates recovery
  seals the exact dirty worktree
  selects a fresh-session strategy
  remains recovering while the controller is alive

external resume, if needed:
  accepts the exact unchanged sealed tree
  rejects any post-checkpoint drift before provider launch
```

## Required regression tests

### Engine tests

1. `test_dirty_invalid_plan_result_is_sealed_before_recovery`
2. `test_dirty_malformed_stream_is_sealed_before_recovery`
3. `test_dirty_oversized_stream_is_sealed_before_recovery`
4. `test_dirty_transport_failure_is_sealed_before_recovery`
5. `test_dirty_context_overflow_is_sealed_before_fresh_session`
6. `test_dirty_stall_is_sealed_before_recovery`
7. `test_dirty_failed_attempt_resumes_only_with_exact_identity`
8. `test_dirty_failed_attempt_rejects_porcelain_drift`
9. `test_dirty_failed_attempt_rejects_content_only_tree_drift`
10. `test_dirty_failed_attempt_rejects_dirty_to_clean_drift`
11. `test_dirty_failed_attempt_rejects_symlink`
12. `test_dirty_failed_attempt_rejects_protected_ref_drift`
13. `test_invalid_result_attempt_is_completed_and_audited`
14. `test_failure_update_preserves_partial_checkpoint`
15. `test_live_controller_recovers_dirty_provider_failure_without_external_resume`

### Provider tests

1. oversized non-critical JSONL event is bounded and diagnosed;
2. an oversized event does not silently count as progress;
3. a later valid final result can still be read when policy permits;
4. missing root `turn.completed` rejects the output file;
5. commentary-phase schema-shaped text is not accepted as final;
6. collaboration-like events do not corrupt root result selection;
7. file-backed installed authentication works in isolated HOME;
8. unavailable file-backed authentication is classified as an auth blocker;
9. auth material never appears in stderr tails, state, or launch logs.

### Storage and contract tests

1. new partial-attempt outcome values are schema-bounded;
2. failure checkpoints survive unrelated failure-detail updates;
3. repair audit artifacts are immutable and digest-addressed;
4. state revision compare-and-swap rejects concurrent repair;
5. older v1 state remains readable or fails with an explicit version boundary;
6. no automatic migration silently marks an unsealed dirty tree as trusted.

### Live canaries

1. file-backed Codex authentication under isolated HOME;
2. large tool output followed by a valid final result;
3. one root session plus one collaboration subagent;
4. provider edit followed by forced malformed final output in a disposable
   repository;
5. interruption after edit and exact-session resume.

## Acceptance criteria

The defect is fixed only when all of the following are true.

### Recovery correctness

- [ ] Every mutation-capable provider attempt records a durable post-provider
      Git identity before semantic result validation can return.
- [ ] A dirty but safe provider-failure tree is bound to its exact attempt.
- [ ] A live controller can continue bounded recovery from that exact tree.
- [ ] An external resume can continue the exact sealed tree when required.
- [ ] Any HEAD, branch, porcelain, content, path, or protected-ref drift is
      rejected before provider launch.
- [ ] Unsafe symlinks and path escapes remain non-resumable.

### Result-boundary correctness

- [ ] Provider stream errors have provider-specific reason codes.
- [ ] State-integrity errors remain distinct.
- [ ] A commentary-phase schema-shaped message is never accepted as final.
- [ ] A final result requires a completed root turn.
- [ ] Collaboration events do not replace or corrupt the root final result.
- [ ] Oversized events are bounded without losing recovery evidence.

### Authentication correctness

- [ ] Supported Codex authentication modes are documented.
- [ ] File-backed authentication works with isolated HOME or fails with a
      precise auth blocker.
- [ ] No secret content is copied into logs, state, packets, or artifacts.

### Evidence

- [ ] Focused provider, engine, storage, and contract tests pass.
- [ ] New composition regressions fail on the old implementation and pass on
      the fix.
- [ ] Full `skills/kws-codex-plan-runner/evals/run.sh` passes once at final
      candidate HEAD.
- [ ] Installed Codex flag/JSONL contract passes.
- [ ] Explicit live canaries pass in disposable repositories.
- [ ] Codex/Claude parity implications are reviewed rather than assumed.

### Documentation

- [ ] `SKILL.md` and `README.md` describe dirty provider-failure recovery.
- [ ] Public exit-code and retry semantics remain accurate.
- [ ] Any new repair command is documented as an explicit, audited recovery
      boundary.
- [ ] `CHANGELOG.md` records the defect and compatibility behavior.

## Current-run recovery guidance

### What must not be done

Do not:

- manually edit `state.json`;
- invent a `partial_worktree` object;
- change an attempt outcome by hand;
- commit the partial tree merely to make it clean;
- stash, reset, or delete the partial work;
- weaken `_require_sealed_partial_worktree`;
- retry the same `resume` command expecting a different result;
- claim that the partial implementation is verified;
- claim `ready_for_integration`;
- merge, push, or deploy the product branch.

These actions either destroy forensic evidence or manufacture trust the runner
did not establish.

### Safest forward-only recovery

After fixing and validating the runner, the safest general recovery is:

1. preserve the existing run, worktree, and state as forensic evidence;
2. export a bounded patch and untracked-file manifest without changing the
   original worktree;
3. start a clean new runner worktree from the intended base;
4. apply the reviewed patch as untrusted input;
5. require a fresh provider to review every adopted change;
6. continue the approved plan from the clean runner state;
7. regenerate all evidence at the final candidate HEAD.

This does not satisfy a requirement that the original run ID must continue.

### Same-run recovery

Same-run continuation requires the audited repair capability described above.
For this incident, such a repair would need to bind:

- state revision `29`;
- attempt `e8c49076-9ddd-425f-a05d-a6810ab8b8db`;
- branch and HEAD shown in this report;
- the current porcelain and tree digests;
- an explicit operator attestation;
- a fresh-session full-diff review.

Until that capability exists and passes deterministic tests, the current run
should remain blocked.

## Rollout plan for the fix

1. Add failing deterministic composition tests.
2. Refactor attempt checkpoint ordering.
3. Add provider-specific failure taxonomy.
4. Generalize exact partial-worktree outcomes.
5. Add drift and unsafe-path regressions.
6. Add file-backed authentication tests and bootstrap.
7. Add collaboration and oversized-event live canaries.
8. Run focused tests during implementation.
9. Run the full deterministic eval once at final candidate HEAD.
10. Review Codex/Claude semantic parity.
11. Update `SKILL.md`, `README.md`, and `CHANGELOG.md`.
12. Release a new runner version.
13. Implement the separately gated forensic repair command if same-run
    recovery of existing incidents is required.

## Risk analysis

### Risk: accidentally trusting arbitrary dirty state

Mitigation:

- seal immediately after the provider process exits;
- bind to attempt, mode, plan, branch, HEAD, and two digests;
- preserve protected-ref checks;
- reject unsafe paths;
- compare state revision atomically.

### Risk: treating malformed provider output as usable implementation evidence

Mitigation:

- a sealed partial tree is not an implemented plan;
- force a fresh provider session to review the complete diff;
- do not accept task-ledger completion or verification claims from the malformed
  result;
- regenerate verification after commits.

### Risk: repair command becomes an integrity bypass

Mitigation:

- explicit operator authorization;
- no live processes;
- exact failed revision;
- immutable repair audit;
- narrow accepted failure reasons;
- no automatic adoption;
- full fresh-session diff review;
- exact-digest resume only.

### Risk: copying provider credentials broadens secret exposure

Mitigation:

- copy only the minimum auth file;
- reject symlinks and wrong ownership;
- private directory and `0600` file mode;
- never persist content or hashes in runner state;
- scrub error output;
- test absence from logs and artifacts.

## Evidence inventory

### Durable state

```text
Path:
$HOME/.codex/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c/state.json

SHA-256:
e1d6d9d856fcc6761b7b276fdfe5692d7f0fc13a704c57fc45a3540febf5b0c7
```

### Recovery audit: first invalid plan result

```text
Path:
.../artifacts/recovery_audit/ea3eca71c48fc2864205e414d7190bd794bd2e35199c3045c530ce256af0d002.json

SHA-256:
ea3eca71c48fc2864205e414d7190bd794bd2e35199c3045c530ce256af0d002
```

### Recovery audit: second invalid plan result

```text
Path:
.../artifacts/recovery_audit/d50fff66100cac722f5acbe35e4315223fe6e2fbaafe5fe2dbbe5635c5a63f13.json

SHA-256:
d50fff66100cac722f5acbe35e4315223fe6e2fbaafe5fe2dbbe5635c5a63f13
```

### Recovery audit: unsafe symlink

```text
Path:
.../artifacts/recovery_audit/824d20c4ef6253e6192e31862be66e94e3aa7fa766447b5b449d818360c42638.json

SHA-256:
824d20c4ef6253e6192e31862be66e94e3aa7fa766447b5b449d818360c42638
```

### Provider rollout: oversized output attempt

```text
Session:
019f93b3-b2ee-7c52-b778-2c24414322c5

SHA-256:
ed35dfdca094118b6808b64aff6fafa68c994d2fa0ceb338fd302fdf6d047738
```

### Provider rollout: collaboration/partial-edit attempt

```text
Session:
019f93b5-911e-7041-a2b9-66eae5962c58

SHA-256:
f562f480949d4970ad1ca864d86f11041fcb81f1d9949013d378b62031fe189d
```

The rollout files may contain large tool output and internal provider records.
They should be shared only through the appropriate internal evidence channel,
not pasted wholesale into a public issue.

## Relevant source files

- [`scripts/plan_runner/engine.py`](../../skills/kws-codex-plan-runner/scripts/plan_runner/engine.py)
  - `_require_git_contract`
  - `_require_sealed_partial_worktree`
  - `_execute_current_plan`
  - `_checkpoint_outcome`
  - `_pause_resumable`
  - `_validated_plan_result`
  - `_integrity_failure`
  - `_fail_closed`
- [`scripts/plan_runner/provider.py`](../../skills/kws-codex-plan-runner/scripts/plan_runner/provider.py)
  - `MAX_JSONL_LINE_BYTES`
  - `CodexAdapter.build_argv`
  - `CodexAdapter.launch`
  - `_consume_stdout`
  - `_read_result`
- [`scripts/plan_runner/git_ops.py`](../../skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py)
  - `_observation_digests`
  - `_regular_file`
  - `GitWorkspace.require_identity`
- [`evals/test_engine.py`](../../skills/kws-codex-plan-runner/evals/test_engine.py)
  - signal-based dirty checkpoint tests
- [`evals/test_provider.py`](../../skills/kws-codex-plan-runner/evals/test_provider.py)
  - malformed and oversized provider stream tests
- [`evals/fake_codex.py`](../../skills/kws-codex-plan-runner/evals/fake_codex.py)
  - deterministic provider scenarios
- [`SKILL.md`](../../skills/kws-codex-plan-runner/SKILL.md)
- [`README.md`](../../skills/kws-codex-plan-runner/README.md)
- [Approved runner design](../superpowers/specs/2026-07-23-quality-first-provider-plan-runners-design.md)
- [Approved Codex runner implementation plan](../superpowers/plans/2026-07-23-codex-quality-first-plan-runner.md)

## Copy-ready concise issue description

### Description

When a Codex provider modifies the runner worktree and then returns malformed
JSONL or an invalid plan-result envelope, `_execute_current_plan` calls
`_integrity_failure` before `_checkpoint_outcome`. `_fail_closed` records only
`reason_code` and `detail`, so the exact dirty worktree is not sealed. Every
later `resume` sees a dirty worktree with no `partial_worktree` and fails before
provider launch.

### Expected

The controller should atomically bind any safe dirty provider tree to its
attempt before semantic result validation can terminate recovery. A live
controller should enter bounded recovery; an external resume should accept only
the exact unchanged sealed tree.

### Actual

The run becomes permanently failed:

```text
state_integrity_failed
dirty worktree has no exact resumable checkpoint
```

### Reproduction

Use a fake provider that:

1. emits a session ID;
2. edits the assigned worktree;
3. writes invalid structured output;
4. exits.

The initial run exits with an invalid result and leaves a dirty tree without a
checkpoint. A retry exits before provider launch with the missing-checkpoint
error.

### Proposed fix

Checkpoint attempt/session/post-provider Git identity before semantic result
validation. Add bounded partial outcomes for provider failures, preserve exact
digest drift rejection, separate provider protocol failures from state
integrity failures, and add dirty-plus-malformed composition tests.

## Final assessment

The runner's final refusal to trust the current dirty worktree is correct. The
bug is that an earlier provider-result failure was allowed to create an
unsealed dirty state that no supported recovery path can adopt.

This is a durable-recovery contract gap in `kws-codex-plan-runner` 1.0.0 and
should be fixed before relying on the runner for long mutation-heavy provider
sessions.

## Remediation closeout (2026-07-25)

**Status:** resolved for new runs and for the one narrowly provable historical
repair shape.

The original forensic evidence remains unchanged. The implemented behavior is
defined by the [approved remediation design](../superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md),
the [core-correctness plan](../superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md),
and the [permission/recovery plan](../superpowers/plans/2026-07-24-codex-plan-runner-permission-recovery.md).
The implementation range is inclusive from `3c93a09e` through `c3a30f61`.

Focused regressions cover checkpoint-before-result validation for invalid,
malformed, oversized, transport, and permission outcomes; exact dirty
checkpoint resume; branch/product-ref drift rejection; safe fresh-root
recovery; and CAS-bound `unsealed-provider-partial` repair with semantic claims
discarded. Coverage lives in `evals/test_engine.py`,
`evals/test_storage.py`, `evals/test_provider.py`, and
`evals/test_recovery.py`.

The disposable candidate canary sealed the post-provider clean HEAD, helper
verification receipt, and final verification set before structured review.
After a focused output-schema compatibility fix, the same preserved run
finalized successfully with no findings or obligations and reached
`ready_for_integration` at
`1773ba770e2b69d975675762cd3b466592a30dd6`.

The canonical final deterministic gate is:

```bash
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

The reported historical run
`2026-07-24-calm-craft-responsive-reference-integ-21fbe848-7ed4-428c-8698-f1dac1eb565c`
was inspected read-only at revision `29`. It is a legacy failed state without a
sealed Git identity, and its recorded worktree no longer exists. Both repair
contracts require that exact worktree, common directory, branch, ancestry,
refs, inputs, and attempt evidence to remain provable. Therefore no safe
`repair` command applies; the state was left untouched.

The deliberate residual boundary is unchanged: arbitrary dirty work is never
adopted. Historical partial repair is available only for one recorded
incomplete implementation or review-fix attempt whose exact current Git
identity and all other proofs still match.

## Whole-review hardening addendum (2026-07-25)

Follow-up runtime commit `9b8c14ad` makes process quiescence part of those
proofs. Provider attempts durably record the controller/helper PID, provider
PID and process-group ID, and observed descendant PIDs as soon as they become
available. Historical `unsealed-provider-partial` repair now fails closed when
that process evidence is missing or when any recorded process/group remains
live; it never adopts a tree while an old provider may still mutate it.

Focused provider regressions prove the process callback is persisted during
the attempt, not only after provider exit. Storage rejects malformed process
evidence, and engine regressions cover missing historical evidence, a live
group, and a quiescent group.

## Whole-review round 2 correction (2026-07-25)

**Current status:** new `unsealed-provider-partial` adoption is disabled.

The earlier quiescence addendum was necessary but not sufficient. A provider
child can call `setsid()`, leave the recorded process group, outlive its parent,
and become unobservable through the recorded parent ancestry. Once reparented,
portable same-host PID/PGID polling cannot prove that no such descendant
exists. Treating an empty original group and dead recorded PIDs as complete
proof would be unsafe.

A real-process regression launches that exact detached-child shape. It
reproduces the former false quiescence and now receives exit `65` with no state,
artifact-ref, or worktree adoption while the child is demonstrably live.
Because no complete proof is available within the lightweight standard-library
boundary, there is currently no condition under which a new historical partial
is adopted. The compatibility repair kind remains parseable, preserves
evidence, and fails closed; already sealed historical adopted-partial audit
records remain readable and integrity-checked.
