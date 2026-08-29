# Incident Report: Codex Plan Runner Conflicts with the Codex Sandbox and Volatile Desktop Git Refs

## Document status

| Field | Value |
| --- | --- |
| Status | Two confirmed runner/host compatibility defects; fixes not yet implemented |
| Suggested severity | High |
| Affected component | `skills/kws-codex-plan-runner` |
| Affected release | `1.0.0` |
| Runner repository HEAD inspected | `0f657980ccef445b3693180a3cf1a5d8cd67b574` |
| Incident date | 2026-07-24 |
| Evidence reviewed | 2026-07-24 |
| Incident A | `workspace-write` provider cannot connect to the parent verification helper's Unix socket |
| Incident B | Desktop-owned `refs/codex/turn-diffs/*` changes are treated as protected repository ref mutations |
| Product repository | `/Users/kws/source/web/canvas-clone` |
| Product data-loss status | No confirmed data loss |
| Remote exposure | No merge, push, or deploy observed |
| Integration status | `not_observed` |

## Issue titles suitable for a tracker

> Make the parent verification helper reachable from the default
> `workspace-write` Codex sandbox without silently escalating to
> `danger-full-access`

> Exclude explicitly classified Codex Desktop bookkeeping refs from the runner's
> product-ref integrity contract while continuing to fail closed on real
> repository ref mutation

## Executive summary

Two independent host-compatibility defects caused otherwise recoverable
implementation runs to be abandoned and recreated.

### Incident A: the default sandbox blocks the verification transport

The runner starts a parent-owned verification server using an `AF_UNIX` socket.
It then launches the Codex provider with `--sandbox workspace-write`, which is
also the runner CLI default. The provider can read the helper descriptor and
execute the checked-in helper client, but the client cannot connect to the
socket. Both focused verification requests observed in the affected run failed
with:

```json
{
  "status": "failed",
  "reason_code": "helper_request_failed",
  "detail": "[Errno 1] Operation not permitted"
}
```

The same helper protocol worked when a later run was explicitly launched with
`--sandbox danger-full-access`. This establishes a sandbox/transport
compatibility failure, not a product-test failure.

Using `danger-full-access` is an operational workaround, not the desired
product fix. The default advertised mode must either provide a compatible
parent-owned transport or fail during a preflight capability check before the
provider edits the worktree.

### Incident B: volatile desktop refs are included in the protected set

At run creation, the runner executes `git for-each-ref` and records every ref
except the assigned implementation branch in
`immutable_config.protected_refs`. In Codex Desktop, that set includes
host-owned bookkeeping refs such as:

```text
refs/codex/turn-diffs/captures/*
refs/codex/turn-diffs/checkpoints/*
```

Those refs can be created, updated, or removed by the enclosing Desktop task,
including as a consequence of ordinary observation or checkpoint activity.
They are not product branches, tags, remote-tracking refs, or release
authority. Nevertheless, the runner compares the entire current ref map with
the immutable snapshot on resume and finalization. Any unrelated Desktop
bookkeeping update therefore produces:

```json
{
  "status": "failed",
  "reason_code": "state_integrity_failed",
  "detail": "protected ref mutation detected"
}
```

The fail-closed comparison is appropriate for product refs. The defect is the
classification policy: volatile host refs are currently indistinguishable from
repository refs whose mutation would threaten the candidate or integration
boundary.

These incidents are independent:

- changing the sandbox does not fix protected-ref classification;
- ignoring volatile refs does not make the Unix socket reachable;
- neither issue is caused by the Calm Craft specification, plan, or product
  tests.

## Affected runs

### Incident A

| Field | Observed value |
| --- | --- |
| Run ID | `2026-07-24-calm-craft-responsive-reference-integ-097667ba-7bdc-4bd5-a0c5-bb0f70d321c4` |
| Provider session | `019f93d1-ef49-7c32-992a-5f43c859dc32` |
| State revision | `5` |
| Final status | `blocked` |
| Failure reason | `permission_required` |
| Durable detail | `The sandbox denies Unix-socket access to the parent-owned verification helper. Mandatory focused/final verification receipts cannot be produced.` |
| Configured sandbox | `workspace-write` |
| Source commit | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |
| Task progress | Task 0 implementation commit existed, but mandatory helper receipts could not be produced |

