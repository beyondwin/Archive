# Codex Plan Runner Incident Remediation Design

## 1. Summary

This design fixes the confirmed `kws-codex-plan-runner` 1.0.0 incidents without
turning the runner into a general workflow platform.

The remediation has two ordered implementation plans:

1. core commit and provider-result correctness;
2. permission-free operation and bounded recovery.

The plans run through `kws-codex-plan-runner` in one isolated worktree and
branch. Every implementation task uses `subagent-driven-development`: one fresh
implementer, one independent task review, required fix and re-review loops, and
one final whole-branch review.

The remediation run explicitly uses `danger-full-access`. It also makes the
non-interactive Codex child ignore repository execpolicy prompts and sets the
approval policy to `never`. This is necessary because the current
`.codex/rules/archive.rules` intentionally prompts for every Git command, even
when the sandbox is `danger-full-access`.

The runner still does not merge, push, deploy, rewrite history, or silently
trust an unexplained dirty worktree.

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
runner's immutable handoff and verification receipts. A tracked incident report
cannot safely embed evidence produced after its own commit without changing the
candidate HEAD and invalidating that evidence.

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

The plans execute sequentially in one runner worktree. Future-plan paths are
not exposed to the provider packet before their turn.

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

## 9. Authentication Contract

The runner checks authentication before the provider can edit the worktree.

Approved environment-token authentication continues to use the existing
allowlist. Installed file-backed Codex authentication is supported by copying
only the minimum required regular auth file into the private run-specific
Codex home with mode `0600`.

The runner does not copy the operator's full `.codex` directory. Auth contents
are not printed or written to state. A missing or unusable auth source becomes
`provider_auth_blocked` before provider work.

## 10. Non-Interactive Full-Access Contract

The remediation plans explicitly invoke the runner with:

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

### 10.1 Current-controller bootstrap

The currently installed controller does not yet add `--ignore-rules` or
`approval_policy="never"` to its child argv. It also does not natively inject
the configured Git identity or provision file-backed authentication. The
remediation plans therefore require a bounded bootstrap environment before the
first runner invocation.

The bootstrap:

- resolves the real Codex executable before changing `PATH`;
- creates a private run-local `codex` shim that adds `--ignore-rules`,
  `--strict-config`, and `-c approval_policy="never"` to `codex exec`;
- passes all non-`exec` invocations through unchanged;
- captures the source repository's effective Git identity and exports the four
  author and committer variables for the old sanitizer;
- provisions a run-private `CODEX_HOME` containing only the minimum auth file;
- preserves the same shim, identity, and auth environment for every external
  `resume` invocation;
- validates the shim, authentication, Git commit ability, and non-interactive
  behavior in a disposable repository before creating the real run.

The bootstrap is a private runtime artifact, not a tracked product change. It
exists only because the old controller cannot hot-reload the fixes it is
implementing. The candidate live canary must run the updated launcher without
the shim and prove that the native implementation supplies the same contract.

If the bootstrap preflight fails, the remediation run is not created.

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

Unexpected errors use a small decision table:

| Observed state | Best action |
| --- | --- |
| Exact clean or committed checkpoint | Retry with one changed strategy |
| Exact safe dirty checkpoint | Fresh session reviews the complete diff |
| External auth, tool, or permission blocker | Block with the precise next action |
| Known repairable historical state | Require the matching explicit repair kind |
| Unknown identity, ref, path, digest, or state drift | Preserve evidence and fail closed |

The controller may continue bounded recovery while it is alive. It does not ask
the user “should I continue,” repeat an unchanged strategy, or turn an
unclassified error into a trusted state.

## 16. Subagent-Driven Implementation Contract

Both implementation plans explicitly require
`subagent-driven-development`.

For each plan task, the root provider:

1. extracts one task brief;
2. dispatches one fresh implementer;
3. requires TDD RED then GREEN;
4. requires focused tests, a task commit, and self-review;
5. writes the implementer report to a file;
6. creates a full task diff package from the recorded base commit;
7. dispatches a separate task reviewer;
8. fixes and re-reviews every Critical or Important finding;
9. records completion in the SDD progress ledger;
10. moves to the next task only after both spec and quality approval.

Implementation agents are not run in parallel.

Mechanical one- or two-file tasks use `gpt-5.6-terra`. Integration, recovery,
security-sensitive work, task reviews of non-trivial diffs, and the final
whole-branch review use `gpt-5.6-sol`.

The root provider coordinates and answers subagent context questions. It does
not implement task code itself. Long briefs, reports, and diffs are handed off
as files so collaboration events do not overwhelm the provider JSONL stream.

The SDD ledger is a recovery aid. Runner state, Git commits, task evidence, and
receipts remain the authority for final completion.

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
   the current-controller bootstrap shim;
5. update contract documentation and the four incident reports;
6. start the runner's fresh finalization session;
7. declare and execute this canonical command through the parent helper:

   ```text
   bun run agent:verify -- --base <merge-base> --head <candidate-head>
   ```

`agent:verify` selects the Codex Plan Runner deterministic eval for this change.
It also supplies the repository diff check selected for this scope. Therefore
the plan does not invoke `git diff --check` or `./evals/run.sh` separately. The full
runner eval runs exactly once at the HEAD that becomes the final candidate. If
the independent finalization review changes that HEAD, the old receipts are
invalidated and the final gate runs again on the replacement candidate; it is
still executed once for the final candidate HEAD.

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
does not use the old-controller PATH shim.

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
  result will be held in the runner handoff;
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
- isolated HOME can hide file-backed authentication and Git identity;
- repository-local signing can cause an interactive pinentry;
- collaboration output can exceed one JSONL line limit;
- a permission error after an edit needs a checkpoint before recovery;
- Desktop volatile refs can change during ordinary observation;
- opening the Git common directory increases the importance of protected-ref
  validation;
- macOS TCC and Keychain prompts cannot be accepted by an autonomous CLI;
- SDD brief, report, ledger, and review-package paths must remain writable;
- a nested live canary must use a disposable repository;
- older run state cannot be made trustworthy merely by installing new code;
- the old controller needs the same durable bootstrap environment for every
  external resume until the remediation run completes.

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
- every implementation task has SDD implementer and independent review
  evidence;
- all Critical and Important review findings are fixed and re-reviewed;
- focused regressions pass;
- one final `bun run agent:verify` passes at the final candidate HEAD;
- the disposable real-Codex canary passes;
- `SKILL.md`, `README.md`, and `CHANGELOG.md` match the implemented contract;
- all four incident reports record their candidate resolution, live-canary
  result, implementation range, and final verification command;
- the runner handoff records the exact final candidate HEAD and canonical
  deterministic evidence;
- no unrelated `docs/operations/` guide is changed without a concrete contract
  impact;
- the result is `ready_for_integration` with no merge, push, or deploy.
