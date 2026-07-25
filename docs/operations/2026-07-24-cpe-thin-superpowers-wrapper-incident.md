# CPE thin Superpowers wrapper incident

## Status

- Lightweight-wrapper direction approved on 2026-07-24.
- Confirmed on 2026-07-24 against CPE 2.1 format-3 state.
- Triggering run: `cpe-43fd3d47337a4c0d`.
- Product repository: ReadMates.
- Run state at investigation time: `checkpointed`, plan 1 of 4 active, clean
  saved worktree, no merge or remote action.
- This is a diagnosis and lightweight repair proposal. It does not mutate or
  complete the affected run.

## Decision

CPE should remain a thin wrapper around Superpowers.

CPE should own only:

1. immutable plan/spec and a small execution note;
2. one isolated worktree and branch;
3. one resumable Codex controller session;
4. bounded process status and final branch handoff.

Superpowers should continue to own:

- task selection and sequencing;
- TDD and implementation;
- task progress;
- reviewer dispatch and finding resolution;
- commits;
- verification commands selected by the plan;
- final review semantics.

CPE should not grow into a second task orchestrator, review engine, event
store, or policy compiler.

## Why standalone SDD feels natural

`subagent-driven-development` has one controller for the whole workflow. That
controller reads the user's constraints, dispatches task-scoped implementers
and reviewers, records progress, and keeps the conversation that explains
what has already been approved.

The task subagents are fresh, but the workflow controller is not.

Current CPE does the opposite. Every slice starts a fresh top-level controller:

```text
codex exec --ignore-user-config --ephemeral --json ...
```

The new controller receives the plans and a short prompt, but not the outer
Goal that selected the workflow and granted authority. CPE then expects that
new controller to reconstruct Superpowers progress and also satisfy a separate
CPE ledger protocol.

The wrapper has become more complicated than the workflow it wraps.

## Confirmed incident

### 1. The approved workflow choice was lost

Each ReadMates plan says:

```text
Use subagent-driven-development (recommended) or executing-plans
```

The outer Goal made the final choice:

```text
Use executing-plans, execute sequentially, and do not use
subagent-driven-development.
```

CPE snapshots the plans, but not this small execution decision. Its child
prompt says only “Use Superpowers.” A fresh child therefore sees SDD as the
recommended choice and cannot know that the operator already selected
`executing-plans`.

This is lost input, not agent disobedience.

### 2. A valid checkpoint lost its completed task

Attempt 1 returned a valid checkpoint result saying Task 1 was complete.
CPE built the next recovery capsule only from
`.superpowers/sdd/progress.md`, where no accepted task line existed.

The capsule therefore said:

```json
{
  "completed_tasks": [],
  "current_task": null,
  "prior_status": "checkpointed"
}
```

The next fresh controller could not reliably tell that Task 1 had finished.
This led to repeated context loading and verification.

### 3. CPE added a second progress protocol

Standalone SDD documents `.superpowers/sdd/progress.md`. CPE additionally
requires `.superpowers/sdd/execution-ledger.jsonl` with a strict internal
event schema.

CPE 2.1.0 told the model to write that JSONL directly. The affected run wrote
a familiar task-summary object instead of the internal event shape. CPE
correctly rejected it as `execution_ledger_invalid`, but the failure shows that
the wrapper exposed its internal protocol to the workflow agent.

The strict validator is not the problem. The extra ledger should not be part
of the normal Superpowers path.

### 4. Updating CPE stranded the active run

The verification helper descriptor points to the mutable Archive checkout and
hashes `cpe.py` plus every `cpe_runtime/*.py` file.

The affected run started with the exact runtime tree at:

```text
4ad1c77d572bbe87a1726dc87d85da92bcad0843
```

Archive later advanced to CPE 2.1.1. Three saved source identities changed:

| Source | Saved digest prefix | Current digest prefix |
| --- | --- | --- |
| `cpe.py` | `a24019a73dd8` | `a290150944cc` |
| `cpe_runtime/launcher.py` | `c39b9e559f1a` | `347e9c9c5eaa` |
| `cpe_runtime/runner.py` | `ecd49f396c06` | `98a24e17426b` |

The next resume stopped before a controller launch:

```text
verification.helper_unavailable_no_request
verification helper descriptor was replaced
```

Failing closed was correct. Binding a small verification helper to every CPE
runtime source was not.

## Cost of the mismatch

| Attempt | Duration | Input tokens | Result |
| --- | ---: | ---: | --- |
| 1 | 185.134 s | 540,400 | Task 1 reported complete, checkpointed |
| 2 | 462.494 s | 2,842,492 | recoverable baseline failure |
| 3 | 335.534 s | 1,837,052 | invalid ledger rejection |
| 4 | 140.151 s | 540,791 | Task 2 started, checkpointed |

Total before the source-drift stop:

- 4 controller launches;
- 1,123.313 seconds of controller wall time;
- 5,760,735 input tokens;
- 5,413,888 cached input tokens;
- 22,102 output tokens.

The dominant waste came from replacing the workflow controller and rebuilding
context, not from product implementation.

## Lightweight target design