The provider session recorded two direct helper failures with exit code `65`,
`reason_code=helper_request_failed`, and `[Errno 1] Operation not permitted`.

### Incident B

| Field | Observed value |
| --- | --- |
| Run ID | `2026-07-24-calm-craft-responsive-reference-integ-fc6482a5-29a7-472b-a9ec-4074305e7914` |
| Provider session | `019f93d5-cfe6-7662-8ae0-6dbb384aedc2` |
| State revision | `9` |
| Final status | `failed` |
| Failure reason | `state_integrity_failed` |
| Durable detail | `protected ref mutation detected` |
| Configured sandbox | `danger-full-access` |
| Protected refs sealed at run creation | `53` |
| Source commit | `4d0153c3ec347dbdaff32642426c466c5b7a607d` |

The immutable protected-ref snapshot contains multiple
`refs/codex/turn-diffs/*` entries. The durable failure records only the generic
detail and does not record a before/after ref delta. The exact changed ref
cannot therefore be reconstructed from `state.json` alone. That missing
diagnostic is a separate observability gap and should be corrected with the
classification fix.

A later controlled run,
`2026-07-24-calm-craft-responsive-reference-integ-5df1b73c-16f6-4e25-b1c7-3ffe294b356d`,
confirmed the exposure: its immutable snapshot included 55 refs, including
Desktop turn-diff refs, while the enclosing Desktop task continued to own and
update that namespace. That run remains `resumable`; it is supporting exposure
evidence, not the direct terminal-failure record.

## Forensic locations

These paths are local evidence locations, not portable runtime interfaces.

```text
$HOME/.codex/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-097667ba-7bdc-4bd5-a0c5-bb0f70d321c4/state.json

$HOME/.codex/sessions/2026/07/24/rollout-2026-07-24T20-10-37-019f93d1-ef49-7c32-992a-5f43c859dc32.jsonl

$HOME/.codex/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-fc6482a5-29a7-472b-a9ec-4074305e7914/state.json

$HOME/.codex/sessions/2026/07/24/rollout-2026-07-24T20-14-51-019f93d5-cfe6-7662-8ae0-6dbb384aedc2.jsonl

$HOME/.codex/plan-runner/2026-07-24-calm-craft-responsive-reference-integ-5df1b73c-16f6-4e25-b1c7-3ffe294b356d/state.json
```

Do not commit provider transcripts. They can contain large prompts, local
paths, environment metadata, and unrelated task context. This report records
only the bounded facts needed to reproduce and fix the defects.

## Incident A: technical analysis

### Current execution path

1. `PlanRunner` creates a `HelperServer`.
2. `HelperServer` binds an `AF_UNIX` stream socket.
3. Long worktree paths cause the socket to be placed under the system temporary
   directory as `kpr-<digest>.sock`.
4. `CodexAdapter` exports the socket path, nonce, protocol version, and helper
   client argv to the provider environment.
5. `CodexAdapter.build_argv()` launches:

   ```text
   codex exec
     --ignore-user-config
     --json
     --sandbox workspace-write
     --add-dir <git-common-dir>
   ```

6. The provider invokes `scripts/runner.py _helper`.
7. `helper_client()` creates an `AF_UNIX` socket and calls
   `connect(socket_path)`.
8. The host sandbox rejects the connect operation with `EPERM`.

### Relevant implementation

| File | Symbol | Current responsibility |
| --- | --- | --- |
| `scripts/plan_runner/helper.py` | `HelperServer` | Creates and owns the Unix socket |
| `scripts/plan_runner/helper.py` | `helper_client` | Connects to the parent socket and exchanges one bounded request |
| `scripts/plan_runner/provider.py` | `CodexAdapter.build_argv` | Selects the provider sandbox and adds the Git common directory |
| `scripts/plan_runner/provider.py` | `CodexAdapter._add_helper_env` | Exports the helper descriptor |
| `scripts/runner.py` | `_helper` | Checked-in provider-side helper entry point |
| `evals/test_helper.py` | helper protocol tests | Exercises the Unix transport without the real Codex sandbox |
| `evals/test_provider.py` | adapter tests | Verifies argv and environment shape without proving socket reachability |

