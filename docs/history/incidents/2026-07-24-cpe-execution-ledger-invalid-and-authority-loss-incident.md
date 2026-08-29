# CPE 2.1 `execution_ledger_invalid` and authority-loss incident

## Status

- Confirmed on 2026-07-24.
- Affected runtime: `skills/kws-codex-plan-executor/` version 2.1.0,
  format-3 run state.
- Affected run: `cpe-4e9bd86b31dc47e6`.
- Current disposition: preserved failed run; no manual ledger deletion,
  worktree rewrite, second CPE run, merge, push, or remote mutation.
- Required resolution: a fail-closed, digest-bound same-run recovery path plus
  explicit launch-authority provenance.

This is a `kws-codex-plan-executor` incident. It is separate from the
`kws-codex-plan-runner` incidents documented elsewhere under
`docs/history/incidents/`.

## Executive summary

CPE successfully created one isolated worktree, launched one Codex controller,
and allowed the controller to implement and independently review Task 0 of an
approved 19-task Canvas Clone plan. The Task 0 RED/GREEN and task verification
passed.

The controller then wrote `.superpowers/sdd/execution-ledger.jsonl` using a
legacy task-summary shape:

```json
{
  "plan_id": "plan-01",
  "task_id": "task-0",
  "status": "complete",
  "base_head": "4d0153c3ec347dbdaff32642426c466c5b7a607d",
  "head": "4d0153c3ec347dbdaff32642426c466c5b7a607d",
  "commit_created": false,
  "review": "approved",
  "report_path": ".superpowers/sdd/task-0-report.md",
  "verification_receipt": ".artifacts/developer-productivity/verification/1784896071444-49450.json"
}
```

CPE format 3 accepts only strict execution-event objects. A task completion
event requires fields such as:

```json
{
  "schema_version": 1,
  "event_id": "task.completed:task-0",
  "source": "child_attested",
  "plan_id": "plan-01",
  "category": "task",
  "action": "completed",
  "result": "pass",
  "evidence_refs": ["task-0-report.md"],
  "task_id": "task-0",
  "duration_ms": 0
}
```

The strict validator correctly rejected the legacy object. The recovery path
then deadlocked: `resume --retry-failed` validates the existing ledger before
launching a controller, so the controller that created the malformed ledger
never receives a recovery capsule or an opportunity to replace it.

A second independent boundary also failed. The parent Goal explicitly granted
implementation and local checkpoint-commit authority, but CPE snapshots only
the spec and plan files. The direct child does not inherit the parent
conversation. Its 963-byte launch prompt did not carry the granted authority.
The plan itself correctly stated that document approval, implementation
authority, and commit authority are separate. The child therefore left the
verified Task 0 changes uncommitted and reported that explicit commit authority
had not been granted.

The incident is therefore not a Canvas Clone product failure. It is a CPE
launch-contract and recovery-contract defect:

1. the runtime requires a strict ledger without giving the child a complete,
   machine-readable ledger-writing contract;
2. the runtime does not snapshot the operator's implementation/commit
   authority for the isolated child;
3. an invalid child ledger is terminal even when its exact bytes and worktree
   state are available and unchanged.

## User-visible impact

- The approved implementation stopped after Task 0 of Tasks 0–18.
- Task 0 source changes and evidence remained in the CPE worktree but were not
  committed.
- The accepted CPE branch handoff was never produced.
- `verify:branch`, local-main integration, and canonical `verify:release` could
  not run.
- One controller launch consumed approximately 1.71 million input tokens,
  including approximately 1.59 million cached input tokens, before the
  post-execution integrity failure.
- Repeated `--retry-failed` attempts could not launch a controller and could
  not make progress.
- Starting a second CPE run would replay Task 0 and violate the requested
  one-run/same-RUN_ID recovery contract.

No remote repository state was changed.

## Confirmed affected run

### Immutable input identity

