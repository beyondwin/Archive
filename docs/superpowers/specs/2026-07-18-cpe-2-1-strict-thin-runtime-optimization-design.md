# CPE 2.1 Strict Thin Runtime Optimization Design

Date: 2026-07-18
Status: approved design
Target: `skills/kws-codex-plan-executor`
Release: CPE 2.1.0, run-state format 3

## 1. Summary

CPE 2.1 is a strict, thin sequential execution and audit harness for approved
Superpowers plans. It preserves ordered immutable inputs, one isolated
worktree, bounded controller slices, exact verification receipts, mechanical
completion checks, and truthful operator reporting. Superpowers remains the
sole semantic owner of implementation, task boundaries, TDD, review, fixes,
test selection, subagent coordination, and commits.

This release removes the model-based plan compiler rather than narrowing it.
CPE no longer maps plan tasks, extracts plan-declared verification commands,
maps plan-specific capabilities, validates plan source spans, or emits compiler
advisories. It accepts verification commands selected by Superpowers and
mechanically executes or reuses them under an exact same-run evidence key.

The release also replaces one-hour controller slices with a twenty-minute
default, recognizes uncommitted worktree changes as durable progress, stops
blind retries after unchanged environment blockers, and classifies controller
transport failures separately from invalid product results. The default
controller sandbox is `danger-full-access`, as an explicit product decision to
avoid recurring local browser, loopback, and managed-filesystem failures.

## 2. Evidence And Problem Statement

### 2.1 The compiler crosses the intended ownership boundary

The current 2.0 runtime uses a separate read-only Codex invocation to derive a
compiled run index containing tasks, source spans, verification declarations,
capabilities, and advisories. Runtime consumers use that artifact primarily to
allowlist verification commands and conditionally probe loopback binding. Task
entries do not dispatch Superpowers work.

This creates a mismatch between the public statement that CPE does not own
task mapping and the actual implementation. It also adds a provider call, a
repair call, state fields, schemas, artifacts, validation code, and tests
before the real Superpowers controller starts.

### 2.2 Full-suite selection is not a CPE responsibility

CPE does not independently invoke a product full suite and does not require a
specific full-suite command for acceptance. Historical full-suite executions
were selected by approved plans and Superpowers controllers. Several repeated
full gates were legitimate because earlier gates found real failures or the
HEAD changed afterward.

CPE nevertheless causes avoidable same-HEAD executions in two cases:

1. verification phase is part of the cache key, so identical task and
   branch-final requests can execute twice;
2. a command not exactly matched by the compiler allowlist falls back to a
   never-reusable execution.

Both causes disappear in 2.1. CPE still does not infer affected tests or
decide that a small change permits cross-HEAD reuse.

### 2.3 Environment blockers were repeatedly relaunched

One sanitized historical Canvas run recorded 58 attempts, 28 blocked outcomes,
and 51 resumes. Many completed implementations repeatedly reported the same
managed-environment loopback-bind and filesystem `EPERM` conditions. Another
run repeatedly reached the same browser and visual-evidence blocker. This is
an executor retry-policy failure even though the underlying browser and
project setup belong to Superpowers.

The current runtime also classifies a nonzero Codex exit with no structured
result as `invalid_result`. In an observed run, two controller attempts exited
within seconds, produced empty result files, and left only repeated Codex state
database warnings in the bounded stderr log. The stored failure did not say
whether the provider, transport, authentication, usage quota, or result schema
was responsible.

### 2.4 The existing code and evidence surface is too large

The current CPE runtime and deterministic evals exceed fifteen thousand lines.
The size is not itself an acceptance criterion, but it reflects responsibilities
that do not belong in a thin harness: model compilation, plan semantic mapping,
source-span validation, plan-specific capability mapping, and their repair and
fixture matrices. Removed behavior must delete its code, schema, state, docs,
and tests instead of leaving compatibility shims.

