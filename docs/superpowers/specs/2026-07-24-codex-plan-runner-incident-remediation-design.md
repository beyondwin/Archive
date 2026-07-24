# Codex Plan Runner Incident Remediation Design

## 1. Summary

This design fixes the confirmed `kws-codex-plan-runner` 1.0.0 incidents without
turning the runner into a general workflow platform.

The remediation has two ordered implementation plans:

1. core commit and provider-result correctness;
2. permission-free operation and bounded recovery.

The remediation is implemented directly through `subagent-driven-development`
in one isolated worktree and branch. The current `kws-codex-plan-runner` does
not orchestrate its own fixes. The candidate launcher is exercised only as the
system under test in one disposable live canary after the deterministic fixes
are complete. Every implementation task uses one fresh implementer, one
independent task review, required fix and re-review loops, and one final
whole-branch review.

The candidate live canary explicitly uses `danger-full-access`. The updated
runner also makes its non-interactive Codex child ignore repository execpolicy
prompts and sets the approval policy to `never`. This is necessary because the
current `.codex/rules/archive.rules` intentionally prompts for every Git
command, even when the sandbox is `danger-full-access`.

The runner still does not merge, push, deploy, rewrite history, or silently
trust an unexplained dirty worktree.

### 1.1 Why direct SDD works while the runner can fail

Direct `subagent-driven-development` has one control plane. The root Codex
session already owns collaboration events, authentication, Git identity,
task reports, and the SDD ledger.

The runner adds a second control plane around that workflow: another
`codex exec`, an isolated home, a sanitized environment, a linked worktree, a
JSONL parser, a helper transport, durable state, and recovery decisions. The
confirmed incidents occur at those added boundaries, not inside SDD itself.

The fix therefore keeps the wrapper thin. Superpowers continues to own task
decomposition, TDD, subagent dispatch, task review, and the SDD ledger. The
runner owns only immutable inputs, one assigned worktree, root-session
launch/resume, checkpoint-before-result handling, and final Git/verification
evidence. It does not reconstruct subagent state or implement a second task
orchestration model.

The wrapper is also a strategic recovery shell around external boundaries.
Normal execution stays on the unmodified Superpowers path. Only after an
observed provider, host, permission, transport, Git, or verification failure
does the wrapper preserve evidence, choose a materially different safe
strategy, and resume the same goal. It does not turn every possible failure
into a new framework or ask for routine approval between recoverable steps.

## 2. Confirmed Inputs

The design treats these incident reports as immutable problem statements:

- `docs/operations/2026-07-24-codex-plan-runner-git-identity-isolation-incident.md`
- `docs/operations/2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md`
- `docs/operations/2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md`
- `docs/operations/2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md`

The affected implementation is limited to:

- `skills/kws-codex-plan-runner/`;
- its deterministic evals;
- its public skill, README, changelog, and CLI contract;
- the repository verification map only if the final verification command needs
  a narrowly scoped correction.

The Codex and Claude runners remain independent. Claude parity implications are
reviewed, but runtime code is not shared and the Claude runner is not modified
unless a concrete compatibility defect is found.

### 2.1 Incident coverage

The remediation covers the confirmed failure in every report, but it does not
adopt every proposed expansion from those reports.

| Incident report | Included remediation | Deliberate lightweight boundary |
| --- | --- | --- |
| Git identity isolation | Capture, seal, inject, and validate author and committer identity | No full Git-config copy or identity-audit subsystem |
| Progress replay and duplicate run | Equivalent-run refusal, exact recommended action, and narrow repair | No general successor graph, run-family UI, or receipt-reuse optimizer |
| Sandbox and volatile refs | Explicit full-access execution without approval prompts, workspace-write fail-fast preflight, and exact volatile-ref policy | No new transport that guarantees workspace-write compatibility |
| Unsealed dirty worktree | Post-provider checkpoint ordering, provider failure taxonomy, fresh-session full-diff review, and narrow historical repair | No generic dirty-state adoption |

Implementation completion updates all four incident reports with:

- the implemented resolution status;
- the implementation commit range available before finalization;
- the expected canonical verification command and observed live-canary result;
- any residual boundary that remains intentionally unsupported.

Other files under `docs/operations/` are updated only when their current
operational contract is changed by the implementation. The final documentation
review checks this explicitly rather than editing unrelated guides
preemptively.