| Field | Observed value |
| --- | --- |
| Run ID | `cpe-4e9bd86b31dc47e6` |
| Run format | `3` |
| Plan ID | `plan-01` |
| Branch | `codex/cpe-4e9bd86b31dc47e6` |
| Source/starting/observed HEAD | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |
| Controller launches | `1` |
| Attempt count | `1` |
| Sandbox | `danger-full-access` |
| Controller slice | `3600` seconds |
| Plan wall budget | `7200` seconds |
| Spec SHA-256 | `744b7b2512c68cad4e5003b60121a147f1e74a6a47a0dc4bd090ba6e679c5bc7` |
| Plan SHA-256 | `97647061df811534746df45000e8a7dba679de8a897c9b10bd955d59ba03da9a` |
| Invalid ledger SHA-256 | `a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80` |

### Private runtime evidence

The paths below are operator-private runtime evidence and are not tracked
product artifacts:

```text
~/.codex/orchestrator/cpe-4e9bd86b31dc47e6/state.json
~/.codex/orchestrator/cpe-4e9bd86b31dc47e6/events.jsonl
~/.codex/orchestrator/cpe-4e9bd86b31dc47e6/results/plan-01-attempt-1.json
~/.codex/orchestrator/cpe-4e9bd86b31dc47e6/logs/plan-01-attempt-1.log
~/.codex/worktrees/cpe-4e9bd86b31dc47e6/.superpowers/sdd/execution-ledger.jsonl
~/.codex/worktrees/cpe-4e9bd86b31dc47e6/.superpowers/sdd/task-0-report.md
```

Do not copy raw provider logs or full transcripts into the repository. The
bounded facts in this report are sufficient to reproduce and repair the
contract.

## Timeline

All times below are UTC.

| Time | Event |
| --- | --- |
| `12:21:00.469` | `run.created`, status `ready` |
| `12:21:00.469` | immutable inputs prepared |
| `12:21:00.923` | isolated worktree ready at source HEAD |
| `12:21:01.196` | plan attempt 1 started |
| `12:29:31.858` | provider returned successfully after `510659 ms` |
| `12:29:31.921` | CPE recorded `plan.integrity_failed` with `execution_ledger_invalid` |
| `12:30:57.552` | operator requested `resume --retry-failed` |
| immediately after | resume returned `execution_ledger_invalid` without a second controller launch |

The provider transport itself returned code 0. The failure occurred during
parent-side progress-ledger validation after the child result was available.

## Expected behavior

For an approved implementation run:

1. CPE snapshots the ordered immutable inputs and the exact authority granted
   for the isolated child.
2. The launch packet supplies the worktree, plan/spec paths, current Git facts,
   strict result schema, execution-ledger schema and append rules, verification
   helper contract, and authority provenance.
3. The child implements the ordered plan, creates only authorized local
   checkpoint commits, and appends schema-valid execution events.
4. CPE validates and records durable progress.
5. If the child produces an invalid ledger, CPE preserves the exact bytes,
   refuses to trust their semantic claims, and offers one explicit,
   digest-bound recovery action.
6. After recovery, the same RUN_ID, worktree, branch, starting commit, budgets,
   and immutable inputs are reused.
7. No second run is created merely to escape a recoverable ledger-format
   failure.

## Actual behavior

1. CPE snapshotted the spec and plan but not the parent Goal's authority.
2. The launch prompt supplied `EXECUTION_LEDGER: <path>` but no schema path,
   schema digest, allowed event examples, or append helper.
3. Installed Superpowers durable progress guidance owns
   `.superpowers/sdd/progress.md`; it does not define the CPE format-3 JSONL
   schema.
4. The child wrote one legacy summary object.
5. The child result reported Task 0 complete, verified, reviewed, and
   uncommitted because commit authority was unavailable.
6. `runner._progress_snapshot()` rejected the legacy object and changed the run
   to `failed`.
7. `resume --retry-failed` called `_progress_snapshot()` before creating a
   recovery capsule or launching the next controller.
8. The same malformed bytes caused the same failure. The controller launch
   count remained one.

## Root cause analysis

### RC-1: strict consumer without an explicit producer contract

The source of truth exists at:

```text
skills/kws-codex-plan-executor/templates/execution-ledger.schema.json
```