## 3. Goals

1. Make the public thin-harness boundary true in runtime code.
2. Remove every model compiler call before controller execution.
3. Preserve one worktree and one ordered plan sequence across interruptions.
4. Reduce the default controller feedback boundary from 3,600 to 1,200 seconds.
5. Recognize clean commits, ledger facts, and uncommitted file changes as
   progress without storing source bodies or diffs.
6. Prevent identical environment blockers from launching another controller.
7. Reuse successful identical verification across task and final phases at the
   same HEAD.
8. Preserve fail-closed result, review, verification, HEAD, cleanliness, and
   ancestry checks.
9. Report usage, verification reuse, artifact pressure, blockers, and handoff
   facts without inventing missing values or external integration.
10. Keep Superpowers upstream files unchanged.

## 4. Non-Goals

CPE 2.1 does not:

- select focused, affected, or full-suite tests;
- infer whether a code or documentation change affects a command;
- reuse verification across different HEADs;
- install dependencies or bootstrap a project automatically;
- copy or symlink `.env`, `local.properties`, SDK state, virtual environments,
  or dependency directories from another checkout;
- define task, review, fix, or subagent workflow policy;
- create a review lifecycle, transition-obligation engine, context-reference
  policy, or cross-run signal promotion system;
- automatically escalate or reduce sandbox permissions;
- detect every filesystem mutation outside the worktree when running with
  `danger-full-access`;
- merge, push, deploy, publish, or claim external product acceptance;
- read, migrate, or resume format-1 or format-2 runs.

## 5. Ownership Boundary

The governing rule is:

> CPE maintains one execution environment and verifies submitted facts.
> Superpowers decides what work and verification are correct.

| Responsibility | Owner |
|---|---|
| Spec and plan meaning | Superpowers |
| Task boundaries and implementation | Superpowers |
| TDD, test scope, review, fixes, commits | Superpowers |
| Subagent prompts and coordination | Superpowers |
| Ordered immutable inputs | CPE |
| Isolated worktree identity and continuity | CPE |
| Controller sandbox, slice, process, and retry boundaries | CPE |
| Verification execution and same-condition reuse | CPE |
| Mechanical result and receipt validation | CPE |
| Fact-only reports and branch handoff | CPE |

The controller prompt may state infrastructure invariants: the supplied CPE
worktree is already isolated, all ordinary task agents must use that same
worktree, and a second worktree is allowed only when the approved plan
explicitly requires cross-revision comparison. This is an execution boundary,
not a task or subagent strategy.

## 6. Architecture

CPE 2.1 consists of seven logical components.

### 6.1 InputSnapshotStore

- validates clean source identity at run creation;
- copies ordered specs and plans to the private run root;
- records role, order, byte length, and SHA-256;
- never replaces a snapshot during resume.

### 6.2 WorktreeManager

- creates one branch and one isolated worktree from the recorded source commit;
- verifies repository, branch, path, Git common directory, and current HEAD;
- preserves the same worktree for every plan and controller slice;
- never copies project-local ignored setup from the source checkout;
- records worktree creation and reconciliation blockers before controller
  launch.

### 6.3 ControllerLauncher

- launches one ephemeral Codex controller for the current plan;
- uses `danger-full-access` by default;
- supports an explicit run-creation opt-down to `workspace-write`;
- uses a 1,200-second default slice and an immutable 1,200-to-3,600-second
  operator override;
- supplies the exact worktree, plan snapshot, spec snapshot list, current HEAD,
  ledger, prior result, failure code, and recovery capsule;
- keeps secret-like environment variables filtered;
- retains process-group termination, bounded two-pipe draining, locking, and
  result-file isolation.

### 6.4 ProgressObserver

- records HEAD, completed task IDs, current task ID, and a worktree-change
  digest;
- recognizes tracked and untracked regular-file changes before a commit;
- stores digests and bounded counts only, never file bodies or raw diffs;
- treats an over-limit dirty inventory as changed but unavailable rather than
  unchanged;
