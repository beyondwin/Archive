# Quality-First Provider Plan Runners Design

**Date:** 2026-07-23

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**New skill surfaces:**

- `skills/kws-codex-plan-runner/`
- `skills/kws-claude-plan-runner/`

## 1. Summary

This design replaces the legacy Codex Plan Executor (CPE) and Claude Plan
Executor (CLPE) with two greenfield, provider-specific plan runners:

- `kws-codex-plan-runner` for Codex;
- `kws-claude-plan-runner` for Claude Code.

The runners share one semantic contract but no runtime implementation. Each
runner is independently installable, testable, recoverable, and adapted to its
provider's session and stream behavior. A repository-level parity evaluation
checks that the two implementations produce the same externally meaningful
states for the same scenarios. It is a test surface, not a third skill or a
shared production runtime.

Both runners execute approved Superpowers specifications and implementation
plans. Superpowers and the provider model own implementation meaning, task
selection, test selection, review technique, debugging, model routing, and
subagent strategy. The runner owns only the durable execution boundary:
immutable inputs, one isolated worktree, provider process/session lifecycle,
checkpointing, exact verification receipts, recovery, mechanical completion
gates, and truthful status reporting.

Quality and actual implementation completion take priority over token use and
elapsed wall time. There is no total token, cost, or wall-clock budget. The
runners prevent waste by reusing valid same-HEAD evidence, avoiding broad tests
after every small change, refusing unchanged retry strategies, and detecting
stalls from trusted activity rather than arbitrary total runtime.

The common successful terminal state is `ready_for_integration`. It means the
approved plans have been implemented and mechanically verified at the exact
recorded HEAD. It does not mean merged, pushed, deployed, released, or accepted
by an external system. The handoff always records
`integration=not_observed`.

## 2. Problem Statement

The two legacy executors evolved toward different strengths:

- CPE accumulated stronger filesystem durability, process cleanup, locking,
  exact-HEAD checks, receipts, and recovery evidence, but also accumulated a
  large runtime and workflow policies that overlap with current models and
  Superpowers.
- CLPE remained much smaller and used Claude session resume effectively, but
  had a thinner state, evidence, locking, and corruption-defense surface.

Retrofitting either implementation into a shared runtime would preserve too
much historical complexity and create a third ownership surface. Keeping the
two legacy completion definitions would also make identical Superpowers inputs
mean different things depending on the provider.

The current workflow has additional failure patterns that the new design must
remove:

1. A small code change can trigger a full suite immediately and repeatedly.
2. A vague performance target can cause the same optimization loop without a
   valid baseline or measurement contract.
3. A recoverable implementation defect can be escalated to the user instead of
   being debugged and fixed autonomously.
4. A failed strategy can be retried without a meaningful change.
5. A fixed one-hour process timeout can terminate a legitimate long build or
   test even while it is making progress.
6. A resumed conversation can preserve useful context, but it can also preserve
   a stuck strategy or damaged context.
7. Superpowers may produce more than one specification or implementation plan.
   Treating the input as exactly one document is incorrect.
8. Legacy runs may still be active while the replacement is developed.
   Renaming or removing their source or installed symlinks during execution can
   break them.

## 3. Goals

1. Provide exactly two new provider-specific plan-runner skills, with no shared
   production runtime and no third common skill.
2. Give Codex and Claude the same execution, recovery, evidence, and completion
   semantics.
3. Delegate implementation and quality workflow decisions to current
   Superpowers and provider capabilities.
4. Keep the runner small by limiting it to durable state and mechanical gates.
5. Execute any number of ordered plans sequentially in one branch and worktree.
6. Resume healthy provider sessions after simple interruptions while retaining
   a fresh-session recovery path.
7. Continue autonomously through implementation defects, test failures, build
   failures, dependency issues, and safely inferable plan gaps.
8. Ask for user intervention only when new authority or unavailable external
   state is genuinely required.
9. Avoid duplicate verification and review on an unchanged HEAD.
10. Allow legitimately long work without a total runtime cap, while detecting
    trusted-activity stalls.
11. Preserve exact Git identity, evidence integrity, process cleanup, bounded
    logs, path safety, and truthful handoff reporting.
12. Replace the legacy skills without affecting runs that are active during
    development.
13. Run both implementations on a preinstalled, uv-managed, normal-GIL
    CPython `>=3.13,<3.14` without depending on the system Python or downloading
    an interpreter during `run` or `resume`.

## 4. Non-Goals

The new runners do not:

- parse plans into a runner-owned task graph;
- choose task boundaries, implementation order within a plan, test scope,
  reviewer roles, subagents, agent count, or parallelism;
- copy or modify upstream Superpowers skills;
- select a cheaper model merely to reduce cost;
- define an arbitrary performance percentage or benchmark;
- impose a total token, cost, or wall-clock budget;
- run a full suite after every task or small fix;
- repeat a successful verification command at the same HEAD and environment;
- merge, rebase, push, deploy, publish, release, or delete the worktree;
- claim external integration or product acceptance;
- read, convert, inspect, or resume legacy CPE or CLPE state;
- automatically kill or migrate legacy runs during cutover;
- provide hostile same-user process isolation;
- replace Waygent scheduling, kernel isolation, or platform orchestration;
- rewrite the runners in Bun or TypeScript;
- install or upgrade Python during an active run or resume;
- change `kws-claude-multi-agent-executor`, which is outside this two-runner
  replacement scope.