The exact final candidate HEAD and canonical deterministic result live in the
direct SDD handoff and canonical verification output. A tracked incident report
cannot safely embed evidence produced after its own commit without changing
the candidate HEAD and invalidating that evidence.

## 3. Goals

1. Preserve the configured Git author and committer identity inside the
   isolated provider environment.
2. Seal the exact post-provider Git state before malformed output or another
   provider failure can terminate recovery.
3. Accept a final provider result only from a completed root turn.
4. Prevent Codex approval prompts during autonomous runner sessions.
5. Distinguish sandbox or host permission failures from product and test
   failures.
6. Ignore only the confirmed volatile Codex Desktop ref namespaces while
   continuing to protect product refs.
7. Stop equivalent new runs from replaying already started work.
8. Provide narrow repair paths for the two confirmed recoverable historical
   states.
9. Choose a safe next action for unexpected errors without building a large
   generic recovery framework.
10. Prove the result with focused TDD, one canonical full verification run, and
    one disposable real-Codex canary.

## 4. Non-Goals

This remediation does not:

- build a general run-family graph or workflow database;
- add a general-purpose “accept current state” or `--force` switch;
- add automatic merge, push, deploy, or history rewriting;
- copy the operator's full Git or Codex configuration;
- build a new cross-platform verification transport;
- add a broad privacy, compliance, or identity-audit subsystem;
- reuse stale receipts to optimize recovery;
- automatically repair unknown ref, path, state, or worktree drift;
- make `danger-full-access` the public CLI default;
- add a large matrix of speculative failure cases.

Existing credential scrubbing and remote-mutation defenses remain regression
requirements. They are not expanded into a separate feature.

## 5. Selected Approach

The selected approach is a small controller correction with two plans.

### 5.1 Plan 1: core correctness

Plan 1 covers:

- effective Git identity capture;
- safe identity injection into the child Git configuration;
- author and committer validation for candidate commits;
- post-provider checkpoint ordering;
- provider failure classification;
- root-turn and final-result selection;
- bounded handling of malformed and oversized provider output;
- installed Codex authentication preflight.

### 5.2 Plan 2: permission-free operation and bounded recovery

Plan 2 covers:

- non-interactive full-access Codex invocation;
- sandbox and host-permission classification;
- exact volatile-ref policy;
- equivalent-run admission control;
- narrow repair of known volatile-ref and unsealed-partial incidents;
- state-specific recommended actions;
- documentation, changelog, live canary, and final evidence.

### 5.3 Thin-wrapper boundary

The runner may:

- snapshot ordered specs and plans;
- allocate and validate one worktree and branch;
- launch or resume the root Codex session;
- seal the exact Git observation before interpreting the root result;
- select a bounded new root-level strategy after an external boundary failure;
- execute declared verification and record the final candidate HEAD.

The runner does not:

- dispatch, schedule, or mirror individual SDD subagents;
- duplicate the SDD ledger as a second task database;
- infer plan completion from collaboration events;
- retry unchanged permission or provider failures;
- replace Superpowers' implementer, TDD, review, or ledger policies with its
  own recovery state machine;
- build a general workflow, repair, or run-family subsystem.

The two plans execute sequentially in one direct-SDD worktree. Superpowers
v6.2.0 gives each plan its own
`.superpowers/sdd/<plan-basename>/` workspace, so Task 1 in one plan cannot be
mistaken for Task 1 in the other. Future-plan paths are not included in a task
brief before their turn.

### 5.4 Superpowers v6.2.0 compatibility