- drives productive-timeout and no-progress decisions.

### 6.5 EnvironmentGuard

- probes only CPE-owned prerequisites before execution: repository read,
  worktree write, and Git availability;
- performs a lazy `loopback_bind` probe only after Superpowers submits that
  specific environment blocker;
- stops unchanged known blockers before model, test, or verification launch;
- requires explicit `--retry-blocked` for unknown child blockers;
- does not parse the plan or grow a generic product-capability registry.

### 6.6 VerificationReceiptStore

- accepts the exact command selected by Superpowers;
- executes without a shell and preserves argv boundaries;
- records bounded stdout and stderr evidence, exit status, duration, and
  required artifact facts;
- revalidates successful receipts under the exact same-run content key;
- records execution phase and requested reuse phase as observations, not cache
  identity;
- never caches failed, timed-out, nondeterministic, always-execute, dirty-tree,
  or untrusted fallback results.

### 6.7 ResultGate

- validates the strict child result envelope;
- binds the result to the exact observed clean HEAD and plan ancestry;
- requires at least one successful verification observation;
- validates final review path and HEAD plus empty open-finding and
  open-obligation ID arrays;
- seals accepted evidence and creates fact-only optimization and branch-handoff
  reports;
- records `integration=not_observed` unless an external finisher supplies a
  separate trusted integration receipt.

## 7. Removed Scope

The final tree must remove all of the following:

- `scripts/cpe_runtime/compiler.py`;
- `templates/compiled-run-index.schema.json`;
- compiler request, launch, repair, result, log, and cache paths;
- compiled-index and operator-contract state fields used only by compilation;
- task and source-span mapping;
- plan-declared verification allowlisting;
- plan capability mapping and task-to-capability references;
- compiler unknown and execution-advisory fields;
- compiler-specific fixtures, tests, documentation, and tracked inventory.

There is no compatibility placeholder for these fields in format 3. Any small
operator contract still needed for source repository, remote policy, and merge
policy is derived deterministically from state and is not a model artifact.

## 8. Public CLI And Immutable Run Configuration

The stable commands remain `run`, `resume`, and `inspect`.

```text
cpe.py run --spec ... --plan ... --workspace ...
           [--sandbox danger-full-access|workspace-write]
           [--controller-slice-seconds 1200..3600]

cpe.py resume --run-id RUN_ID
cpe.py resume --run-id RUN_ID --retry-blocked
cpe.py resume --run-id RUN_ID --retry-failed
cpe.py inspect --run-id RUN_ID
```

Defaults:

| Setting | Value |
|---|---:|
| Sandbox | `danger-full-access` |
| Controller slice | 1,200 seconds |
| Maximum controller launches per plan | 6 |
| Maximum active wall time per plan | 7,200 seconds |

Sandbox and slice settings are recorded at run creation and cannot change on
resume. CPE never changes sandbox mode in response to a failure.

`danger-full-access` is an approved default with an explicit residual risk:
CPE cannot completely observe or reverse writes outside the worktree. Prompt
constraints, remote-operation prohibitions, secret filtering, result
validation, and Git integrity remain, but they are not a sandbox substitute.

## 9. Execution And Recovery Flow

1. Validate the source repository and clean source commit.
2. Persist format-3 state and immutable input snapshots.
3. Create or reconcile the exact worktree.
4. Probe CPE-owned prerequisites.
5. Launch the current plan controller directly; no compiler call occurs.
6. Persist attempt identity and result placeholder before spawn.
7. On return or timeout, observe actual HEAD, ledger facts, and worktree-change
   digest.
8. Persist one canonical outcome before deciding whether another launch is
   allowed.
9. On accepted completion, seal evidence and advance to the next plan in the
   same worktree.
10. After the final plan, materialize reports and factual handoff.