## 5. Considered Architectures

### 5.1 Two independent runners with a common semantic contract — selected

Each skill owns its state format, provider adapter, stream parser, launcher,
tests, and documentation. A root-level parity evaluation supplies the same
fault scenarios to both runners and compares semantic outcomes.

This keeps provider behavior explicit, prevents a shared compatibility layer
from becoming a new orchestrator, and allows Codex and Claude session handling
to evolve independently.

### 5.2 One shared runtime with two adapters — rejected

A shared runtime would reduce some duplicated code, but it would become a third
production component with its own release and compatibility contract. Provider
differences would either leak into the shared core or be hidden behind a large
adapter interface. This conflicts with the requested two-skill structure and
the goal of removing historical machinery.

### 5.3 Refactor both legacy implementations in place — rejected

In-place refactoring would require preserving old state shapes, CLI behavior,
repair paths, and compatibility tests during the rewrite. The user explicitly
does not require legacy compatibility. Greenfield implementations can port
only proven durability primitives and avoid carrying old policy and reporting
surfaces forward.

## 6. Ownership Boundary

The governing rule is:

> Superpowers decides what correct implementation and verification mean. The
> runner preserves the execution environment and verifies submitted facts.

| Concern | Owner |
|---|---|
| Specification and plan meaning | Superpowers and provider model |
| Task discovery and ordering inside the current plan | Superpowers |
| Implementation, TDD, debugging, and fixes | Superpowers |
| Focused, affected, and final verification selection | Superpowers |
| Review method and subagent use | Superpowers and provider model |
| Provider-native model and agent strategy | Provider model |
| Ordered immutable input snapshots | Runner |
| Worktree, branch, base commit, and HEAD identity | Runner |
| Provider process and session lifecycle | Runner |
| Checkpoint, ledger, locks, and recovery attempts | Runner |
| Exact verification command execution and receipt reuse | Runner |
| Mechanical final acceptance | Runner |
| Merge, push, deploy, and external approval | User or external integration workflow |

The runner may supply a short `quality_first` execution profile. It may not
copy Superpowers implementation templates, invent roles, compile task graphs,
or prescribe subagent topology.

## 7. Common Quality-First Execution Contract

The execution packet tells the provider session to:

1. Read the immutable specification and current plan snapshots.
2. Execute the approved plan with Superpowers.
3. Prefer implementation correctness and review quality over token reduction.
4. Keep the configured top-level model unless the operator supplied an ordered
   fallback policy or the provider applies its own native fallback.
5. Choose subagents, roles, model use inside the session, and parallelism only
   when useful for the current
   work.
6. Run focused or affected verification while implementing.
7. Reuse valid evidence instead of rerunning the same command at the same HEAD.
8. Declare and run the final verification set at the clean candidate HEAD.
9. Perform one whole-branch review at that same HEAD.
10. Consolidate related findings into a coherent fix rather than dispatching a
    separate loop for every small issue.
11. Continue autonomously through ordinary defects and record consequential
    inferred decisions.
12. Never merge, push, deploy, or modify files outside the assigned worktree.

The runner does not rank models, infer price or strength, or switch models as a
recovery strategy. An optional `--model` pins the top-level provider model when
the operator needs reproducibility. Otherwise the provider default and current
Superpowers capabilities are used. Provider-native fallback is allowed when it
is already configured, and a future operator-supplied ordered fallback may be
passed through without runner judgment. Model change is never required for a
changed technical strategy. Usage and cost may be reported as informational
facts, but they are never acceptance gates.

## 8. Autonomous Decision Boundary

The provider session must resolve and continue without asking the user when it
encounters:

- implementation defects;
- failing focused, affected, or full tests;
- build and type-check failures;
- ordinary dependency or local environment setup issues that are safe to fix
  inside the worktree;
- small plan gaps that can be resolved from the specification, repository
  conventions, existing code, or tests;
- reviewer findings;
- a failed technical strategy for which a materially different safe strategy
  exists.

The session records material inferred decisions in the run ledger or plan
handoff. It changes strategy after the same failure signature rather than
repeating the same work.

Only the following may become `blocked`:

- unavailable credentials, secrets, authentication, or provider access;
- missing permissions or external approval;
- required external-system state that the session cannot create or observe;
- an action requiring destructive authorization outside the approved worktree;
- irreconcilable product requirements where repository evidence cannot select
  one safe interpretation;
- provider authentication, quota, or rate-limit conditions that cannot be
  recovered locally;
- missing or incompatible required runner runtime discovered before worktree or
  provider mutation.

The child session never waits on an interactive user question. It returns a
structured blocker when one of these authority boundaries is reached.

## 9. Inputs and Public CLI

Both skills expose the same common CLI shape:

```bash
./scripts/runner run \
  --spec /absolute/spec-a.md \
  [--spec /absolute/spec-b.md ...] \
  --plan /absolute/plan-a.md \
  [--plan /absolute/plan-b.md ...] \
  --workspace /absolute/repository \
  [--stall-seconds 3600] \
  [--model MODEL]

./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence or materially different strategy"
./scripts/runner inspect --run-id RUN_ID
```