The execution baseline is
[Superpowers v6.2.0](https://github.com/obra/superpowers/releases/tag/v6.2.0).
The wrapper consumes its public workflow instead of copying its internals into
runner state:

- resolve the plan workspace with `scripts/sdd-workspace PLAN_FILE`;
- create task briefs with `scripts/task-brief PLAN_FILE N [OUTFILE]`;
- create full and fix-range packages with
  `scripts/review-package PLAN_FILE BASE HEAD [OUTFILE]`;
- resume the original implementer for fix rounds 1 through 3;
- use a fresh, more capable implementer for rounds 4 and 5;
- use the scoped `re-review-prompt.md` after every fix round;
- stop at the five-round circuit breaker and adjudicate remaining findings;
- delete only that plan's SDD workspace after its final review and canonical
  evidence are clean.

The current local installation can preserve script contents while losing their
executable mode. The direct-SDD controller therefore invokes these helpers
through `/bin/bash` and supplies explicit brief and review-package output
paths. This avoids an internal direct call to a non-executable sibling helper
without chmod, rewriting the global skill, or weakening host permissions.

Compatibility is capability-based, not a permanent equality check on the
`6.2.0` version string. The disposable canary exercises the public helper
signatures, plan-scoped workspace, one task, one review package, and workspace
cleanup. A later compatible release may proceed; an incompatible interface
blocks with the exact missing capability before Archive edits instead of
silently falling back to the old flat ledger.

The v6.2.0 testing guidance is `writing-good-tests.md`. Runtime regressions
must assert behavior and failure cause rather than source-string presence or a
change-detector proxy. Exact text assertions remain appropriate only for the
runner's deliberately versioned public contract vocabulary.

The runner does not parse the v6.2.0 ledger or depend on its directory layout
for product correctness. The plan-scoped workspace is execution scratch;
runner state observes only the root result, Git state, and declared evidence.
This keeps a later Superpowers update from becoming a runner state migration.

## 6. Component Boundaries

The design follows the current module boundaries.

### 6.1 `contracts.py` and `storage.py`

These modules own only the new bounded state fields:

- sealed Git identity;
- attempt failure class;
- post-provider worktree checkpoint;
- repair record;
- equivalent-input key;
- recommended next action.

Existing atomic state-write and revision behavior is reused. No new storage
engine or general migration framework is introduced.

### 6.2 `git_ops.py`

This module owns:

- reading the effective repository `user.name` and `user.email` before HOME
  isolation;
- validating non-empty, bounded, newline-free identity values;
- constructing the runner-owned Git config overlay;
- removing ambient author, committer, date, and Git-config overrides;
- forcing `user.useConfigOnly=true`;
- disabling automatic commit signing for runner-created commits;
- preserving disabled push URLs;
- inspecting author and committer fields for every candidate commit;
- classifying protected and volatile refs;
- capturing exact clean or dirty worktree observations.

It does not copy `.gitconfig`.

### 6.3 `provider.py` and `helper.py`

These modules own:

- the exact non-interactive Codex argv;
- auth and capability preflight;
- process-group lifecycle;
- root-session and root-turn tracking;
- bounded JSONL parsing;
- final output-file validation;
- helper failure classification.

They do not decide whether a Git state is safe to resume.

### 6.4 `engine.py` and `recovery.py`

These modules own:

- checkpoint ordering;
- failure-to-action decisions;
- bounded changed-strategy recovery;
- equivalent-run admission;
- narrow repair authorization;
- final candidate validation and completion.

They do not rewrite provider commits automatically.

## 7. Git Identity Contract

At new-run creation, before the child HOME is created, the runner resolves:

```text
git -C WORKSPACE config --get user.name
git -C WORKSPACE config --get user.email
```

Both values must be present and valid before the worktree or provider is
created. The resulting identity is sealed in immutable run state and reused by
initial, resumed, recovery, review-fix, and later-plan sessions.

The child Git overlay contains only:

```text
user.name=<sealed name>
user.email=<sealed email>
user.useConfigOnly=true
commit.gpgSign=false
remote.<name>.pushurl=disabled://plan-runner/<run-id>/<remote>
```

The sanitizer removes:

```text
EMAIL
GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL
GIT_AUTHOR_DATE
GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL
GIT_COMMITTER_DATE
GIT_CONFIG_GLOBAL
GIT_CONFIG_SYSTEM
GIT_CONFIG_NOSYSTEM
```

The exact candidate range `source_commit..candidate_head` is checked before a
plan becomes implemented and again before final handoff. Every author and
committer name and email must match the sealed identity.

A mismatch fails closed. The runner does not amend, reset, or recreate commits
automatically.

## 8. Provider Result and Checkpoint Contract

Every mutation-capable provider path uses this order:

1. launch the provider;
2. terminate or reap its complete process group;
3. validate branch, HEAD, ancestry, protected refs, and bounded paths;
4. capture and atomically persist the exact post-provider Git observation;
5. classify clean, committed, or safe dirty state;
6. validate JSONL lifecycle and final structured output;
7. accept, recover, block, or fail closed.

Step 4 must occur before semantic result validation can return.

A final result is accepted only when:

- the expected root session ID was observed;
- the root process exited successfully;
- a root `turn.completed` event was observed;
- the output file is a bounded regular file and not a symlink;
- the output matches the required schema;
- its candidate HEAD and task evidence pass engine validation.

Collaboration events remain activity evidence but cannot become the root final
result. A malformed or oversized event is bounded and classified as a provider
stream failure. It does not erase an already sealed post-provider checkpoint
and does not count as successful progress.

## 9. Codex Home, Authentication, and Superpowers Contract

The runner resolves the effective Codex home before replacing `HOME` and makes
that existing home available to the child through `CODEX_HOME`. This preserves
both installed authentication and the Superpowers skills that the runner is
wrapping. It does not copy, mirror, or maintain a second skill installation.

`--ignore-user-config` and `--ignore-rules` keep operator config and repository
rules from changing autonomous execution behavior. Existing credential
scrubbing and disabled Git push URLs remain in force. Auth contents, skill
contents, transcripts, and session history are not copied into runner state or
printed.

Approved environment-token authentication continues to use the existing
allowlist. A missing effective Codex home, unavailable authentication, or
missing required Superpowers workflow becomes `provider_auth_blocked` or
`provider_capability_blocked` before Archive implementation work. The
disposable canary proves the actual v6.2.0 SDD workflow is discoverable.

## 10. Non-Interactive Full-Access Contract

The disposable candidate canary explicitly invokes the runner with:

```text
--sandbox danger-full-access
```

Every initial, resumed, and fresh recovery Codex invocation includes:

```text
codex exec
  --ignore-user-config
  --ignore-rules
  --strict-config
  -c approval_policy="never"
  --sandbox danger-full-access
```

The exact ordering may follow the installed CLI parser, but the semantic options
must be identical.

The current inspected Codex CLI, `0.144.1`, supports `--ignore-rules`,
`--strict-config`, `-c`, and `danger-full-access`. The runner still probes the
installed CLI rather than trusting that observation indefinitely. Unsupported
flags block before the provider can edit the worktree.

`--ignore-rules` is required because
`.codex/rules/archive.rules` prompts for every Git command. Full sandbox access
does not disable those execpolicy prompts. `approval_policy="never"` prevents
the provider from waiting for an interactive approval that the autonomous
controller cannot supply.

The runner does not use:

```text
--dangerously-bypass-approvals-and-sandbox
--dangerously-bypass-hook-trust
```

Repository execpolicy is not a hard safety boundary for the provider session.
The runner therefore retains:

- an isolated assigned worktree and branch;
- scrubbed credential and prompt variables;
- disabled Git push URLs;
- protected-ref checks;
- exact candidate ancestry and identity validation;
- no merge, push, or deploy instructions;
- process-group cleanup and bounded recovery.

The public default sandbox remains `workspace-write`. If it cannot reach the
helper or write the linked worktree's required Git paths, a capability preflight
fails before provider edits with `sandbox_capability_blocked` and recommends an
explicit `danger-full-access` run. The remediation does not silently escalate
an explicitly requested `workspace-write` run.

### 10.1 Direct implementation control plane

The currently installed controller cannot hot-reload provider changes made
inside its own worktree. This remediation therefore does not wrap its
implementation in the old controller and does not create a PATH shim,
bootstrap Codex home, or parallel bootstrap state.

The current root session runs the two plans directly through
`subagent-driven-development`. Only after the native identity, authentication,
argv, checkpoint, and root-result fixes pass focused tests does one disposable
canary invoke the candidate launcher. This removes the circular dependency
where the broken controller must provide the capabilities required to fix
itself.

This execution choice does not remove the product requirements in Sections 7,
9, and 10. The updated runner must still supply the minimal identity,
authentication, and non-interactive environment when it later launches a root
Codex session.

## 11. Permission-Failure Decision

The runner distinguishes four permission sources:

| Source | Required action |
| --- | --- |
| Repository execpolicy prompt | Avoid with `--ignore-rules` and approval `never` |
| Codex sandbox denial | Classify as sandbox capability failure, not a product test failure |
| Git, SSH, signing, or credential prompt | Disable interactive prompting and fail with a precise blocker |
| Host or macOS TCC, Keychain, or GUI permission | Do not attempt automatic approval; stop once with `host_permission_blocked` |

The runner uses already accessible repository, worktree, state, auth, and
temporary paths. It does not run broad `chmod`, alter system permissions, open
GUI authentication, or retry the same denied capability repeatedly.

If a permission failure occurs after provider edits, the runner first seals the
exact safe dirty state. It then uses a fresh session and one changed strategy.
The same permission mode is not retried indefinitely and does not consume
ordinary product-repair attempts.

## 12. Protected and Volatile Refs

The protected set continues to include product-relevant refs, including
branches, tags, remote-tracking refs, stash, replace, notes, original refs, and
unknown namespaces.

Only these confirmed Codex Desktop namespaces are volatile:

```text
refs/codex/turn-diffs/captures/*
refs/codex/turn-diffs/checkpoints/*
```

The policy is versioned in new run state. Volatile changes may be recorded for
diagnosis but do not fail resume or finalization.

The runner does not ignore all `refs/codex/*`. An unknown ref change remains an
integrity failure.

Older runs are not silently reinterpreted under the new ref policy. They may use
the narrow repair path in Section 14 when the complete delta matches the known
volatile namespaces.

## 13. Equivalent-Run Admission

Before creating a UUID or worktree, the runner computes a bounded key from:

- source Git common-directory identity;
- source commit;
- ordered immutable input snapshots.

Provider, sandbox, model, and runner version are recorded as execution-profile
metadata, not as part of logical equivalence. Changing from a failed
`workspace-write` attempt to `danger-full-access` must not silently create a new
Task-0 branch for the same source and inputs.

It scans bounded run metadata under an intent-specific lock.

When an equivalent run exists, `run` does not create another branch. It returns
the matching run ID and the best available next command:

| Existing state | Recommended action |
| --- | --- |
| running or recovering | inspect the live run |
| resumable | `resume --run-id ...` |
| blocked | fix the reported blocker, then `resume --retry-blocked` |
| retryable failed | `resume --retry-failed --strategy-note ...` |
| known repairable integrity failure | the exact `repair` command |
| ready for integration | inspect the existing candidate |
| unknown or unproven integrity failure | preserve evidence and stop |

There is no generic force-new option. This prevents Task 0 replay while keeping
the implementation small.

## 14. Narrow Historical Repair

The public repair surface supports only:

```text
volatile-codex-turn-refs
unsealed-provider-partial
```

Every repair requires:

- exact run ID;
- exact expected state revision;
- no live controller, provider, helper, or descendant process;
- exclusive run lock;
- valid state and input digests;
- exact source repository, worktree, branch, and current HEAD;
- stable product refs;
- bounded regular paths with no symlink or path escape;
- exact matching repair-kind evidence;
- an explicit strategy note.

`volatile-codex-turn-refs` accepts only a delta wholly contained in the two
known volatile namespaces.

`unsealed-provider-partial` requires a captured incomplete attempt that matches
the current plan and mode. The current tree is sealed as
`adopted_untrusted_partial`; prior task and verification claims from that
attempt are discarded. A fresh session must inspect the entire diff and rerun
focused tests before continuing.

If these requirements cannot be proven, repair stops. The runner does not
invent a checkpoint or create another equivalent run.

## 15. Unexpected-Error Policy

Unexpected errors use a small two-step policy.

First, preserve the latest Git and provider checkpoint before interpreting the
failure. Second, classify both the observed state and the failed boundary, then
change exactly one relevant strategy dimension:

| Observed state and boundary | Best next strategy |
| --- | --- |
| Exact clean or committed checkpoint plus root transport loss | Resume the same root session once; if the same boundary repeats, start a fresh root with the checkpoint and failure evidence |
| Exact safe dirty checkpoint plus malformed result, provider crash, or lost session | Start a fresh root that reviews the complete diff and continues the same goal |
| Verification command unavailable or environment-specific | Use an already declared equivalent verification route when one exists; otherwise preserve evidence and report the exact missing capability |
| External auth, tool, TCC, Keychain, or host permission blocker | Preserve the checkpoint and block only when new external authority or a host-state change is actually required |
| Known repairable historical state | Require the matching explicit repair kind |
| Unknown identity, ref, path, digest, or state drift | Preserve evidence and fail closed |

The strategy history is bounded and records the failure evidence, changed
dimension, and return condition. The controller never repeats the same failed
strategy unchanged. It continues autonomously through safe resume, fresh-root
review, or an equivalent declared verification route, and returns to the
normal Superpowers path as soon as the external boundary is healthy.

This recovery shell observes only root lifecycle, Git checkpoints, and declared
evidence. It does not inspect the SDD ledger to invent new task status, replace
Superpowers' v6.2.0 fix-loop policy, or create a second implementer scheduler.
It stops only when external authority is needed or a load-bearing identity,
ref, path, digest, state, correctness, or acceptance invariant cannot be
established safely.

## 16. Subagent-Driven Implementation Contract

Both implementation plans are executed directly with
`subagent-driven-development`.

For each plan task, the root controller:

1. resolves the v6.2.0 plan-scoped SDD workspace and its plan-identified
   ledger;
2. extracts one task brief;
3. dispatches one fresh implementer;
4. requires TDD RED then GREEN;
5. requires focused tests, a task commit, and self-review;
6. writes the implementer report to a file;
7. creates a full task diff package from the recorded base commit;
8. dispatches a separate task reviewer;
9. uses the v6.2.0 bounded fix and scoped re-review loop;
10. records completion in the plan-scoped SDD ledger;
11. moves to the next task only after both spec and quality approval.

Implementation agents are not run in parallel.

Mechanical one- or two-file tasks use `gpt-5.6-terra`. Integration, recovery,
security-sensitive work, task reviews of non-trivial diffs, and the final
whole-branch review use `gpt-5.6-sol`.

The root controller coordinates and answers subagent context questions. It
does not implement task code itself. Long briefs, reports, and diffs are handed
off as files. The candidate runner treats collaboration events only as bounded
activity signals; they are not mirrored into runner task state and cannot
replace the root result.

The SDD ledger is a recovery aid. Git commits, file-backed task reports,
focused test output, review verdicts, and the final direct-SDD handoff remain
the authority for this implementation.

## 17. Verification Strategy

### 17.1 Focused TDD

During implementation, tasks run only the focused tests that cover their
changes, primarily:

- `evals/test_git_ops.py`;
- `evals/test_provider.py`;
- `evals/test_engine.py`;
- `evals/test_recovery.py`;
- `evals/test_storage.py`;
- `evals/test_skill_contract.py`.

Required composition regressions cover:

1. isolated HOME plus correct commit identity;
2. dirty worktree plus invalid structured result;
3. dirty worktree plus malformed or oversized provider stream;
4. root plus collaboration-subagent events plus one root final result;
5. full access plus repository rules that would otherwise prompt for Git;
6. workspace-write capability failure before provider edits;
7. volatile Codex ref churn without product-ref weakening;
8. equivalent run refusal with an exact recommended action;
9. narrow repair acceptance and all adjacent rejection cases.

### 17.2 Final evidence

The order at final candidate HEAD is:

1. all task reviews and fix loops complete;
2. one broad whole-branch review;
3. fix any review findings and rerun affected focused tests;
4. run the disposable real-Codex canary against the updated launcher without
   using the runner as the implementation controller;
5. update contract documentation and the four incident reports;
6. execute this canonical command directly from the SDD worktree:

   ```text
   bun run agent:verify -- --base <merge-base> --head <candidate-head>
   ```

`agent:verify` selects the Codex Plan Runner deterministic eval for this change
and supplies the repository diff check selected for this scope. Therefore the
plan does not invoke `git diff --check` or `./evals/run.sh` separately. The full
runner eval runs exactly once at the HEAD that becomes the final candidate. If
the independent final review or a canary repair changes that HEAD, the old
evidence is invalidated and the final gate runs once at the replacement
candidate.

### 17.3 Live Codex canary

One explicit canary runs in a disposable repository before the canonical final
gate. It uses:

- `danger-full-access`;
- `approval_policy="never"`;
- `--ignore-rules`;
- one root provider and one SDD subagent;
- one correctly attributed local commit;
- one focused helper verification;
- one completed root turn and final structured result.

The canary must not use the Archive source worktree as its product target. It
does not merge, push, or deploy. It invokes the candidate launcher directly and
does not use the old controller to implement or repair Archive. The canary uses
one minimal Superpowers task; it is not a second full implementation run or a
differential workflow harness. A failure returns to the single affected focused
TDD task and review loop rather than creating another equivalent run.

The reported historical run is inspected read-only. If it satisfies a narrow
repair contract, the final report prints the exact repair command. Actual repair
is not inferred from the implementation request.

### 17.4 Documentation synchronization

After behavior and live-canary evidence are final, but before the canonical
final gate, the implementation:

- updates `SKILL.md`, `README.md`, and `CHANGELOG.md`;
- changes each incident report status from an open defect to an implementation
  candidate or resolved state supported by evidence available at that point;
- links each incident report to the final design, implementation plans, and
  implementation commit range;
- records the live-canary outcome and the canonical final command whose exact
  result will be held in the direct SDD handoff;
- records deliberate residual boundaries without rewriting the original
  forensic evidence;
- reviews the remaining `docs/operations/` files and updates only those whose
  commands or behavioral claims became stale.

## 18. Residual Risks and Blind Spots

The implementation explicitly reviews these bounded blind spots:

- linked worktrees write Git objects and refs through a common directory;
- repository execpolicy prompts are independent of sandbox mode;
- `--ignore-user-config` does not imply `--ignore-rules`;
- resume and fresh sessions must receive identical non-interactive flags;
- Codex CLI flags may drift after `0.144.1`;
- replacing `HOME` can hide file-backed authentication and installed
  Superpowers unless the effective `CODEX_HOME` is preserved;
- a Superpowers upgrade can change plan-workspace and review-package
  interfaces even when runner code is unchanged;
- an over-eager wrapper can fight Superpowers by treating its normal task,
  fix, or cleanup lifecycle as a runner failure;
- a recovery loop can appear autonomous while merely repeating the same failed
  strategy; every retry therefore records the one changed dimension;
- repository-local signing can cause an interactive pinentry;
- collaboration output can exceed one JSONL line limit;
- stale flat `.superpowers/sdd/progress.md` files must not override v6.2.0
  plan-scoped ledgers;
- a permission error after an edit needs a checkpoint before recovery;
- Desktop volatile refs can change during ordinary observation;
- opening the Git common directory increases the importance of protected-ref
  validation;
- macOS TCC and Keychain prompts cannot be accepted by an autonomous CLI;
- SDD brief, report, ledger, and review-package paths must remain writable;
- installed helper executable bits may be missing even when script contents are
  valid, so orchestration must use the documented shell fallback and explicit
  output paths rather than changing the global skill;
- a nested live canary must use a disposable repository;
- older run state cannot be made trustworthy merely by installing new code.

The response to a newly discovered blind spot follows Section 15. The runner
does not pre-build a subsystem for every hypothetical failure.

## 19. Acceptance Criteria

The remediation is complete when:

- the configured Git identity is sealed, injected, and validated for every new
  candidate commit;
- a missing identity blocks before provider work;
- every mutation-capable provider attempt checkpoints Git state before semantic
  result validation;
- safe dirty provider failures remain recoverable by a fresh session;
- root final output cannot be replaced by commentary or collaboration events;
- autonomous Codex sessions use full access without repository Git approval
  prompts;
- unsupported CLI flags, auth, sandbox, or host permissions block before
  uncontrolled edits when possible;
- permission failures after edits preserve an exact checkpoint;
- only the two confirmed Codex turn-diff namespaces are volatile;
- product and unknown ref mutation still fails closed;
- an equivalent run is refused with an exact recommended action;
- the two narrow repair kinds accept only their proven states;
- the installed Superpowers workflow satisfies the v6.2.0 plan-scoped
  workspace, plan-aware review-package, scoped re-review, and five-round
  circuit-breaker contract;
- recoverable external-boundary failures preserve evidence, change strategy,
  and resume the same goal without adding routine user approval checkpoints;
- the runner returns to the normal Superpowers path after recovery and never
  treats the SDD ledger as product recovery state;
- every implementation task has SDD implementer and independent review
  evidence;
- all Critical and Important review findings are fixed and re-reviewed;
- focused regressions pass;
- one final `bun run agent:verify` passes at the final candidate HEAD;
- the disposable real-Codex canary passes;
- `SKILL.md`, `README.md`, and `CHANGELOG.md` match the implemented contract;
- all four incident reports record their candidate resolution, live-canary
  result, implementation range, and final verification command;
- the direct SDD handoff records the exact final candidate HEAD and canonical
  deterministic evidence;
- no unrelated `docs/operations/` guide is changed without a concrete contract
  impact;
- the result is `ready_for_integration` with no merge, push, or deploy.
