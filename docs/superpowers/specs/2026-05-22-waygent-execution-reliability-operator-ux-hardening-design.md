# Waygent Execution Reliability And Operator UX Hardening Design

Date: 2026-05-22
Status: Draft for user review

## Goal

Waygent should handle the execution-intelligence dogfood failure class without
operator-written wrapper plans or manual verification command surgery, then
make the resulting run evidence easy to understand from CLI, API, and console.

This design intentionally combines the broader operator experience work with
the core reliability fix. The broader scope is acceptable only because the
first phase is a hard gate: verification environment hardening, failure
classification, state-based explain/resume, and real event timestamps must land
before console polish or provider-log cleanup can be considered complete.

## Observed Failure

The recent execution-intelligence run showed two different truths:

- The provider completed the implementation and reported successful local
  verification from inside its worker process.
- Waygent kernel verification failed in the isolated worktree because the
  worktree did not have dependency access. `bun test` could not resolve `ajv`,
  and the console build could not resolve `@vitejs/plugin-react`.

The retry passed only after the verification commands manually symlinked
`/Users/kws/source/private/Archive/node_modules` into the isolated worktree and
removed it after each command.

The successful retry also exposed follow-up gaps:

- `explain` summarized the failed run as `unknown` instead of using the
  task-level `latest_failure_class`.
- events used a fixed `occurred_at` timestamp, which weakens timeline analysis.
- the newly implemented artifact index and phase timing model need a dogfood
  run on the latest runtime to prove they appear in real run state.
- provider stderr contains repeated plugin and skill loader warnings that bury
  important signals.
- the source implementation plan was not directly executable because it did not
  contain a `waygent-task` block.

## Non-Goals

- Do not weaken checkpoint manifests, patch digest checks, dry-run evidence,
  completion audit, reconciliation, or clean-checkout apply rules.
- Do not let provider-reported success override Waygent-owned kernel evidence.
- Do not restore legacy AgentRunway or KWS executor routing.
- Do not make `node_modules` a tracked artifact or commit runtime state.
- Do not infer broad file claims, risk, or dependencies from prose without an
  explicit operator review point.
- Do not make live Codex or Claude provider smoke tests part of the default
  local test suite.

## Design Principles

1. Failure handling is a trust boundary, not a display detail.
2. Verification environment setup must be owned by Waygent, not by ad hoc
   command prefixes in a temporary plan.
3. `explain` and `resume` must prefer durable v2 state when event payloads are
   incomplete or ambiguous.
4. Console UX should summarize evidence already captured by the runtime; it
   must not invent readiness or recovery decisions.
5. Dogfood runs are acceptance evidence. A feature that only passes fixture
   tests but does not appear in a real Waygent run is not done.

## Target Architecture

### Phase 1: Core Reliability Gate

Phase 1 is mandatory and blocks every later phase.

#### Verification Environment

Add a small orchestration-owned verification environment layer between worktree
preparation and kernel command execution.

Responsibilities:

- inspect the source workspace for dependency affordances that are safe to
  inherit into an isolated worktree;
- prepare temporary verification-only links or environment variables before
  running kernel verification;
- record setup and cleanup evidence in task state or verification evidence;
- remove temporary links after verification, even when a command fails;
- classify setup failure as `environment_blocker`;
- classify missing runtime dependencies as `dependency_missing`.

The first implementation should support the local Bun workspace case:

- if the source workspace has `node_modules` and the task worktree does not,
  create a temporary worktree-local `node_modules` symlink for verification;
- remove that symlink after verification;
- never include `node_modules` in checkpoint patches, artifact index entries,
  or provider changed files;
- keep the existing forbidden write glob for `node_modules/**`.

This is intentionally narrower than dependency installation. Installing inside
each worktree can be added later if Waygent needs fully hermetic runs, but the
current failure is dependency access, not dependency resolution policy.

#### Verification Failure Classification