Codex additionally accepts an immutable run-creation `--sandbox` option. Its
default is `workspace-write`. Claude records its fixed permission mode and deny
rules in the run state.

The public executable is a self-locating POSIX launcher. It resolves its own
physical skill directory rather than the caller's current working directory,
then performs this no-download lookup:

```bash
uv python find \
  --managed-python \
  --no-python-downloads \
  --no-project \
  --no-config \
  --resolve-links \
  3.13
```

The launcher executes the returned interpreter with the absolute
`scripts/runner.py` path and the original arguments. It does not use
`uv run`: the repository is intentionally not a uv project, and the launcher
does not need project discovery or its warning surface.

Both runners require:

- `uv` on `PATH`;
- an already installed, uv-managed CPython `>=3.13,<3.14`;
- the normal GIL build, not the free-threaded variant;
- standard-library-only Python production code.

The implementation and cutover workflow prepares the runtime explicitly with
`uv python install 3.13` before any live run. `run`, `resume`, and `inspect`
never download or install Python. The launcher emits a stable
`blocked: runtime_missing` result when `uv` or the managed interpreter cannot
be found. Once Python starts, preflight rejects an incompatible
implementation, minor version, or free-threaded build as
`blocked: runtime_incompatible`.

Before creating a worktree, launching a provider, or otherwise mutating run
state beyond the initial blocked record, preflight records the runner runtime's
exact patch version, resolved executable path, architecture, GIL mode, and
`uv` version. This runner-runtime identity is distinct from the environment
identity sealed for target-project verification commands; a target command
may intentionally use a different interpreter or toolchain.

At design finalization, the implementation host was prepared and verified with
`uv 0.11.28`, normal-GIL CPython `3.13.14`, architecture `arm64`, and canonical
interpreter path
`/Users/kws/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin/python3.13`.
The system `/usr/bin/python3` remains `3.9.6` and is not used or modified. These
patch, path, and architecture values are current-host evidence, not portable
hardcoded requirements beyond the common version and GIL contract.

Input rules:

- at least one `--spec` and one `--plan` are required;
- every path must be absolute, regular, readable, UTF-8, and outside unsafe
  symlink or traversal chains;
- specs and plans are snapshotted in the exact command-line order;
- order and digest are immutable for the life of a run;
- all specs are ordered, immutable source-of-truth references available to each
  current plan;
- plans execute sequentially in the supplied order;
- there is no implicit `spec[i]` to `plan[i]` pairing;
- the execution packet identifies exactly one current plan and tells the
  provider not to implement later plans early;
- Superpowers and the current plan decide which specs are relevant; the runner
  does not parse, merge, rewrite, or summarize input documents;
- changing a spec or plan digest requires a new run;
- `resume` never silently replaces an input snapshot;
- `--stall-seconds` and provider permission/sandbox settings are immutable;
- no token, cost, or total wall-time option is provided.

`run` and `resume` use these stable exit codes:

| Exit | Meaning |
|---:|---|
| `0` | `ready_for_integration` |
| `2` | `resumable` |
| `3` | `blocked` |
| `4` | `failed` |
| `64` | invalid invocation or immutable-input violation |
| `65` | state, artifact, or provider-result integrity failure |
| `70` | unexpected runner-internal failure |

`inspect` exits zero when it can safely read a valid run and prints its current
status without changing state. It uses `64` for an unknown run and `65` for
untrusted state.

## 10. Filesystem and Git Layout

Provider-private state:

```text
~/.codex/plan-runner/<run-id>/
~/.claude/plan-runner/<run-id>/
```

Provider-private worktrees and branches:

```text
~/.codex/worktrees/plan-runner/<run-id>
codex-plan/<run-id>

~/.claude/worktrees/plan-runner/<run-id>
claude-plan/<run-id>
```

`run-id` is a sanitized first-plan slug plus a UUID. The UUID, not a timestamp
or slug, provides uniqueness.

Each run uses one branch and one worktree for all plans. A completed plan
commits into that branch, and the next plan continues from the resulting HEAD.
The source checkout must be clean at run creation. The runner records the
repository identity, Git common directory, starting commit, branch, worktree,
and current HEAD and revalidates them before every provider launch and final
transition.

## 11. State Model

Each provider has an independent state format version `1`. Provider-private
fields may differ, but both formats contain these common facts:

- run ID, provider, runner version, and provider CLI version;
- runner-runtime identity: uv version, CPython implementation and patch
  version, resolved executable, architecture, and GIL mode;
- source repository, starting branch, and starting commit;
- worktree and Git common-directory identity;
- ordered spec and plan snapshots with SHA-256 digests;
- immutable run configuration;
- current plan index;
- per-plan state: `pending`, `running`, or `implemented`;
- optional opaque task-ledger entries submitted by Superpowers, using
  `pending`, `running`, or `reported_done`;
- observed HEAD and clean/dirty digest;
- checkpoint revision and checkpoint digest;
- ledger entries and implemented-plan handoffs;
- verification receipts and reuse relationships;
- whole-branch review receipt;
- provider process attempts and session lineage;
- finalization candidate HEAD, declaration digest, and review-session lineage;
- current failure signature;
- strategies already attempted for that signature;
- required next changed strategy;
- top-level status;
- `integration=not_observed`.

Top-level run states are:

- `running`: a controller process is active;
- `recovering`: a live controller is automatically replacing or resuming a
  failed child;
- `resumable`: durable work exists and the run may continue without new
  authority, but no controller is active and a new external invocation is
  required;
- `blocked`: external authority or unavailable external state is required;
- `failed`: valid state records exhausted recovery strategies or another
  unrecoverable execution failure;
- `ready_for_integration`: all plans are implemented and the final run-level
  gates passed.

`implemented` is a plan-local historical fact, not final acceptance. A later
plan may regress earlier work, so only the run-level final gates can produce
`ready_for_integration`. Likewise, `reported_done` is an opaque task-ledger
claim, not a runner-owned completion decision.

The runner does not create a task scheduler. Task-ledger entries are optional
opaque checkpoint facts supplied by Superpowers so recovery can avoid
redispatching reported work.

State writes are atomic and private. Each update increments a monotonic
revision, includes a digest of canonical state, and occurs under a run lock.
Readers reject unexpected file types, unsafe ownership or permission changes,
symlink-backed artifacts, traversal, digest mismatch, repository mismatch, and
concurrent mutation.

Receipts and other state-referenced evidence use an artifact-first commit
protocol:

1. write an immutable content-addressed artifact to a temporary regular file;
2. flush and `fsync` the file;
3. atomically rename it to its digest-derived final name and `fsync` the
   containing directory;
4. write, flush, and atomically replace the next monotonic state revision that
   references the artifact;
5. `fsync` the state directory.

On resume, a valid state revision is authoritative. Content-addressed artifacts
that exist but are not referenced by that revision are crash-window orphans and
are ignored. The runner does not repair state by guessing which orphan was
intended.

## 12. Execution Data Flow

For the current plan, the runner creates a compact execution packet containing:

- immutable spec and current-plan snapshot paths and digests;
- plan index and prior implemented-plan summaries;
- starting and current HEAD;
- current checkpoint, ledger, and receipt references;
- prior failure signature and strategies;
- required next strategy, when any;
- the common quality-first and authority-boundary contract;
- final structured-output schema;
- the internal verification-helper descriptor.

The provider reads source documents and repository files directly. The packet
does not duplicate their contents or compile them into a second plan.
Future plan snapshot paths and contents are omitted from the current execution
packet. Only the current index and total plan count are exposed, preventing
accidental early execution from becoming the default context.

The child runs verification through an internal runner helper. The helper
executes an exact argv array in the assigned worktree and records:

- argv without shell reinterpretation;
- cwd;
- executable identity;
- sanitized environment fingerprint;
- starting and ending HEAD;
- start and finish timestamps;
- exit code;
- bounded stdout and stderr digests;
- observational liveness samples while the command remains alive.

The provider's final structured JSON is a claim, not proof. The runner compares
it with Git, state, receipts, review evidence, and the current plan ledger
before accepting anything.

Provider streams are normalized into a small event vocabulary such as
`activity`, `session`, `tool`, `result`, and `error`. Raw transcripts are not
duplicated into state. Bounded diagnostic tails are retained only after secret
scrubbing.

## 13. Provider Adapters

### 13.1 Codex adapter

The initial session uses the installed `codex exec` contract:

```text
codex exec
  --ignore-user-config
  --json
  --output-schema <schema>
  --output-last-message <path>
  --cd <worktree>
  --sandbox <recorded-mode>
  --add-dir <git-common-dir>
  [--model <model>]
```

The initial run does not use `--ephemeral`. The adapter captures the explicit
session ID from the JSONL stream and persists it before relying on later output.

For a healthy same-plan interruption, a new OS process resumes the prior
conversation:

```text
codex exec
  --cd <worktree>
  --sandbox <recorded-mode>
  --add-dir <git-common-dir>
  resume <explicit-session-id> -
```

All compatible structured-output, JSON stream, model, and configuration flags
remain explicit on resume. The adapter never uses `--last`, because another
Codex task could otherwise be resumed accidentally.

### 13.2 Claude adapter

The initial session uses:

```text
claude -p
  --output-format stream-json
  --verbose
  --json-schema <inline-schema>
  --permission-mode bypassPermissions
  --session-id <uuid>
  [--model <model>]
```

The adapter retains project and user skill discovery and therefore does not use
`--bare` or `--safe-mode`. A narrow disallowed-tool contract prevents
interactive question waiting and integration actions. The process environment
removes nested-session markers and secret-like variables while preserving the
provider authentication variables required by the installed Claude setup.

A healthy same-plan interruption uses `--resume <explicit-session-id>`. A new
plan always uses a newly generated session ID.

### 13.3 Accidental remote-mutation defenses

Merge, push, deploy, and publish prohibitions are workflow invariants, not a
claim of hostile-process containment. The launcher adds defense in depth
against accidental remote mutation:

- set `GIT_TERMINAL_PROMPT=0`;
- remove `SSH_AUTH_SOCK`, `SSH_ASKPASS`, `GIT_ASKPASS`, common Git-host tokens,
  and unrelated cloud deployment credentials from the child environment;
- preserve only the provider authentication inputs required for the selected
  Codex or Claude process;
- override every discovered Git remote push URL to a non-routable value in the
  child process environment without changing repository config;
- apply provider-supported deny rules for remote mutation tools and commands;
- snapshot source and remote-tracking refs before launch and verify that the
  child did not alter protected local refs;