The runtime validator in `scripts/cpe_runtime/evidence.py` requires exact
properties and rejects unknown or missing fields. This strictness is correct
for trust and evidence sealing.

The launcher in `scripts/cpe_runtime/launcher.py`, however, passes only:

```text
EXECUTION_LEDGER: <path>
```

It does not pass:

- the schema path;
- the schema SHA-256;
- an append helper;
- allowed trust levels for child-written events;
- category-specific required fields;
- evidence-reference containment rules;
- instructions not to write legacy progress-summary objects.

This makes correct production of strict evidence dependent on model inference.
That is incompatible with a fail-closed evidence format.

### RC-2: CPE and Superpowers use different durable-progress contracts

The installed `subagent-driven-development` skill documents:

```text
.superpowers/sdd/progress.md
```

CPE format 3 requires:

```text
.superpowers/sdd/execution-ledger.jsonl
```

CPE correctly says that Superpowers owns workflow semantics, but it also
requires CPE-specific evidence. The integration boundary does not currently
state who emits the CPE event, by what API, and from which workflow decision.

The fix must not modify Superpowers upstream. CPE must provide its own narrow
evidence adapter or append command.

### RC-3: invalid-ledger recovery is circular

`resume --retry-failed` must inspect prior progress before it launches the next
controller. For valid ledgers, this protects against progress regression.

For invalid ledgers, the same ordering creates a cycle:

```text
controller must run to repair its ledger
                 ↑
resume refuses to run until the ledger validates
```

No public `ledger-inspect`, `ledger-quarantine`, or digest-bound repair command
exists. `verify` cannot help because it requires an active run and appends to
the same invalid file.

### RC-4: launch authority is not an immutable input

The parent request explicitly authorized:

- implementation start;
- local checkpoint commits in the CPE worktree;
- evidence-based Golden Slice decisions;
- exact-case baseline promotion;
- later supervisor-owned local integration.

The child sees only input documents and the small launcher prompt. The approved
plan says that design approval, implementation authority, snapshot approval,
commit authority, integration, and remote actions are separate decisions.

Because CPE does not snapshot the parent's authority, the child made the safe
but operationally incomplete choice to avoid committing. This was a correct
response to the information it received.

Authority must be represented as bounded data, not inferred from the existence
of a worktree or from an outer conversation the child cannot access.

### RC-5: the result and progress channels can disagree

The child result was schema-valid enough to report `checkpointed`, Task 0
completion, and verification observations. The progress ledger was invalid.
CPE correctly rejected the combined handoff, but inspect output retained only
the coarse `execution_ledger_invalid` reason.

The operator could not see from `inspect`:

- which ledger line failed;
- the rejected ledger digest;
- whether the file was regular and path-contained;
- whether the error was invalid JSON, property mismatch, source mismatch,
  duplicate ID, or regression;
- the exact supported next action.

This prolonged diagnosis and encouraged unsafe temptations such as deleting the
ledger or starting a duplicate run.

## Contributing changes and why earlier runs could pass

This incident does not prove that every earlier CPE run used the same runtime
and failed silently. Several conditions can explain prior successful runs:

- an earlier launcher prompt included more workflow and recovery guidance;
- an earlier run used a different state/evidence format;
- a plan included implementation and commit authority in the submitted
  documents;
- a child happened to use the verification helper, producing valid CPE events;
- a child did not create a conflicting legacy ledger before CPE-owned
  verification events were appended.

The current failure is deterministic once the observed legacy ledger exists.
The non-deterministic part is whether an under-specified child produces the
strict format in the first place.

Git history shows that the CPE prompt was deliberately narrowed as part of the
strict-thin work. Thin orchestration remains the right boundary, but removing
schema and authority facts was too aggressive: those are transport contracts,
not workflow-policy decisions.

## Safety constraints for remediation

The remediation must preserve all existing CPE boundaries:

- one reused isolated worktree and branch;
- Python standard-library runtime;
- Superpowers ownership of tasks, implementation choices, tests, reviews, and
  fixes;