`runVerificationCommands` should return structured failure information in
addition to kernel results:

- `failure_class`;
- `failure_summary`;
- command index or verification id for the first blocking command;
- evidence refs after kernel artifacts are written.

Classification should be deterministic and conservative:

- timeout -> `timeout`;
- command not found -> `command_not_found`;
- module/package resolution failures such as `Cannot find package` and
  `ERR_MODULE_NOT_FOUND` -> `dependency_missing`;
- permission policy denial -> `permission_denied`;
- verification environment setup failure -> `environment_blocker`;
- all other non-zero verification exits -> `verification_failed`.

`TaskExecutor` should use this classified failure when writing
`latest_failure_class` and `runway.verification_result` payloads. A completed
provider result plus failed verification must produce a blocked task with
Waygent-owned failure evidence.

#### State-Based Explain And Resume

`explainRun` should use v2 state as the primary source for active failure
barriers:

1. find blocked or failed tasks with `latest_failure_class`;
2. fall back to failure projector events only when v2 state is missing;
3. include the top cost hotspot from execution explanation;
4. include artifact health when missing or drifted artifacts exist.

`resumeRun` should then select actions from the same failure class:

- `dependency_missing` or `environment_blocker` -> repair verification
  environment, then rerun verification;
- `verification_failed` -> rerun verification only when retry budget allows,
  otherwise human decision;
- `artifact_missing` or `state_drift` -> retry checkpoint generation or human
  decision;
- `dirty_source_checkout` and `needs_rebase` -> clean source checkout.

The action names can remain existing strings in the first implementation if
contracts would otherwise expand too far, but the summary must no longer report
`unknown` when state contains a precise failure class.

#### Real Event Timestamps

`buildRunEvent` should use `new Date().toISOString()` for `occurred_at` by
default. Tests that need deterministic timestamps should pass an explicit clock
or expected value through a helper. Runtime events should no longer share a
fixed date.

### Phase 2: Provider Signal Hygiene

Provider process stderr should remain available as raw evidence, but CLI/API
surfaces should expose a compact signal summary.

Add a provider log summarizer that classifies stderr lines into:

- `error`;
- `warning`;
- `mcp`;
- `plugin_manifest`;
- `skill_loader`;
- `other`.

The raw provider stderr artifact remains unchanged for auditability. The
summary becomes operator metadata in provider attempt evidence. Console and
`inspect` can show counts plus the first few important lines.

This phase should not hide provider crashes or malformed worker output. It only
reduces repeated non-actionable warnings in operator-facing views.

### Phase 3: Executable Plan Scaffold

Waygent should help operators produce an executable `waygent-task` wrapper
without guessing hidden trust fields.

Add a scaffold path that can produce a draft task block from explicit operator
inputs:

- task id;
- title;
- file claims;
- risk;
- verification commands;
- optional spec path and plan prose path.

The scaffold must not automatically infer owned files or risk from prose for an
apply-capable run. It may suggest candidate file claims, but the output should
remain reviewable before execution.

Acceptable surfaces:

- CLI command such as `waygent scaffold-plan`;
- or a documented helper in `skills/waygent/SKILL.md`;
- or a small orchestrator function that the CLI can expose later.

The immediate acceptance criterion is that the next docs-first implementation
plan can be turned into a valid `waygent-task` block without creating a
temporary `/tmp` wrapper by hand.

### Phase 4: Console Operator UX

The console should render the same execution explanation used by CLI/API:

- top failure barrier;
- recommended next action;
- phase timing breakdown;
- artifact health counts;
- readiness artifact refs;
- provider log signal summary.

The console must keep dense operational styling. This is an operator console,
not a marketing page. It should make repeated inspection faster by reducing the
time from “run failed” to “the next safe action is clear.”

### Phase 5: Artifact Index Dogfood

Run a real Waygent dogfood execution on the latest runtime and verify that the
state contains:

- non-empty `artifact_index`;
- task `phase_timings`;
- real `occurred_at` timestamps;
- classified verification failures when dependency access is intentionally
  removed;
- clean artifact health when the environment is prepared;
- `explain` output that names the precise blocker or says no active failure
  barrier.

This phase is not just an integration test. It is the acceptance evidence that
the execution-intelligence feature works on Waygent itself.

## Data Flow

1. `runWaygent` prepares the run and v2 state.
2. `TaskExecutor` asks `WorktreeManager` for an isolated worktree.
3. `VerificationEnvironment` prepares temporary verification affordances.
4. Kernel verification runs commands in the worktree.
5. Verification output is classified into a Waygent failure class.
6. `TaskExecutor` writes provider, verification, checkpoint, artifact index,
   timing, and failure evidence into the task result.
7. The run execution context replays task evidence into ordered events and v2
   state.
8. Completion audit and reconciliation decide apply readiness.
9. `inspect`, `explain`, API, and console project the same state into operator
   explanations.
10. Dogfood run evidence proves the full loop.

## Error Handling

- Environment setup failure blocks verification with `environment_blocker`.
- A temporary symlink cleanup failure is recorded. If the symlink remains in
  the worktree, checkpoint scope validation must still prevent it from being
  applied.
- Dependency resolution failures become `dependency_missing`; they do not look
  like provider success or unknown failure.
- Provider stderr summarization failure does not block a run because raw
  stderr is still preserved.
- Scaffold generation must fail loudly when required fields are missing.
- Console projection failure may show partial data, but cannot mark a blocked
  run ready.

## Testing Strategy

### Unit Tests

- verification environment creates and removes a temporary `node_modules`
  symlink;
- verification environment records cleanup evidence on command failure;
- verification classifier maps missing packages to `dependency_missing`;
- verification classifier maps command-not-found and timeout cases correctly;
- `explainRun` prefers v2 task `latest_failure_class` over empty event failure
  projection;
- `buildRunEvent` records current timestamps unless a test helper supplies a
  deterministic clock;
- provider log summarizer groups repeated plugin and skill warnings;
- plan scaffold rejects missing file claims, risk, or verification commands.

### Integration Tests

- a Waygent run with an isolated worktree and inherited Bun dependencies passes
  verification without command-level symlink prefixes;
- a run with dependency inheritance disabled produces `dependency_missing` and
  `resume` offers a verification-environment repair path;
- API run detail exposes classified blocker, phase timings, artifact health,
  and provider log summary;
- console model renders the same execution explanation fields;
- scenario harness includes a fixture for dependency-missing verification.

### Dogfood Verification

After implementation, run at minimum:

- `bun run check`;
- `bun run waygent:scenarios`;
- `bun run platform:demo`;
- `bun run check:legacy`;
- `bun run --cwd apps/console build`;
- `git diff --check`;
- one real Waygent run that exercises verification environment preparation and
  confirms non-empty artifact index plus phase timings in `inspect`.

## Acceptance Criteria

- The original execution-intelligence failure class is fixed without manual
  verification command prefixes.
- `waygent explain` no longer reports `unknown` when v2 state has a precise
  failure class.
- Runtime event timestamps reflect actual event creation time.
- Raw provider logs remain available, while operator surfaces show compact
  signal summaries.
- Operators can create an executable `waygent-task` wrapper through a scaffold
  path instead of hand-writing a temporary `/tmp` plan.
- Console/API/CLI expose the same execution explanation data.
- Dogfood evidence proves `artifact_index` and `phase_timings` are populated by
  the latest runtime.

## Open Questions For Implementation Planning

- Should verification environment inheritance be enabled by default for local
  workspaces, or require an explicit plan/profile field?
- Should scaffold live first in `apps/cli` or in the `skills/waygent` wrapper
  protocol?
- Should `dependency_missing` map to a new resume action string immediately, or
  reuse `rerun_verification` with a richer summary in the first pass?