- revalidate the assigned branch, worktree, and source checkout after every
  attempt.

These controls reduce accidental side effects. A same-user child can remove
environment overrides or invoke another binary, so the design does not describe
them as a security boundary.

### 13.4 Provider trust boundary

Provider processes run under the same operating-system user as the runner. The
runners defend against stale state, accidental corruption, unsafe paths,
symlink replacement, malformed output, and incomplete evidence. They do not
claim to contain a malicious same-UID process, especially when Claude uses
`bypassPermissions` or Codex uses `danger-full-access`.

Hostile process containment belongs to Waygent/kernel or another external
sandbox. This explicit boundary prevents filesystem hardening from being
misrepresented as a security boundary it cannot provide.

## 14. Session and Recovery Policy

An OS process and a provider conversation session are different identities.
`codex exec resume` and `claude --resume` start new OS processes while
continuing earlier conversation state.

Both providers use this policy:

| Condition | Session decision |
|---|---|
| New plan begins | Fresh session |
| Controller exit or terminal disconnect | Resume healthy current-plan session |
| System restart | Resume healthy current-plan session |
| Transient provider or transport error | Resume healthy current-plan session first |
| Stored session missing | Fresh-session fallback |
| Explicit session resume fails | Fresh-session fallback |
| Stall lease expires | Invalidate session; fresh session with changed strategy |
| Same failure signature repeats | Invalidate session; fresh session with changed strategy |
| Strategy is visibly stuck | Invalidate session; fresh session with changed strategy |
| Context overflow or abnormal compaction | Invalidate session; fresh session |
| Session data is corrupt | Invalidate session; fresh session |
| Current plan becomes implemented | Never pass its conversation to the next plan |
| Input digest changes | Refuse resume and require a new run |

Session resume is a quality and efficiency optimization, not a correctness
dependency. Canonical recovery sources are:

1. Git HEAD and worktree digest;
2. checkpoint;
3. completed-work ledger;
4. exact verification receipts;
5. implemented-plan handoffs.

Each plan records a session lineage:

- active session ID;
- session creation and resume attempts;
- distinct OS process attempt IDs;
- last valid provider event;
- health: `healthy`, `suspect`, or `invalidated`;
- invalidation reason;
- fresh-fallback reason;
- changed strategy.

The fresh finalization session has the same lineage fields but is keyed to a
candidate HEAD rather than a plan. A simple interruption may resume it only
while the candidate HEAD and verification declaration are unchanged.
Contamination or candidate change invalidates that session and requires a fresh
finalization session.

If the controller process remains alive, child stall, transport failure,
session loss, and other recoverable child failures enter `recovering`. The
controller checkpoints before relaunching and automatically continues the
bounded changed-strategy loop without asking the user. `resumable` is exposed
only when the controller itself is gone or an external invocation is required.
It is not an intermediate child-retry state.

For one unchanged failure signature, the runner permits up to three distinct
changed recovery strategies after the initial attempt. It never repeats an
identical strategy as a new attempt. A reset requires material progress: a new
Git tree digest, an evidence-backed task transition, a newly successful
verification receipt, or resolution of a recorded finding. Repeated logs,
token output, timestamp-only checkpoints, or code churn that returns to the
same tree do not reset the count. Exhausting the strategy set yields
`failed: recovery_exhausted`.

`resume --retry-blocked` is an explicit assertion that an authority blocker was
resolved. A failed run requires
`resume --retry-failed --strategy-note <new-evidence-or-strategy>`. The note is
stored immutably, must be non-empty, and must not duplicate an earlier retry
note digest. It seeds a new recovery audit without erasing prior failure
signatures or strategies. This prevents a flag-only retry from resetting the
same loop. Neither retry mode overrides input-digest or state-integrity checks.

## 15. Activity Lease and Long Commands

`--stall-seconds` defaults to `3600`, but it is an inactivity lease, not a
process or run duration.

Trusted activity that refreshes the lease is limited to:

- a new provider tool call starting or finishing;
- a Git or worktree digest change;
- a checkpoint or ledger revision increase;
- a provider lifecycle event advancing to a new distinct phase.

These do not refresh the lease:

- repeated warnings;
- identical log lines;
- noisy status output;
- raw token or partial-message deltas without lifecycle progress;
- verification-helper heartbeat or process existence by itself;
- retransmitted provider events.

Provider stall detection and runner-owned verification-command deadlines are
separate:

- outside a verification-helper call, the provider activity lease applies;
- every verification-helper request must declare an explicit positive command
  deadline selected by the plan or Superpowers;
- while that command is active, its deadline governs and the provider lease is
  covered rather than refreshed by artificial heartbeats;
- helper liveness, output digests, process-tree changes, and available CPU/I/O
  samples are recorded for inspection but do not extend the command deadline;
- when the command finishes, its tool-completion event restarts the normal
  provider activity lease.

This is intentionally simpler than a CPU/I/O progress heuristic. A legitimate
silent build can receive a deadline longer than one hour, while `sleep` or a
hung process cannot live forever merely by existing. The runner imposes no
uniform command timeout and no total run timeout.

Outside an active helper command, absence of all trusted activity for the stall
window terminates the child process group. A live controller enters
`recovering` and applies the changed-strategy policy. A terminated controller
leaves a durable `resumable` checkpoint.