### 9.1 Outcome table

| Observation | Action |
|---|---|
| Child completed | Validate and finish or fail closed |
| Child checkpointed | Persist and return; no automatic launch |
| Child blocked | Persist blocker and return |
| Child failed | Persist failure; require `--retry-failed` |
| Timeout with changed progress | Continue within launch and wall budgets |
| Timeout without changed progress | Return stalled checkpoint immediately |
| Known unchanged environment blocker | Zero child launches |
| Known changed environment blocker | Permit bounded resume |
| Unknown child blocker | Require `--retry-blocked` |
| Any budget exhausted | Stop before another launch |

The 2.0 one-hour confirmation-slice behavior is removed. One twenty-minute
no-progress timeout is sufficient to stop. Operators with a known long-running
build or E2E command must choose a larger immutable slice at run creation.

## 10. Worktree Progress Digest

The worktree-change digest prevents loss of uncommitted work from being
misclassified as no progress.

The observer enumerates tracked modifications and untracked regular files
using non-following filesystem checks. It hashes content into one canonical
digest without persisting paths, bodies, patches, or command output in the
public event. Bounded private diagnostics may retain counts and total bytes.

If file count, individual file size, total bytes, symlink safety, or read
stability exceeds the supported boundary, the observer records:

- `changed=true`;
- `digest=null`;
- a stable reason code such as `dirty_inventory_unavailable`.

Unavailable digest is never treated as clean or reusable verification input.

## 11. Environment Continuity And Blockers

### 11.1 Project bootstrap

Superpowers reads repository instructions and performs project-specific setup
inside the CPE worktree. Because every slice and ordinary subagent reuses that
worktree, installed dependencies and generated local state persist naturally.
CPE does not run an inferred package-manager command and does not import ignored
state from another checkout.

### 11.2 Parent-owned blockers

Repository-read, worktree-write, Git, creation, and reconciliation failures are
parent-observed. Plain resume rechecks them. An unchanged observation launches
zero controller, verification, or setup process; a changed observation permits
normal bounded continuation.

### 11.3 Child environment blockers

A Superpowers blocked result may include a bounded capability identifier and
stable reason code. For `loopback_bind`, CPE performs a local parent probe after
the first blocked result and records a canonical fingerprint. Plain resume
rechecks that fingerprint before any controller launch.

Unknown identifiers remain child-attested facts. They do not create a new CPE
probe. Plain resume returns the same blocked state with zero launch, and only
`--retry-blocked` expresses operator intent to try again.

## 12. Verification Selection And Reuse

### 12.1 Ownership

Superpowers chooses whether to run a method test, affected suite, build,
browser scenario, full suite, or static check. CPE does not assign significance
to a command name or infer affected scope from changed files.

### 12.2 Cache scope and key

Reuse is scoped to one run. The reusable content key contains:

1. argv digest;
2. resolved working directory;
3. exact HEAD;
4. sanitized execution-environment fingerprint;
5. decision-complete input digest;
6. mutable-input policy.

Command ID and phase are observational labels and are not identity fields.
The execution-environment fingerprint includes sandbox mode and the safely
resolved executable identity so a changed command resolution cannot reuse an
older receipt.

### 12.3 Cross-phase reuse

If a task-phase command passed and branch-final requests the same content key,
CPE revalidates the receipt and artifacts without executing the underlying
command. The reuse observation records both the original execution phase and
the new requested phase. It does not rewrite the original receipt or pretend
that the command executed twice.

### 12.4 Mandatory execution

CPE executes when any of these are true:

- HEAD changed;
- worktree is dirty;
- argv, cwd, executable identity, environment, input digest, or mutable-input
  policy changed;
- the command is nondeterministic or always-execute;
- the prior result failed or timed out;
- a receipt, required artifact, or digest is unavailable, unsafe, or changed.

Cross-HEAD reuse remains out of scope. A small change can affect a broad test,
and deciding otherwise belongs to Superpowers.