### Why deterministic tests did not catch it

The helper tests create a client and server in the same unrestricted test
process. Provider adapter tests validate that `--sandbox` and the helper
environment are present, but they do not run a real `codex exec` under
`workspace-write` and attempt the helper connection. The protocol is valid in
an unrestricted process while remaining unusable across the actual sandbox
boundary.

### Immediate operational mitigation

If a trusted plan requires the existing helper before the product fix:

1. verify that the task explicitly authorizes the broader sandbox;
2. start a new run with `--sandbox danger-full-access`;
3. do not mutate the immutable sandbox choice when resuming an existing run;
4. retain `integration=not_observed` and all normal runner safety checks.

Do not silently retry a `workspace-write` run with
`danger-full-access`. Sandbox escalation changes the authority boundary and
must remain an explicit launch decision.

### Recommended product fix

Introduce a transport abstraction and add a filesystem-mailbox transport that
works in `workspace-write`.

The mailbox should live in a run-private directory under the Git common
directory, because that directory is already explicitly granted through
`--add-dir` and does not dirty the assigned worktree. A suggested layout is:

```text
<git-common-dir>/codex-plan-runner-helper/<run-id>/
  descriptor.json
  requests/
  responses/
```

Required properties:

- parent creates the directory with mode `0700`;
- request and response files are regular files, never symlinks;
- every request has a random request ID and the existing 256 KiB byte limit;
- provider writes to a unique temporary file, fsyncs, and atomically renames;
- parent opens with no-follow semantics, validates owner, mode, size, nonce,
  run ID, protocol version, operation, and request ID;
- parent writes one atomic response and never executes shell text;
- provider polls with a bounded deadline and deletes only its own completed
  request/response pair;
- parent removes the runtime directory only after the provider process group
  is stopped;
- stale files cause a bounded diagnostic, not unbounded replay;
- verification execution remains parent-owned through `EvidenceStore`;
- receipts remain bound to candidate HEAD and exact argv;
- the transport directory is excluded from product Git observations by
  location, not by adding a repository `.gitignore` rule.

The current Unix socket can remain available for environments that prove it is
reachable, but `workspace-write` should select the compatible transport
deterministically. Transport selection must be sealed in immutable run state.

### Required preflight

Before allowing a provider to edit the worktree, run a minimal real-provider
capability canary using the selected sandbox and transport:

1. start the parent helper;
2. launch a bounded `codex exec` request under the exact immutable sandbox;
3. perform a non-mutating helper `ping` operation;
4. require the response to contain the run ID, protocol version, and nonce
   binding;
5. cleanly stop the canary;
6. only then launch the implementation prompt.

If the canary fails, return a specific external status such as
`helper_transport_unavailable`. Do not let the provider edit files and later
misclassify missing receipts as a product blocker.

### Required tests for Incident A

Add deterministic tests for:

1. mailbox request/response success;
2. stale request ID rejection;
3. wrong nonce and wrong run ID rejection;
4. oversized request and response rejection;
5. symlink, FIFO, directory, device, and path-escape rejection;
6. owner/mode mismatch rejection;
7. atomic-write interruption;
8. timeout and parent shutdown;
9. concurrent request IDs without response crossover;
10. exact candidate-HEAD and argv receipt binding;
11. cleanup after normal completion and provider termination;
12. immutable transport selection on resume.

Add an explicit live Codex canary that:

1. uses `--sandbox workspace-write`;
2. launches through the self-locating runner;
3. performs the helper `ping`;
4. requests one harmless focused verification;
5. confirms a receipt is produced;
6. proves no `danger-full-access` fallback occurred.

The live canary must remain separate from deterministic offline evaluation.

## Incident B: technical analysis

### Current execution path

At creation, `engine._protected_refs()` runs:

```text
git for-each-ref --format=%(refname)%09%(objectname)
```

It records every returned ref except:

```text
refs/heads/<assigned-runner-branch>
```