### 1. One CPE run uses one Codex controller session

Initial launch:

- remove `--ephemeral`;
- capture the bounded Codex session ID from the JSON event stream;
- persist only that ID and launch facts in CPE state.

Normal checkpoint resume:

```text
codex exec resume SESSION_ID ...
```

The same controller keeps the plan, user constraints, completed work, and
Superpowers workflow context. Fresh agents still exist where SDD wants them,
but CPE does not replace the workflow controller.

Before adopting this path, focused evals must prove that Codex resume preserves
the original worktree, sandbox, ignored user config, output schema, and remote
prohibitions. If the current CLI cannot prove those facts, retain a fresh
controller as a fallback, not the default.

### 2. Add one small execution note

CPE needs the operator decisions that are not inside the plan. It does not need
the complete outer conversation or a large policy schema.

Accept a small immutable file such as:

```json
{
  "workflow": "executing-plans",
  "sequential": true,
  "implementation": true,
  "local_commits": true,
  "integration": false,
  "remote_actions": false
}
```

Suggested CLI:

```bash
python3 scripts/cpe.py run \
  --execution-note /absolute/path/to/execution-note.json \
  --spec ... --plan ... --workspace ...
```

CPE snapshots it with the plans and passes it unchanged to the first
controller and any fallback controller.

This note resolves workflow choice and basic authority. It must not become a
task DSL.

### 3. Use Superpowers progress, not a second CPE ledger

Remove the normal requirement for:

```text
.superpowers/sdd/execution-ledger.jsonl
```

Superpowers keeps its existing progress/report/commit workflow. CPE records
only a small child-attested checkpoint in its result:

```json
{
  "status": "checkpointed",
  "completed_tasks": ["Task 1"],
  "current_task": "Task 2",
  "head_commit": "..."
}
```

This progress is coordination data, not proof that the task is correct.
Superpowers review artifacts, commits, and plan-selected tests remain the
evidence.

On a normal same-session resume, the controller already knows its progress.
The checkpoint fields are used for inspect output and fresh-session fallback.

CPE should validate only that task IDs are bounded strings and that HEAD is a
valid descendant. It should not interpret task semantics.

The existing `recover-ledger` command remains only for old format-3 runs that
already created the legacy ledger.

### 4. Keep verification inside Superpowers

Remove the run-critical verification helper and its source descriptor.

Superpowers and the approved plan already select and run:

- RED/GREEN tests;
- focused and full regressions;
- browser or device evidence;
- independent review;
- final branch verification.

The final result references the commands, exit codes, and safe evidence paths.
CPE validates field shape, path containment, final HEAD, ancestry, and clean
handoff. It does not execute a second verification workflow or bind the run to
the installed CPE source tree.

If stronger host-owned verification is required for a different product, it
should be a separate explicit supervisor step after CPE handoff, not a hidden
requirement of every CPE resume.

### 5. Keep CPE completion mechanical

CPE completion should check only facts it can verify cheaply:

- plans completed in submitted order;
- final HEAD descends from the starting HEAD;
- worktree is clean;
- submitted report paths are safe and exist;
- final review names the actual HEAD;
- submitted findings and obligations are empty;
- branch handoff records `integration=not_observed`.

Superpowers and the approved plan decide whether tests and review are
sufficient. CPE should not reproduce those workflows.

### 6. Use a small runtime contract version

Store one `runtime_contract_version` in CPE state. The installed CPE declares
which versions it can read and resume.

Compatible implementation changes do not invalidate active runs. A genuinely
incompatible change returns one actionable `runtime_contract_incompatible`
result and uses one narrow migration command.

Do not hash every installed CPE Python file and do not add a separate recovery
command for each helper or descriptor.

## Current-run recovery

The ReadMates run predates the thin contract, so it needs one compatibility
command:

```bash
python3 scripts/cpe.py migrate-run \
  --run-id cpe-43fd3d47337a4c0d \
  --descriptor-sha256 EXACT_DESCRIPTOR_SHA256 \
  --source-revision 4ad1c77d572bbe87a1726dc87d85da92bcad0843 \
  --execution-note /absolute/path/to/execution-note.json
```

The command should:

1. hold the run lock and prove no controller/helper process is alive;
2. verify the saved descriptor and every historical source digest;
3. verify worktree, branch, HEAD, and immutable input identity;
4. snapshot the operator-approved execution note;
5. migrate the run to the thin `runtime_contract_version`;
6. mark old helper receipts as historical, non-reusable evidence;
7. remove the old descriptor and child-ledger gates from future resume
   decisions without deleting their preserved evidence;
8. record one compatibility migration as a parent-observed event;
9. preserve the same run ID, worktree, branch, plan index, and budgets;
10. print the exact plain-resume command.

There is no generic `--force`, no manual state edit, and no second product run.

This is one run-format migration, not one repair command per artifact. It can
be removed after no active legacy run requires it.

## Small implementation sequence

### Step 1: preserve controller continuity

- store the Codex session ID;
- resume the same session after a normal checkpoint;
- add focused sandbox/worktree/schema inheritance tests.

### Step 2: preserve the missing operator choice