## 16. Verification and Evidence Reuse

During implementation, Superpowers runs focused or affected checks appropriate
to the current change. Reviewers reuse successful same-HEAD evidence and do not
automatically rerun it. A small fix does not trigger a broad suite.

Finalization is candidate-HEAD scoped:

1. After all plans are `implemented`, the runner freezes a clean candidate
   HEAD.
2. It launches a fresh provider session whose only job is final
   verification-set declaration and whole-branch review. It receives the
   specification snapshots, plan snapshots, full diff, ledger, and existing
   receipts, but not the implementation conversation.
3. Superpowers in that fresh session declares the complete ordered final
   verification command set with exact argv, cwd, environment requirements, and
   per-command deadlines.
4. The runner seals that declaration to the candidate HEAD and executes every
   required command through the verification helper.
5. Every declared required command must have a successful receipt at that exact
   HEAD.
6. The fresh session completes one structured whole-branch review using those
   receipts. It must not modify the worktree; the runner verifies unchanged
   HEAD and worktree digest afterward.

Each exact final command and whole-branch review may execute at most once for a
candidate HEAD. Successful same-condition receipts are reused. A code or
tracked-file change creates a new candidate HEAD and invalidates the previous
HEAD's final status, verification declaration, and review as final evidence.

A transport interruption without a definitive command or review result resumes
the same in-flight attempt and does not create a second logical execution. A
definitive nonzero command result rejects the candidate. If an external
environment blocker is later resolved, its changed environment fingerprint
allows a new command execution; no review is duplicated because review begins
only after all declared commands succeed.

When verification or review finds a defect, the candidate is rejected.
Superpowers consolidates related fixes, runs covering focused checks, and
creates a new candidate HEAD. Finalization then runs once for that new HEAD.
The final successful verification set and final successful review must name the
same full SHA.

The runner never invents a test command. For a documentation-only or otherwise
non-executable change, the fresh finalization session may declare
`no_applicable_verification` instead of a command set. The declaration must
include a structured rationale, and the whole-branch review must explicitly
accept it. An empty command list without that evidence fails closed.

An identical successful command is reusable only when argv, cwd, executable,
environment fingerprint, input digest, candidate HEAD, and declared command
role all match.

A performance result is binding only when the approved input defines:

- baseline;
- exact command;
- environment;
- number of repetitions or sampling method;
- tolerance or acceptance threshold.

Without all of these, performance observations are informational. The runner
must not create or repeatedly chase an arbitrary percentage improvement.

## 17. Whole-Branch Review

The whole-branch review occurs in the fresh finalization session described
above. It evaluates the complete diff from the starting commit to the candidate
HEAD for:

- specification coverage;
- cross-plan integration;
- regressions and omissions;
- unsafe behavior;
- unresolved review obligations;
- adequacy of the declared final verification set.

The review receipt records the exact full SHA and final verification-set
digest. A receipt from another HEAD or command-set declaration is not reusable.
`ready_for_integration` requires no unresolved Critical or Important finding
and no incomplete submitted obligation. Smaller observations may remain only
when they are explicitly non-blocking and recorded in the handoff.

The runner validates the receipt shape and HEAD identity. It does not claim to
semantically reproduce the review. This is an intentional consequence of
delegating quality judgment to Superpowers and the provider model.

## 18. Completion Semantics

A run becomes `ready_for_integration` only when all of the following are true:

1. every ordered plan is `implemented`;
2. implemented plans were not replayed;
3. the worktree is clean;
4. the observed HEAD is a full commit SHA;
5. the starting commit is an ancestor of the observed HEAD;
6. every final structured result names that exact HEAD;
7. every command in the sealed final verification set has a successful receipt
   at the final HEAD, or `no_applicable_verification` was validly approved;
8. the whole-branch review receipt names the same final HEAD and verification
   set;
9. there are no unresolved Critical or Important findings;
10. there are no incomplete submitted tasks or obligations;
11. every referenced artifact is a safe regular file under an approved root;
12. state, checkpoint, ledger, and receipt digests validate.

The final handoff contains:

- runner and provider identity;
- branch, worktree, starting commit, and final HEAD;
- ordered plan implementation summary;
- verification and review receipt references;
- recorded non-blocking observations;
- `status=ready_for_integration`;
- `integration=not_observed`.

It never claims merge, push, deployment, release, remote branch state, or
external acceptance.

## 19. Safety and Observability

Both runners preserve these proven durability primitives from the legacy
implementations without preserving their workflow engines:

- atomic private state writes;
- per-run locking;
- process-group termination with grace and escalation;
- bounded concurrent stdout and stderr draining;
- Git repository, common-directory, ancestry, branch, and HEAD validation;
- symlink, traversal, ownership, and regular-file checks;
- secret-like environment and log scrubbing;
- Codex JSONL/session event handling;
- Claude stream-json/session event handling.

The new implementations intentionally omit:

- legacy state repair and migration;
- compatibility envelopes;
- compiler and plan-mapping machinery;
- optimization percentage reports;
- token-efficiency targets;
- historical active-runtime reports;
- cost-based model routing;
- duplicated raw transcripts.