`GitWorkspace.open()` independently builds the same all-ref snapshot.
`PlanRunner._require_git_contract()` and
`GitWorkspace.require_clean_ancestor()` later require exact dictionary
equality.

This policy protects real repository state, but it also captures namespaces
owned by the host:

```text
refs/codex/turn-diffs/captures/*
refs/codex/turn-diffs/checkpoints/*
```

The enclosing Desktop task can change those refs without touching the runner
branch or product history. Exact all-ref equality therefore conflates
repository integrity with host telemetry lifecycle.

### Relevant implementation

| File | Symbol | Current responsibility |
| --- | --- | --- |
| `scripts/plan_runner/engine.py` | `_protected_refs` | Creates the immutable all-ref snapshot |
| `scripts/plan_runner/engine.py` | `_require_git_contract` | Compares current refs with immutable state |
| `scripts/plan_runner/git_ops.py` | `GitWorkspace.protected_refs` | Rebuilds the current all-ref map |
| `scripts/plan_runner/git_ops.py` | `GitWorkspace.require_clean_ancestor` | Rejects any map difference |
| `evals/test_git_ops.py` | protected-ref mutation test | Proves real ref mutation is rejected, but has no volatile-host-ref case |

### Security boundary that must remain

The fix must continue to reject mutation of:

- every local branch except the assigned runner branch;
- remote-tracking refs;
- tags;
- `refs/stash`;
- backup and rewrite refs such as `refs/original/*`;
- any unknown ref namespace not explicitly classified as volatile;
- creation, update, or deletion of the above refs.

Do not replace the current policy with broad patterns such as ignoring all
`refs/codex/*`. A future user-owned branch or durable security ref under that
prefix must remain protected unless its exact namespace has a documented
owner and lifecycle.

### Recommended product fix

Introduce a versioned ref-classification policy.

For new runs:

```text
protected:
  every ref except the assigned branch and an exact volatile-prefix allowlist

volatile-observed:
  refs/codex/turn-diffs/captures/*
  refs/codex/turn-diffs/checkpoints/*
```

Recommended immutable state additions:

```json
{
  "protected_ref_policy_version": 2,
  "protected_refs": {},
  "volatile_ref_prefixes": [
    "refs/codex/turn-diffs/captures/",
    "refs/codex/turn-diffs/checkpoints/"
  ],
  "volatile_refs_at_start_digest": "<sha256>"
}
```

The volatile digest is diagnostic only. It must not gate resume, recovery, or
finalization. Current volatile refs should be recorded in bounded audit
evidence when they differ, without failing the run.

Use one shared classifier in `engine.py` and `git_ops.py`; do not maintain two
independent filtering implementations. Prefer moving the canonical classifier
to `git_ops.py` and importing it into the engine.

Unknown namespaces remain protected by default. The allowlist must contain
literal normalized prefixes checked after validating the ref name. It must not
accept user-supplied regexes.

### Existing-run compatibility

Do not reinterpret an existing run's immutable protected-ref map under the new
policy. That would weaken a sealed contract after creation.

Required behavior:

- version-1 runs continue using the version-1 all-ref policy;
- version-2 is selected only when a new run is created;
- `inspect` remains able to read both versions;
- resume reports a precise legacy-policy conflict when a version-1 run is
  already affected;
- no automatic rewrite of `state.json` or its digest chain;
- no deletion or rewriting of the volatile refs to make an old run pass.

If a separately designed repair command is later added, it must require
explicit operator authority and emit immutable before/after audit evidence.

### Improve failure diagnostics

Current state stores only:

```text
protected ref mutation detected
```

Before failing, compute a bounded delta with three categories:

```text
created: ref -> new object ID
updated: ref -> old and new object IDs
deleted: ref -> old object ID
```

Store the full bounded delta as an immutable artifact and put only its digest
and counts in the failure object. Redact nothing from ref names or object IDs,
but enforce:

- valid Git ref names;
- a maximum number of entries;
- a maximum encoded artifact size;
- deterministic ordering.

This makes an integrity failure actionable without dumping the entire ref map
into a single state line.

### Immediate operational mitigation