## 13. Controller Transport Classification

The launcher parses only allowlisted, content-free facts from Codex JSONL. It
does not persist raw stdout events or provider messages.

Stable outcome codes are:

- `provider_usage_blocked`;
- `provider_auth_blocked`;
- `provider_unavailable`;
- `controller_spawn_failed`;
- `controller_transport_failed`;
- `controller_result_missing`;
- `controller_result_invalid`;
- `controller_timed_out`.

Usage, authentication, and provider availability produce a blocked state with
no automatic retry. A present but schema-invalid result is a failed integrity
outcome. An unrecognized nonzero exit with no result becomes
`controller_transport_failed`, not `invalid_result`.

Known repetitive Codex state-database warnings remain in bounded diagnostics
but are separately counted as noise and never replace the terminal reason.

## 14. Completion And Reporting

The existing mechanical gates remain:

- exact reported and observed HEAD;
- ancestry from plan start;
- clean tracked and untracked worktree;
- nonempty successful verification observations;
- safe final review and ledger paths;
- final review HEAD equal to accepted HEAD;
- empty open-finding and open-obligation arrays;
- sealed evidence under the private run root.

Optimization reporting adds or preserves:

- controller attempts and active duration;
- known and unknown provider usage fields without zero substitution;
- verification requests, executions, reuses, uncached executions, and avoided
  executions;
- requested and executed phase counts;
- blocker type, fingerprint availability, unchanged stops, and explicit
  retries;
- controller transport outcome counts;
- metadata-only produced-artifact inventory;
- truthful branch, observed HEAD, last-known HEAD, and
  `integration=not_observed`.

Reports are advisory and cannot expand acceptance policy.

## 15. Format And Legacy Boundary

CPE 2.1 writes only format 3. It does not read, migrate, repair, or resume
format-1 or format-2 state. A legacy run is rejected without mutation and
remains readable as filesystem audit evidence. Existing failed CPE state is
never rewritten to claim success from later inline work.

## 16. Verification Strategy

Implementation uses focused deterministic tests rather than repeated full
gates.

### 16.1 State and CLI

- default sandbox is `danger-full-access`;
- explicit `workspace-write` opt-down is persisted;
- sandbox and slice mutation on resume is rejected;
- slice override accepts 1,200 through 3,600 seconds only;
- format-1 and format-2 are rejected without file mutation;
- `--retry-blocked` and `--retry-failed` apply only to their exact states.

### 16.2 Controller and worktree

- run launches no compiler process;
- multiple slices use the exact same worktree;
- controller command contains the saved sandbox and timeout;
- prompt states infrastructure boundaries without task, review, fix, or
  subagent workflow policy;
- process-group, lock, bounded-log, and coordinator-loss guarantees remain.

### 16.3 Progress and recovery

- HEAD, ledger, tracked change, and untracked change each produce progress;
- content is not persisted in progress evidence;
- over-limit dirty inventory is changed and unavailable, not unchanged;
- first no-progress timeout stops with zero confirmation launch;
- productive timeouts continue only within six launches and two active hours;
- identical known blockers produce zero child launches;
- unknown blockers require explicit retry.

### 16.4 Verification

- identical task and branch-final requests execute once and reuse once;
- reuse preserves original and requested phases truthfully;
- command ID changes alone do not force execution;
- HEAD, dirty state, cwd, argv, executable, environment, input, artifact,
  policy, failure, and timeout invalidations each force execution;
- CPE never selects or directly schedules a full suite.

### 16.5 Transport and completion

- empty-result nonzero exits are classified as transport/provider failures;
- schema-invalid present results remain integrity failures;
- raw provider messages are absent from durable events;
- all existing clean-HEAD, ancestry, review, finding, obligation, artifact,
  and successful-verification gates remain covered.

### 16.6 Historical regression fixture