`inspect` is concise and factual. It shows input identities, current plan,
current HEAD, last checkpoint, session health, last trusted activity,
verification receipts, recovery strategies, blocker or failure reason, and
integration status. Usage totals are displayed only when supplied reliably by
the provider.

## 20. Multi-Plan Semantics

Plans execute in immutable input order in one worktree:

```text
all ordered spec snapshots -> source-of-truth context

plan 1 -> implemented commit(s)
       -> fresh session
plan 2 -> implemented commit(s)
       -> fresh session
...
fresh finalization session
       -> declared final verification set
       -> whole-branch review at the same HEAD
       -> ready_for_integration
```

Every attempt receives all spec snapshots as ordered reference context and one
explicit current plan as its only implementation target. There is no positional
pairing between the spec and plan lists. Superpowers determines relevance from
the documents themselves. The runner neither merges documents nor lets a
current session pre-implement later plans.

The next plan receives repository state, Git history, implemented-plan
handoffs, ledger facts, and receipts. It does not inherit the preceding plan's
conversation and does not replay an implemented plan.

Minor differences between specs are resolved autonomously from plan text, code,
tests, and repository conventions and recorded as decisions. Only genuinely
incompatible product requirements become `blocked`.

Focused and affected tests run during plans. Final verification and
whole-branch review run once per candidate HEAD after all plans unless an
approved plan explicitly defines an intermediate broad gate as a product
deliverable. Such an intermediate gate is plan evidence and does not replace
the final candidate-HEAD gate.

## 21. Testing Strategy

Each skill is a CPython `>=3.13,<3.14` standard-library implementation launched
through its own self-locating executable and a preinstalled uv-managed
interpreter. Its tests prove that no active command attempts a Python download
and that runtime identity is recorded separately from target verification
environment identity. Each skill has its own:

- unit tests;
- fake-provider adapter;
- state and transition tests;
- CLI contract tests;
- deterministic integration evaluations.

The repository also contains a root-level, versioned plan-runner contract
fixture and parity evaluation. The small test-only contract fixes public
outcomes, failure taxonomy, plan/task/run state vocabulary, and receipt
meaning. It is not imported by either installed runtime and therefore is not a
shared production library or third skill. The parity evaluation executes the
same scenario definitions against both public CLIs and compares semantic state,
not provider-private fields.

Required deterministic scenarios include:

- single-plan completion;
- ordered multi-spec and multi-plan execution;
- no implicit spec-to-plan pairing;
- current-plan scope preventing early execution of later plans;
- no replay of an implemented plan;
- exact same-HEAD verification reuse;
- no automatic full suite after a small change;
- one final review and final gate per candidate HEAD;
- invalidation of final evidence after a new candidate HEAD;
- declaration and sealing of every required final verification command;
- rejection when any declared final command lacks a successful receipt;
- structured `no_applicable_verification` and review approval;
- fresh finalization/review context and unchanged-worktree enforcement;
- dirty worktree and wrong-HEAD rejection;
- missing, malformed, stale, and symlink-backed receipt rejection;
- artifact-first receipt commit, state-reference commit, and orphan ignoring
  across injected crash windows;
- a silent verification command exceeding one hour under its explicit
  deadline;
- a sleeping or hung verification command ending at its explicit deadline;
- helper heartbeat alone not refreshing progress;
- repeated logs without trusted progress causing a stall;
- process interruption and checkpoint recovery;
- live-controller child failure entering automatic `recovering`, not
  `resumable`;
- controller absence exposing durable `resumable`;
- Codex and Claude healthy-session resume;
- explicit session IDs and prohibition of latest-session shortcuts;
- missing-session and failed-resume fresh fallback;
- session invalidation after stall, repeated failure, or context damage;
- a new session at every implemented plan boundary;
- input-digest mismatch requiring a new run;
- three distinct changed strategies and recovery exhaustion;
- verified progress resetting the strategy count;
- failed retry requiring a new non-duplicate strategy note;
- blocker classification for credentials, authority, and external state;
- credential and SSH-agent scrubbing plus noninteractive remote protection;
- concurrency locking and process-group cleanup;
- path traversal, unsafe ownership, and symlink replacement attacks;
- provider stream truncation and malformed final envelopes;
- missing `uv`, missing managed Python, incompatible CPython, and free-threaded
  runtime rejection before worktree or provider mutation;
- self-locating launcher behavior from unrelated current directories;
- runner-runtime and target-verification environment identity separation;
- final completion parity between the two providers.

Validation proceeds in this order:

1. focused unit tests during implementation;
2. provider-specific fake integration evaluations;
3. common parity evaluation;
4. installed Codex and Claude CLI version and flag checks;
5. real provider session creation and explicit-ID continuity probes in
   disposable Git repositories;
6. real provider multi-plan happy-path canaries;
7. provider-specific complete evaluations at the candidate HEAD;
8. `bun run agent:verify`;
9. one `code_review.md` whole-branch review.

Fault injection uses deterministic fake providers. Live provider canaries prove
that installed CLIs, session persistence, structured streams, Superpowers
discovery, worktree access, and multi-plan handoff work together. Model prose
is not used as a deterministic test oracle.

Both real provider canaries are required before cutover. Missing provider
authentication or quota is reported as a cutover blocker rather than silently
skipping live evidence.

## 22. Greenfield Implementation and Cutover