- no plan compiler or CPE-owned task mapping;
- no automatic merge, push, deploy, publication, tag, or history rewrite;
- no trust in malformed ledger claims;
- no broad deletion of `.superpowers`, worktrees, evidence, or run state;
- no silent new run for equivalent immutable inputs;
- no manual editing of the CPE worktree from outside CPE;
- no automatic authority expansion;
- exact digest, file identity, lock, process-liveness, worktree, branch, HEAD,
  source-input, and run-state revalidation before recovery.

## Recommended remediation

### R-1: snapshot a bounded launch-authority document

Add an optional immutable run input with a strict schema, for example:

```json
{
  "schema_version": 1,
  "authority_id": "canvas-calm-craft-goal-2026-07-24",
  "implementation": true,
  "local_checkpoint_commits": true,
  "visual_review_decision": "evidence-gated-delegated",
  "baseline_promotion": "exact-approved-cases-only",
  "local_integration": false,
  "push": false,
  "pull_request": false,
  "deploy": false,
  "tag": false,
  "history_rewrite": false,
  "source": "operator-submitted",
  "submitted_at": "2026-07-24T00:00:00Z"
}
```

The exact public shape may be smaller, but it must:

- be supplied explicitly by the operator or supervisor;
- be snapshotted under the run root before launch;
- be included in immutable input identity and equivalent-run matching;
- distinguish local child authority from supervisor-only integration;
- default every absent capability to false;
- never infer remote mutation authority from implementation authority;
- be passed to every initial, resumed, review-fix, and later-plan child;
- be preserved in private run evidence without embedding the parent transcript.

If the public CLI does not accept authority yet, a supervisor-owned
machine-readable file is preferable to free-form prompt text.

### R-2: provide a CPE-owned ledger append interface

Do not require the model to hand-author strict JSONL.

Add a narrow command such as:

```bash
python3 scripts/cpe.py ledger-append \
  --run-id RUN_ID \
  --event-file /absolute/path/to/private-event.json
```

or a run-private descriptor similar to the verification helper.

The helper must:

- acquire the run lock or use a safely scoped append lock;
- validate the run, plan ID, worktree, branch, and current attempt;
- accept only child-attested categories and actions appropriate to its caller;
- validate against the runtime contract, not only a divergent JSON Schema
  implementation;
- reject symlinks, path escapes, oversized events, unknown fields, duplicate
  IDs, and invalid evidence references;
- append with `O_NOFOLLOW`, `O_APPEND`, mode `0600`, `fsync`, and directory
  durability;
- return a bounded receipt containing the event digest;
- never translate an arbitrary legacy summary into trusted events.

The launcher should pass:

```text
EXECUTION_LEDGER_HELPER_DESCRIPTOR: <run-private path>
EXECUTION_LEDGER_SCHEMA: <tracked or snapshotted path>
EXECUTION_LEDGER_SCHEMA_SHA256: <digest>
```

The schema remains useful for orientation and independent validation; the
helper is the authoritative write path.

### R-3: add explicit digest-bound invalid-ledger recovery

Add a public recovery surface, for example:

```bash
python3 scripts/cpe.py ledger-inspect --run-id RUN_ID

python3 scripts/cpe.py ledger-recover \
  --run-id RUN_ID \
  --sha256 a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80 \
  --strategy quarantine-and-restart-ledger
```

`ledger-inspect` is read-only and should report:

- regular-file and symlink status;
- byte size and SHA-256;
- first failing line;
- bounded reason code;
- last accepted event count and digest prefix;
- current run/plan/attempt status;
- process and lock status;
- exact allowed recovery command, if any.

`ledger-recover` must require:

1. run status `failed`;
2. last failure `execution_ledger_invalid`;
3. an exclusive run lock;
4. no live controller/provider/helper/descendant process;
5. exact ledger path beneath the saved worktree;
6. every path component non-symlinked;
7. regular file, bounded size, unchanged device/inode/size/digest;
8. exact operator-supplied SHA-256;
9. unchanged source inputs, worktree, branch, HEAD, and product refs;
10. no previously accepted execution-event digest that would regress;
11. a recoverable invalid-schema classification rather than unknown state
    corruption.

The command must:

- copy or atomically move the rejected bytes into a private run-root quarantine
  with mode `0400`;
- write a manifest with original path, digest, size, identity, reason, run,
  plan, attempt, observed HEAD, and recovery timestamp;
- `fsync` the quarantine payload, manifest, and containing directory;
- remove or replace the invalid worktree ledger only after quarantine succeeds;
- append a parent-observed `ledger.quarantined` event to the run event stream;
- leave semantic Task 0 completion untrusted until the next child inspects the
  diff and reruns required verification;
- change the run to a specifically resumable recovery state;
- print the exact same-RUN_ID resume command.

It must refuse:

- digest mismatch;
- file replacement or inode swap;
- symlink or non-regular file;
- live owner;
- changed HEAD/branch/worktree;
- protected-ref drift;
- missing or changed immutable inputs;
- an already recovered ledger;
- an invalid event suffix after previously accepted event digests unless a
  separate prefix-preserving policy is implemented and proven.

There must be no generic `--force`.

### R-4: preserve progress without trusting the malformed summary

For the affected run, the Task 0 diff and reports are useful but not trusted
completion evidence after ledger quarantine.

The recovery capsule must tell the next child:

- the rejected ledger is quarantined and must not be treated as accepted
  progress;
- inspect the complete worktree diff before editing;
- use the submitted plan and Task 0 report only as leads;
- rerun the focused Task 0 verification;
- obtain a clean independent Task 0 review;
- create the authorized checkpoint commit;
- append new events using the CPE helper;
- continue at Task 1 only after those facts pass.

This costs extra verification but avoids replaying implementation or trusting
unvalidated legacy metadata.

### R-5: make `resume --retry-failed` return an actionable diagnosis

When pre-launch progress validation fails, return structured output such as:

```json
{
  "status": "failed",
  "error": "execution_ledger_invalid",
  "recoverable": true,
  "ledger": {
    "sha256": "a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80",
    "bytes": 356,
    "first_invalid_line": 1,
    "reason_code": "execution_event_properties_invalid"
  },
  "recommended_action": [
    "python3",
    "scripts/cpe.py",
    "ledger-recover",
    "--run-id",
    "cpe-4e9bd86b31dc47e6",
    "--sha256",
    "a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80",
    "--strategy",
    "quarantine-and-restart-ledger"
  ]
}
```

If the failure is not safely recoverable, report `recoverable: false` and omit
the recovery command.

### R-6: restore factual launch context without restoring workflow policy

The strict-thin launcher may remain small. It still must convey transport facts
needed for safe execution:

- the plan is being launched under explicit implementation authority, if and
  only if the immutable authority input says so;
- whether local checkpoint commits are authorized;
- which actions remain supervisor-only or prohibited;
- the ledger helper/schema contract;
- the verification helper contract;
- the recovery capsule and rejected-ledger manifest on recovery.

These are not task selection or quality-policy decisions. They are capabilities
and transport facts already decided outside the child.

## Proposed implementation surface

Keep the production change narrow:

| File | Responsibility |
| --- | --- |
| `scripts/cpe.py` | Add bounded authority input and ledger inspect/recover/append commands |
| `scripts/cpe_runtime/state.py` | Store immutable authority identity and ledger recovery metadata |
| `scripts/cpe_runtime/launcher.py` | Pass authority, ledger schema/helper, and recovery facts |
| `scripts/cpe_runtime/evidence.py` | Inspect, quarantine, validate, and append ledger evidence safely |
| `scripts/cpe_runtime/runner.py` | Gate recovery state transitions and same-run resume |
| `scripts/cpe_runtime/result_validation.py` | Only if result/recovery reporting needs a strict new field |
| `templates/execution-ledger.schema.json` | Keep synchronized with runtime validation |
| `templates/plan-result-schema.json` | Only if child result needs authority/recovery provenance |
| `README.md` and `SKILL.md` | Document the new public contract and recovery procedure |

Do not add a task compiler, database, Waygent dependency, third-party package,
or Superpowers modification.

## Required deterministic evals

Add focused RED tests before implementation.

### Launch contract