Until the classifier is fixed:

1. do not run the plan runner in a repository whose shared Git common
   directory is concurrently observed by Codex Desktop;
2. avoid Git inspection from the enclosing Desktop task while the controller
   is live;
3. launch the provider without Desktop multi-agent/checkpoint behavior when
   that isolation is available;
4. monitor only the controller's existing terminal session;
5. do not delete or rewrite `refs/codex/turn-diffs/*` during an affected run;
6. treat exit `65` as an integrity stop and inspect durable state before
   deciding whether a new run is required.

These steps reduce exposure but are not a reliable product fix. Host
bookkeeping may still change independently.

### Required tests for Incident B

Add deterministic tests proving:

1. assigned runner branch updates are allowed;
2. another local branch creation, update, and deletion each fail;
3. remote-tracking ref creation, update, and deletion each fail;
4. tag creation, update, and deletion each fail;
5. stash and `refs/original/*` mutation fail;
6. an unknown `refs/codex/other/*` mutation fails;
7. creation, update, and deletion under
   `refs/codex/turn-diffs/captures/*` do not fail;
8. creation, update, and deletion under
   `refs/codex/turn-diffs/checkpoints/*` do not fail;
9. a similar but non-matching prefix remains protected;
10. policy version and allowlist are immutable;
11. version-1 state retains legacy comparison semantics;
12. version-2 state resumes and finalizes while volatile refs change;
13. a real protected-ref failure stores a bounded deterministic delta artifact.

Add a live Desktop-host canary that starts a disposable repository run, mutates
only a disposable `refs/codex/turn-diffs/checkpoints/*` ref from a separate
process, and proves the run remains valid. The canary must then mutate a
disposable protected branch and prove exit `65`.

## Combined acceptance criteria

The incidents are fixed only when all of the following are true:

- a default `workspace-write` run can obtain parent-owned focused and final
  verification receipts;
- no implicit sandbox escalation occurs;
- helper requests remain bounded, authenticated, no-follow, and shell-free;
- candidate HEAD and exact argv remain bound to receipts;
- Desktop turn-diff ref churn does not block resume or finalization;
- real product ref mutation still fails closed with exit `65`;
- failures identify the changed protected refs through a bounded artifact;
- old immutable runs are not silently reinterpreted;
- deterministic evaluation passes;
- the explicit live Codex sandbox canary passes;
- the explicit live Desktop ref-churn canary passes;
- a new end-to-end runner run can reach `ready_for_integration` without a
  transport workaround or host-ref wrapper.

## Non-fixes

The following approaches are insufficient:

- making `danger-full-access` the silent default;
- treating helper failure as a successful verification;
- allowing the provider to execute verification directly without parent-owned
  receipts;
- disabling protected-ref checking;
- ignoring all `refs/codex/*`;
- rewriting or deleting Desktop refs during a run;
- mutating an existing run's immutable protected-ref snapshot;
- retrying exit `65` without new evidence;
- starting a new run for every ordinary provider or test failure.

## Relationship to other incident reports

This report is intentionally narrow:

- `2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md` covers
  failure to seal a dirty provider result and the resulting unrecoverable
  checkpoint.
- `2026-07-24-codex-plan-runner-git-identity-isolation-incident.md` covers
  incorrect Git author/committer identity in the isolated provider home.

The defects can compose, but each requires its own fix and regression coverage.

## Remediation closeout (2026-07-25)

**Status:** resolved within the explicitly authorized full-access and narrow-ref
policy.

The original observations and proposed alternatives above remain forensic
evidence. The selected implementation is defined by the
[approved remediation design](../../superpowers/specs/2026-07-24-codex-plan-runner-incident-remediation-design.md),
the [core-correctness plan](../../superpowers/plans/2026-07-24-codex-plan-runner-core-correctness.md),
and the [permission/recovery plan](../../superpowers/plans/2026-07-24-codex-plan-runner-permission-recovery.md).
The implementation range is inclusive from `3c93a09e` through `c3a30f61`.