Implementation occurs in an isolated feature worktree. The first phase adds
and validates only:

- `skills/kws-codex-plan-runner/`;
- `skills/kws-claude-plan-runner/`;
- their independent evaluations;
- the root parity evaluation;
- repository routing and skill-index documentation needed for the new names.

During this phase:

- legacy source directories remain unchanged;
- installed legacy symlinks remain unchanged;
- legacy state remains unchanged;
- active legacy controllers and children are not signaled;
- new test state uses new directory names and cannot collide with old state.

Final cutover has two hard preconditions:

1. all CPE and CLPE controllers, children, and helper processes are absent;
2. every legacy state that its legacy schema considers `running`,
   `resumable`, or otherwise intentionally continuable has either reached a
   terminal state or been explicitly marked abandoned by the user for cutover.

Both checks are read-only and must be repeated immediately before filesystem
changes. Process absence alone is insufficient because a resumable run may
intentionally have no live process. The new implementation does not mutate old
state to manufacture terminal status. Explicit abandonment is recorded in the
cutover audit while the original state remains forensic evidence.

If any live process or non-abandoned continuable legacy state remains, the
implementation may be complete but cutover is reported as
`cutover_pending_legacy_runs`.

Once the count is zero, cutover:

1. installs `kws-codex-plan-runner` only under `~/.codex/skills/`;
2. installs `kws-claude-plan-runner` only under `~/.claude/skills/`;
3. removes installed legacy CPE and CLPE symlinks;
4. removes the two legacy source skill directories;
5. preserves legacy runtime state as forensic data;
6. verifies the new symlink targets and absence of traversal;
7. starts fresh Codex and Claude sessions and confirms that each environment
   discovers its intended runner;
8. reruns the relevant installed-path smoke checks.

There is no automatic process termination, state migration, compatibility
reader, alias, shim, or legacy resume path.

## 23. Residual Risks and Blind Spots

### 23.1 Delegated semantic judgment

The runner can prove that a command ran successfully at one HEAD. It cannot
independently prove that Superpowers selected every necessary test or that a
reviewer understood the product correctly. Final specification-coverage review
and exact evidence make this risk visible but do not eliminate model judgment.

### 23.2 Provider CLI drift

Codex and Claude flags, stream event shapes, session storage, and structured
output behavior can change. Each run records provider versions and performs a
capability preflight. Unsupported required capabilities fail before worktree
mutation.

### 23.3 Session contamination is heuristic

Some damaged context may look healthy, and a fresh session may lose useful
unstored reasoning. Canonical file-backed recovery, explicit session health,
failure signatures, and fresh fallback limit both failure modes.

### 23.4 Same-user process trust

Private permissions and path checks do not stop a malicious same-UID process.
This design treats provider children as trusted executors and documents that
strong isolation belongs elsewhere.

### 23.5 Opaque task progress

Avoiding plan parsing keeps the runner thin, but it means the runner cannot
compare a parsed task list with submitted completion. The completed-work ledger
and final specification-coverage review are the compensating controls.

### 23.6 Non-deterministic live evidence

Real model canaries can fail because of temporary provider behavior even when
deterministic adapter tests pass. The result is a truthful cutover blocker, not
a reason to weaken or silently omit live validation.

### 23.7 Long but silent legitimate work

A provider can perform internal reasoning without emitting a trusted lifecycle
event. After the stall interval, that session may be replaced even though it
was not logically stuck. This is preferable to allowing repeated token deltas
or logs to keep a non-progressing session alive forever. Long external commands
use explicit command-specific deadlines; mere liveness never proves progress.

## 24. Acceptance Criteria

The implementation is acceptable when:

1. exactly two new provider-specific runner skills exist;
2. neither depends on the other's runtime;
3. both implement the approved common CLI and semantic state contract;
4. both preserve multiple ordered specs and execute multiple ordered plans
   without pairing, merging, rewriting, or early execution;
5. both support healthy-session resume and durable fresh-session fallback;
6. both autonomously recover from ordinary implementation failures;
7. neither repeats an unchanged failed strategy;
8. neither imposes total token, cost, or wall-clock limits;
9. activity leases and explicit command deadlines preserve legitimate long work
   without treating heartbeat-only liveness as progress;
10. exact same-HEAD verification receipts are reused;
11. arbitrary performance percentages cannot become completion gates;
12. final review, verification, cleanliness, ancestry, HEAD, and artifact gates
    fail closed;
13. successful runs end in `ready_for_integration` with
    `integration=not_observed`;
14. provider-specific and parity deterministic evaluations pass;
15. real Codex and Claude session and multi-plan canaries pass;
16. `bun run agent:verify` passes at the final candidate HEAD;
17. review against `code_review.md` has no unresolved Critical or Important
    findings;
18. active legacy runs remain unaffected during implementation;
19. legacy removal and installed-skill cutover occur only after zero live
    legacy processes and zero non-abandoned continuable legacy states are
    confirmed;
20. no legacy compatibility or migration code is introduced;
21. both public launchers use the preinstalled uv-managed normal-GIL CPython
    `>=3.13,<3.14`, never fall back to the system Python, and never download an
    interpreter during `run`, `resume`, or `inspect`;
22. runtime preflight records exact runner identity before worktree or provider
    mutation and does not conflate it with target verification environment
    identity.