- The initial prompt includes a readable ledger helper descriptor, schema path,
  and exact schema digest.
- The prompt includes immutable authority and exact prohibitions.
- A run without implementation authority does not claim it.
- A run with implementation authority but without commit authority preserves
  that distinction.
- Resume, retry, review-fix, and later-plan launches receive identical immutable
  authority.
- The launcher does not include the parent transcript or secrets.

### Ledger writer

- A valid task event appends and validates.
- Every category uses the exact category-specific required fields.
- Unknown fields, invalid trust sources, invalid actions/results, duplicate
  IDs, oversized events, unsafe evidence paths, and symlinks fail.
- Concurrent append attempts serialize safely.
- A crash before `fsync` cannot publish a partially accepted event.
- The returned event digest matches canonical event bytes.
- The helper cannot append for another run, plan, worktree, or attempt.

### Recovery inspection

- The observed legacy Task 0 shape is classified as
  `execution_event_properties_invalid`.
- The observed 356-byte fixture produces the expected SHA-256.
- Invalid JSON, empty lines, oversized lines, duplicate IDs, wrong plan IDs,
  private trust sources, and progress regression retain distinct reason codes.
- Inspect is read-only.
- Inspect refuses symlinked or escaped run/worktree paths.

### Digest-bound quarantine

- Exact digest and stable file identity permit quarantine.
- Digest mismatch refuses without changing any file.
- Replacement between inspect and recover refuses.
- Inode, size, or mode change refuses.
- Live controller/provider/helper refuses.
- Lock contention refuses.
- Changed branch, HEAD, worktree, input digest, or protected ref refuses.
- Quarantine payload and manifest are private, immutable, and digest-correct.
- Crash before durable quarantine leaves the original ledger untouched.
- A completed quarantine cannot run twice.
- No accepted semantic completion event is invented.

### Same-run resume

- After a valid quarantine, the same run ID, worktree, branch, starting commit,
  plan index, sandbox, and budgets are preserved.
- Resume creates exactly one new controller attempt.
- Recovery capsule exposes the quarantine manifest and authority.
- The child can append a fresh valid Task 0 event.
- Task 0 must be reverified and reviewed before Task 1 is accepted.
- A new run is not created.
- A second invalid ledger fails with a bounded changed-strategy policy rather
  than looping forever.

### Authority

- Authority input is strict, bounded, immutable, and digest-bound.
- Unknown capability fields fail closed.
- Missing fields default to false only according to the documented schema.
- Local commit authority does not imply merge, push, deploy, tag, or rewrite.
- Integration authority remains unavailable to the CPE child when it is
  supervisor-owned.
- Authority cannot change on resume.
- An equivalent run with different authority is not silently reused.

### Regression

- Existing valid format-3 runs still resume.
- Existing malformed-ledger fail-closed tests still fail without explicit
  recovery.
- `provider_usage_blocked`, `provider_auth_blocked`,
  `provider_unavailable`, timeout, and result-envelope recovery are unchanged.
- Verification same-HEAD reuse remains exact.
- Completion still requires clean HEAD, valid ancestry, ledger/final-review
  paths, empty findings/obligations, and successful verification.
- Full `./evals/run.sh` passes once on the final clean candidate.

## Affected-run recovery procedure after the fix

Do not execute these commands until the implementation and focused evals pass.

1. Inspect without mutation:

   ```bash
   python3 skills/kws-codex-plan-executor/scripts/cpe.py \
     ledger-inspect --run-id cpe-4e9bd86b31dc47e6
   ```

2. Confirm:

   - run is failed for `execution_ledger_invalid`;
   - no owner process is alive;
   - branch and HEAD remain the recorded values;
   - the worktree diff is bounded to Task 0;
   - ledger SHA-256 is
     `a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80`;
   - immutable spec and plan digests still match.

3. Quarantine through CPE:

   ```bash
   python3 skills/kws-codex-plan-executor/scripts/cpe.py \
     ledger-recover \
     --run-id cpe-4e9bd86b31dc47e6 \
     --sha256 a04c557914f8e1a422fbfde91095710e1e744506ee1495f3db9b9e7f5756cb80 \
     --strategy quarantine-and-restart-ledger
   ```