- add the six-field execution note;
- snapshot and pass it unchanged;
- ensure plan wording cannot override the selected workflow.

### Step 3: remove duplicate progress machinery

- add `completed_tasks` and `current_task` to the result schema;
- stop requiring the CPE execution ledger for new runs;
- build fallback recovery capsules from the checkpoint result and Git facts.

### Step 4: remove run-critical helper coupling

- keep verification in Superpowers;
- replace installed-source digests with `runtime_contract_version`;
- retain only mechanical final handoff validation.

### Step 5: recover the live ReadMates run

- add the single legacy `migrate-run` path;
- run focused evals and `./evals/run.sh`;
- perform an independent review;
- repair and resume the same ReadMates run;
- prove Task 1 is not repeated.

## File-level change map

| File | Minimal change |
| --- | --- |
| `scripts/cpe.py` | Add `--execution-note` and one legacy `migrate-run` |
| `scripts/cpe_runtime/state.py` | Store execution-note digest, Codex session ID, and runtime contract version |
| `scripts/cpe_runtime/launcher.py` | Capture session ID and use `codex exec resume` |
| `scripts/cpe_runtime/runner.py` | Prefer same-session resume and simplify checkpoint recovery |
| `scripts/cpe_runtime/result_validation.py` | Validate bounded task checkpoint fields |
| `scripts/cpe_runtime/verification.py` | Remove run-critical installed-source descriptor coupling |
| `templates/execution-note.schema.json` | Define the six small run decisions |
| `templates/plan-result-schema.json` | Add `completed_tasks` and `current_task` |
| `evals/fake_codex.py` | Simulate session creation and resume |
| `evals/check_cli.py` | Cover note input and one legacy migration |
| `evals/check_runner.py` | Cover same-session resume and no duplicate Task 1 |
| `README.md` / `SKILL.md` | Document the thin ownership boundary |

No task compiler, scheduler, review engine, verification runner, event
database, runtime capsule, third-party dependency, or Superpowers fork is
required.

## Required evals

### Workflow and authority

- A plan recommends SDD while the note selects `executing-plans`; the
  controller receives `executing-plans`.
- `sequential=true` is preserved on every fallback launch.
- Local commits never imply merge, push, PR, tag, publish, or deploy.
- A changed execution note is not treated as the same run.

### Session continuity

- A checkpoint resumes the same session ID.
- The resumed session retains the worktree and sandbox facts.
- No new top-level controller is created on a normal checkpoint.
- A missing session uses one explicit fresh-session fallback.

### Progress

- A Task 1 checkpoint appears as completed in inspect and fallback recovery.
- Task 1 is not re-executed after resume.
- A summary sentence alone cannot invent a completed task.
- No new run requires `execution-ledger.jsonl`.

### Verification boundary

- CPE source changes do not invalidate a compatible active run.
- Superpowers verification results remain referenced in the final result.
- Unsafe evidence paths, wrong final HEAD, dirty handoff, or invalid ancestry
  still fail.
- CPE does not choose or re-run a hidden test suite.

### Legacy recovery

- Exact descriptor and exact historical source digests allow
  `migrate-run`.
- A partial source match, changed HEAD, dirty worktree, live process, or
  descriptor mismatch refuses without mutation.
- Historical helper receipts are not silently reused.
- The same run ID and product worktree continue.

### Regression

- provider usage/auth/unavailable blockers keep their existing bounded
  behavior;
- plan order, clean worktree, ancestry, and final handoff checks remain;
- the final clean candidate passes `./evals/run.sh`.

## Explicit non-solutions

Do not solve this incident by:

- building a second task orchestrator inside CPE;
- adding a CPE-owned review lifecycle;
- adding another strict model-authored execution ledger;
- adding another CPE-owned verification workflow;
- pinning or copying the whole CPE runtime per run;
- passing the complete parent conversation to the child;
- weakening Git, clean-worktree, ancestry, or remote-action boundaries;
- trusting a free-form summary as completion;
- replacing descriptors or state by hand;
- increasing retries, timeouts, launch counts, or token budgets;
- starting another equivalent ReadMates run.

## Definition of Done

The repair is complete when:

1. CPE is documented and implemented as a thin Superpowers wrapper;
2. one run normally keeps one Codex controller session;
3. the selected Superpowers workflow and basic authority survive every resume;
4. new runs need no CPE execution ledger;
5. checkpoint progress does not lose completed tasks;
6. compatible CPE upgrades do not invalidate active runs;
7. the legacy ReadMates run can be repaired without a second run;
8. focused evals and the full clean CPE eval suite pass;
9. independent review has no open findings;
10. the same ReadMates run resumes without repeating Task 1;
11. no merge or remote action is inferred from CPE recovery.

## Final assessment

The useful part of CPE is small: durable worktree isolation, one resumable
controller, immutable input paths, and a mechanical branch handoff.

Superpowers already owns the hard workflow problems. CPE should preserve that
workflow across process interruption, not translate it into another
orchestration system. Removing the fresh-controller default, the duplicate
ledger, and the whole-runtime descriptor binding is the shortest path to a
reliable and understandable CPE.