Focused regressions prove that full-access execution uses
`approval_policy="never"` and `--ignore-rules`, workspace-write helper denial
fails before product edits, host permission failures remain distinct, only the
two confirmed `refs/codex/turn-diffs/` namespaces are volatile, unknown or
product refs remain protected, policy versions are sealed, and the narrow
volatile repair rejects every broader delta. Coverage lives in
`evals/test_provider.py`, `evals/test_git_ops.py`, `evals/test_engine.py`, and
`evals/test_contracts.py`.

The real candidate canary ran with `danger-full-access`, approval policy
`never`, and the effective installed `CODEX_HOME`. It completed implementation,
helper verification, and structured finalization with zero approval requests,
kept the candidate clean, and reached `ready_for_integration` at
`1773ba770e2b69d975675762cd3b466592a30dd6`.

A bounded read-only audit of provider tool calls and Archive reflogs found no
Archive mutation or integration performed by the canary provider. The assigned
Archive branch advanced only through controller-approved Task 5 commits:
`ca65e964` before the initial provider launch, `c3a30f61` between the failed
finalization and the successful same-run continuation, and `861886ae` after the
canary to record this evidence. No canary-issued product-ref update, merge,
push, or deploy was observed. The earlier before/after ref hashes used different
serializations and span the intentional branch advance, so they are not claimed
as byte-identical all-ref snapshots.

The canonical final deterministic gate is:

```bash
bun run agent:verify -- --base "$MERGE_BASE" --head "$CANDIDATE_HEAD"
```

The deliberate residual boundary is that `workspace-write` is not promised to
carry the parent-owned helper transport on every host. The runner never
silently escalates it: autonomous mutation uses explicitly authorized
`danger-full-access`, while workspace-write capability failure stops before
product edits. Volatile treatment remains limited to literal capture and
checkpoint prefixes; no other `refs/codex/*` namespace is ignored.

## Whole-review hardening addendum (2026-07-25)

Follow-up commits `9b8c14ad` and `95d4d23e` tighten this boundary without
adding approval loops. Structured `sandbox_denied`, or `EPERM`/`EACCES` paired
with a recognized sandbox capability, normalizes to
`sandbox_capability_blocked`; free-text permission matching is not used.
Provider-runtime capability gaps are separately reported as
`provider_capability_blocked`.

An explicitly authorized retry may remain on the same logical run while
changing the effective profile:

```bash
./scripts/runner resume --run-id RUN_ID \
  --retry-blocked --sandbox danger-full-access \
  --strategy-note "workspace-write capability is blocked; use authorized full access"
```

The immutable initial profile is retained. The runner seals an
`execution_profile_transition`, starts a fresh provider session, and rejects
unchanged, unauthorized, or tampered transitions before launch.

The public Superpowers v6.2.0 helper surface was also smoke-tested against the
existing disposable canary root only; no new provider workflow was launched.
The exact commands and results were:

```text
/bin/bash /Users/kws/.codex/skills/subagent-driven-development/scripts/sdd-workspace \
  /private/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/plan-runner-real-canary-MdxUqM/inputs/plan.md
=> /private/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/plan-runner-real-canary-MdxUqM/home/.codex/worktrees/plan-runner/plan-8cb5dab2-10ba-49b3-885d-7133ed3c4f01/.superpowers/sdd/plan

/bin/bash /Users/kws/.codex/skills/subagent-driven-development/scripts/task-brief \
  /private/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/plan-runner-real-canary-MdxUqM/inputs/plan.md 1
=> wrote .../.superpowers/sdd/plan/task-1-brief.md: 10 lines

/bin/bash /Users/kws/.codex/skills/subagent-driven-development/scripts/review-package \
  /private/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/plan-runner-real-canary-MdxUqM/inputs/plan.md \
  11aef38 1773ba7
=> wrote .../.superpowers/sdd/plan/review-11aef38..1773ba7.diff: 1 commit(s), 835 bytes
```

The review package represented exactly `11aef38..1773ba7`, one commit
(`1773ba7 test: prove candidate runner canary`), and only `canary.txt` plus
`test_canary.py`. After inspection, the exact plan-scoped helper directory was
removed only after a non-symlink check; `.superpowers/sdd` retained its existing
`.gitignore`.