A sanitized content-free fixture represents the historical 58-attempt Canvas
run. The fixture proves that after the first loopback blocker, unchanged plain
resumes launch zero controller, model, or verification processes until the
environment changes or the operator explicitly retries.

## 17. Implementation And Review Policy

- Use method or class-level RED/GREEN tests while editing.
- Run one focused suite for each minimal implementation task.
- Perform at most one review per task.
- Do not create routine diff-package or re-review artifacts.
- Use static contract checks for docs and inventory-only changes.
- Do not rerun an identical command at the same HEAD.
- Perform one final integration review on the candidate clean HEAD.
- Close any finding with focused tests and no routine re-review.
- Run `./evals/run.sh` once on the resulting final clean HEAD.
- If that full gate fails, fix only the exact failures and run the next full
  gate once on the new clean HEAD; never rerun a failed unchanged HEAD for
  reassurance.

## 18. Release And Installation

The tracked skill directory remains the installation source of truth. Local
Codex and Claude Code installations continue to link to that directory, so new
sessions discover CPE 2.1.0 without copied mutable installations.

The release is local-only until separately authorized. It does not push,
publish, merge a remote branch, deploy, or claim a live provider canary. A
deterministic fixture is not a canary.

## 19. Acceptance Criteria

1. No compiler module, schema, call, artifact, state field, test, or inventory
   entry remains.
2. CPE does not map plan tasks, verifications, capabilities, or source spans.
3. Default controller sandbox is `danger-full-access`; opt-down is explicit and
   immutable.
4. Default slice is 1,200 seconds, one no-progress timeout stops, and every
   continuation respects six-launch and 7,200-second limits.
5. Uncommitted tracked and untracked changes count as progress without storing
   source bodies or diffs.
6. Repeated unchanged known blockers launch zero controller, model, setup, or
   verification process.
7. Unknown child blockers require `--retry-blocked`.
8. Same-run same-HEAD identical verification executes at most once across
   phases and command labels.
9. Changed HEAD and every unsafe or incomplete evidence condition force
   execution.
10. CPE never chooses focused or full-suite scope and never reruns product
    verification after accepting a handoff.
11. Controller transport and provider failures are distinguishable from
    invalid result schemas without storing raw provider text.
12. Existing final review, open finding, open obligation, verification,
    cleanliness, HEAD, ancestry, and artifact checks remain fail closed.
13. Reports remain fact-only and handoff remains
    `integration=not_observed`.
14. Format-1 and format-2 runs are rejected without mutation.
15. Focused tests, one final integration review, one final clean-HEAD full gate,
    docs, and tracked inventory prove the reduced contract.
16. Superpowers upstream files are unchanged.
17. No push, remote merge, deploy, or publish occurs as part of implementation.

## 20. Accepted Trade-Offs And Residual Risks

- CPE no longer proves that a verification command appeared in plan prose. It
  proves only what command Superpowers actually ran, where, at what HEAD, with
  what result, and whether reuse was exact.
- CPE no longer preflights plan-specific capabilities. It reacts to an actual
  Superpowers blocker and probes only the bounded loopback case.
- Task source-span and compiler advisory views disappear from `inspect`.
- Default `danger-full-access` can permit undetected writes outside the
  worktree. This is knowingly accepted to eliminate recurring local sandbox
  blockers; prompt and Git checks are not presented as equivalent protection.
- A changed HEAD always invalidates verification even for documentation-only
  changes. Superpowers must order final documentation and the final gate to
  avoid unnecessary work.
- A twenty-minute slice can interrupt a legitimately long command. The
  immutable 20-to-60-minute override is the supported escape hatch.
- Project bootstrap can still fail in a fresh worktree. CPE preserves the
  environment and stops repeated retries, but Superpowers remains responsible
  for choosing and running the correct setup.

These trade-offs intentionally exchange CPE semantic intelligence for a
smaller, faster, more truthful execution boundary.