4. Resume the same run:

   ```bash
   python3 skills/kws-codex-plan-executor/scripts/cpe.py \
     resume --run-id cpe-4e9bd86b31dc47e6 --retry-failed
   ```

5. Inspect after every controller slice:

   ```bash
   python3 skills/kws-codex-plan-executor/scripts/cpe.py \
     inspect --run-id cpe-4e9bd86b31dc47e6
   ```

6. Require Task 0 reverification, clean review, and an authorized checkpoint
   commit before accepting Task 1 progress.

If any expected identity differs, stop and preserve the run. Do not delete the
ledger, reset the worktree, or create a duplicate run.

## Acceptance criteria

- [ ] A child never needs to infer the execution-ledger schema.
- [ ] CPE owns a strict, safe append interface for child-attested events.
- [ ] The tracked schema and runtime validator cannot drift.
- [ ] Parent-granted implementation and local commit authority reaches every
      child as immutable, bounded provenance.
- [ ] Authority not granted remains unavailable.
- [ ] Remote and history-rewrite actions remain prohibited unless separately
      modeled, and remain outside the CPE child for this use case.
- [ ] `execution_ledger_invalid` inspect output identifies the exact bounded
      failure and whether recovery is supported.
- [ ] Recovery requires exact digest, file identity, run lock, process
      liveness, worktree/branch/HEAD/input equality, and an explicit strategy.
- [ ] Rejected ledger bytes are preserved before the worktree ledger changes.
- [ ] No malformed semantic claim is promoted to trusted progress.
- [ ] The same RUN_ID resumes without Task 0 replay or a second run.
- [ ] The affected run can reverify Task 0, create its authorized checkpoint,
      and proceed to Task 1.
- [ ] Valid existing format-3 runs remain compatible.
- [ ] Malformed-ledger recovery cannot weaken progress-regression checks.
- [ ] Focused deterministic evals pass.
- [ ] `python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py`
      passes.
- [ ] `bash -n evals/run.sh` passes.
- [ ] Final clean-candidate `./evals/run.sh` passes once.
- [ ] `SKILL.md` and `README.md` document the new commands and safety boundary.

## Explicit non-solutions

Do not resolve this incident by:

- deleting or hand-editing `execution-ledger.jsonl`;
- manually committing the CPE worktree outside CPE;
- resetting, rebasing, or replacing the CPE branch;
- starting a second equivalent CPE run;
- accepting the legacy summary as trusted completion evidence;
- weakening `_validate_execution_ledger_payload`;
- accepting unknown properties in the event schema;
- treating `--retry-failed` as permission to discard evidence automatically;
- passing the entire parent transcript to the child;
- modifying Superpowers upstream;
- adding a generic `--force` or “trust current state” option;
- broadening local implementation authority into merge, push, deploy, tag, or
  history-rewrite authority.

## Verification commands for the remediation implementation

During implementation, run the exact focused eval modules that own each
change. The final exact module names should follow the existing eval layout.
At minimum:

```bash
python3 evals/check_runner.py \
  ProgressDecisionTests \
  CheckpointTrustAndLedgerTests \
  ProgressRecoveryIntegrationTests

python3 evals/check_cli.py

python3 -m py_compile \
  scripts/cpe.py \
  scripts/cpe_runtime/*.py \
  evals/*.py

bash -n evals/run.sh
```

After independent review and all focused fixes, run exactly once from the clean
candidate:

```bash
./evals/run.sh
```

Do not claim the incident fixed from documentation, unit tests alone, or a new
synthetic run. The final live proof is recovery and continued progress of
`cpe-4e9bd86b31dc47e6` using the same run ID and worktree.

## Final assessment

The format-3 validator did its safety job: it rejected evidence that did not
match the trusted schema. The defect is that the producer contract and recovery
contract were incomplete.

The correct fix is not to relax validation. CPE must make strict evidence
producible, make externally granted authority visible as immutable data, and
make known invalid-ledger states recoverable only through an explicit,
digest-bound, evidence-preserving same-run transition.
