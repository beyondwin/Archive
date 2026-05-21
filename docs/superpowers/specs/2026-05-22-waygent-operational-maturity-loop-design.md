# Waygent Operational Maturity Loop Design

Date: 2026-05-22
Status: Draft for user review

## Goal

Waygent should close the gap between passing local tests and being operable as
a trusted local agent runtime. Recent work made the runtime Waygent-native,
v2-only, safer around verification, and more explainable. The next step is to
turn those separate improvements into one operator loop:

1. prove real Waygent dogfood runs contain complete execution evidence;
2. explain runtime cost and plan-shaping opportunities from durable state;
3. make live-provider readiness and failures actionable without making live
   providers part of the default local gate.

The loop should let an operator answer four questions from `inspect`,
`explain`, API, or console:

- why is this run blocked?
- why was this run slow or serial?
- is the recorded evidence complete enough to trust the diagnosis?
- what should I do before the next run?

This design keeps apply readiness strict. Dogfood evidence, runtime cost, and
provider readiness are diagnostic projections. They do not authorize source
checkout mutation and they do not replace completion audit, checkpoint
manifests, combined patch evidence, reconciliation, or clean-checkout checks.

## Current Context

The current product baseline already includes these shipped pieces:

- active Waygent product boundaries under `apps/`, `packages/`,
  `native/kernel/`, `docs/`, and `skills/waygent/`;
- v2-only Waygent runtime state for active execution;
- `platform.*`, `runway.*`, `kernel.*`, and `lens.*` active event families;
- safe-wave scheduling with bounded parallel execution;
- provider adapters for fake, Codex, and Claude process execution;
- verification environment evidence and dependency-missing classification;
- no-op checkpoint patch handling;
- execution explanation projection for safe waves, barriers, phase timings, and
  artifact health;
- documentation for architecture, operations, contracts, recovery, and
  verification.

The remaining gap is not another isolated reliability patch. The gap is that
operators need one product-quality feedback loop that connects real dogfood
evidence, runtime cost, live-provider readiness, and the next safe action.

The repository already documents a dogfood expectation in operations docs:
before treating execution intelligence as complete, a real Waygent dogfood run
should show non-empty `artifact_index`, task `phase_timings`, real event
timestamps, and precise `explain` blockers. This design turns that expectation
into a first-class slice.

## Non-Goals

- Do not weaken checkpoint manifests, patch digest checks, checkpoint dry-run
  evidence, completion audit, reconciliation, or clean-checkout apply rules.
- Do not let dogfood evidence, runtime cost, or provider readiness mark a run
  apply-ready.
- Do not trust provider claims without Waygent-owned verification evidence.
- Do not make Codex or Claude live smoke checks part of default verification.
- Do not reintroduce AgentRunway, KWS CPE, or KWS CME as active Waygent
  routing.
- Do not introduce automatic plan rewriting. Recommendations are read-only
  operator guidance.
- Do not store full provider transcripts or secrets in summaries. Raw provider
  stdout and stderr artifacts remain bounded runtime evidence.

## Design Principles

1. `waygent.run_state.v2` remains the runtime source of truth.
2. AgentLens events and artifacts provide replayable evidence, not a second
   scheduler or apply engine.
3. Projections are pure and read-only whenever possible.
4. Operator surfaces should share one projection shape instead of reimplementing
   diagnosis in CLI, API, and console.
5. Real dogfood runs are acceptance evidence, not optional screenshots.
6. Live-provider diagnostics should be useful offline through fixtures and
   more precise when live checks are explicitly enabled.

## Target Architecture

Waygent Operational Maturity Loop has four layers.

### Layer 1: Dogfood Evidence Gate

Add a dogfood evidence collector that reads durable run evidence after a run
completes or blocks. It should not mutate run state or fabricate missing data.

Inputs:

- `waygent.run_state.v2`;
- event journal;
- artifact index;
- task packet refs;
- provider attempts;
- verification records;
- checkpoint manifests;
- checkpoint dry-run evidence;
- completion audit;
- reconciliation records;
- `inspect` and `explain` projections.

Output:

- dogfood status: `complete`, `partial`, `missing`, or `projection_error`;
- evidence checklist with per-item status and refs;
- missing or stale evidence reasons;
- an optional dogfood run ref when the current run was itself created by a
  Waygent dogfood command.

Required checklist items:

- non-empty event journal;
- non-empty provider attempt records for executed tasks;
- non-empty verification records for executed tasks;
- non-empty `artifact_index` for real execution artifacts;
- task `phase_timings` with at least provider, verification, checkpoint or
  blocked phase, and total timing where applicable;
- wave timing and concurrency when safe waves execute;
- real runtime timestamps rather than fixed fixture timestamps;
- `explain` summary with either a precise blocker or a precise no-blocker
  statement;
- readiness-critical artifact refs when apply readiness is `ready`.

The collector may be exposed as a projector in `packages/lens-projectors` and
called by `inspect`, API, and console. If it writes any additional dogfood
artifact later, that write must be explicit and separate from apply readiness.

### Layer 2: Runtime Cost And Operator Feedback Projection

Extend the current execution explanation into a more explicit runtime-cost and
plan-feedback model.

Inputs:

- safe waves and withheld reasons;
- task dependencies, risk, and file claims;
- task `phase_timings`;
- wave timing and concurrency;
- artifact health;
- drift records;
- dogfood evidence status.

Output:

- estimated wave count;
- measured wave count;
- parallelism score;
- serial barriers grouped by dependency, file claim, risk, checkpoint,
  failure, or source state;
- top runtime hotspots by phase and task;
- fixed-cost summary for worktree setup, provider, verification, checkpoint,
  checkpoint dry-run, and reconciliation when available;
- plan-shaping recommendations.

Recommended actions should be concrete but read-only:

- split overlapping owned file claims;
- add explicit dependencies where tasks already serialize by hidden order;
- reduce high-risk task scope before expecting wider safe waves;
- inspect verification environment cost before changing provider concurrency;
- repair missing or drifted artifacts before applying checkpoints;
- run a dogfood check when evidence completeness is partial.

This projection should live in `packages/lens-projectors` so `inspect`, API,
and console use one shared shape.

### Layer 3: Live Provider Readiness Projection

Add a provider-readiness model that summarizes live-provider preflight and
process evidence without requiring live providers in the default test suite.

Inputs:

- selected provider profile;
- configured process command;
- provider process evidence;
- exit code, timeout, and malformed-output classification;
- provider stderr summary categories;
- offline replay fixtures for unavailable CLI, auth failure, timeout, crash,
  malformed output, and successful worker result.

Output:

- provider readiness status: `ready`, `not_configured`, `unavailable`,
  `auth_required`, `failed`, or `unknown`;
- command summary without secrets;
- stderr category counts and selected bounded samples;
- failure class when a provider attempt already exists;
- recommended next action.

Live smoke behavior stays opt-in:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Offline tests should validate the classification and projection shape with
fixtures. Live tests can add confidence, but they are not required for normal
local development.

### Layer 4: Operator Surfaces

Expose the same operational maturity loop through CLI, API, console, and docs.

CLI:

- `waygent inspect --json` includes `dogfood_evidence`, `runtime_cost`, and
  `provider_readiness` when v2 state is available.
- `waygent explain --last` prioritizes hard blockers, then cost hotspots, then
  missing dogfood evidence when no hard blocker exists.
- `resume` and `apply` continue to use existing readiness and recovery policy.

API:

- run detail responses include the same projection fields used by CLI inspect;
- projection errors are represented as data, not thrown as 500s for otherwise
  readable runs;
- API does not compute an independent apply-readiness shortcut.

Console:

- add a compact operational maturity section for real run details;
- show hard blocker, runtime hotspot, dogfood status, provider readiness, and
  next action;
- keep apply controls tied only to apply readiness;
- keep dense operator styling rather than marketing or explanatory UI.

Docs:

- document the loop as run, inspect, explain, repair provider/environment/plan,
  rerun;
- document how to read dogfood evidence and runtime cost;
- keep live provider smoke clearly opt-in;
- refresh Graphify output after meaningful structure changes.

## Data Flow

1. `waygent run` executes the normal v2 path: plan discovery, safe-wave
   scheduling, provider attempts, verification, checkpoints, completion audit,
   reconciliation, and AgentLens event emission.
2. `inspect` reads v2 state and events, then computes execution explanation,
   dogfood evidence, runtime cost, and provider readiness projections.
3. API run detail returns those same projections for real v2 runs.
4. Console maps the API fields into read-only operator sections.
5. `explain` returns the shortest useful diagnosis:
   - hard blocker first;
   - otherwise top runtime hotspot;
   - otherwise missing or partial dogfood evidence;
   - otherwise no active failure barrier and no trust-preserving optimization.
6. `resume` and `apply` keep their existing gate order and do not consult
   diagnostic projections as readiness authority.

## Error Handling And Recovery Policy

### Hard Blockers

Hard blockers can stop resume or apply:

- `dirty_source_checkout`;
- `missing_run_state_v2`;
- `unsupported_run_state`;
- `invalid_run_state_v2`;
- `checkpoint_manifest_missing`;
- `checkpoint_patch_missing`;
- `checkpoint_digest_mismatch`;
- `combined_patch_missing`;
- `state_drift`;
- `artifact_missing`;
- `environment_blocker`;
- `dependency_missing`;
- provider crash, timeout, or malformed output after the allowed recovery
  policy.

Handling:

- `explain` names the blocker first.
- `resume` returns only the allowed recovery action.
- `apply` appends a blocked event and stops before source mutation.

### Evidence Gaps

Evidence gaps do not authorize or block apply by themselves:

- empty artifact index;
- missing phase timing;
- missing provider stderr summary;
- missing dogfood evidence refs;
- generic `explain` summary;
- projection failure for a non-readiness diagnostic.

Handling:

- expose `dogfood_evidence.status = partial`, `missing`, or
  `projection_error`;
- include reasons and refs where available;
- keep apply readiness unchanged;
- make the gap visible in CLI/API/console and dogfood gate output.

### Optimization Signals

Optimization signals are plan-quality guidance:

- overlapping file claims serialized the run;
- high-risk tasks withheld wider safe waves;
- worktree setup dominated runtime;
- verification dominated runtime;
- provider stderr contains repeated non-actionable noise;
- live-provider setup is unavailable or auth-gated.

Handling:

- add concrete `recommended_next_actions`;
- do not rewrite the plan automatically;
- do not retry live providers automatically from chat context.

### Projection Failures

Projection calculation must fail closed:

- failure to compute runtime cost or dogfood evidence must not turn a blocked
  run into a ready run;
- readable state and events should still be returned with a `projection_error`
  object;
- exceptions in API projection code should become structured run-detail
  warnings when the underlying run can still be inspected.

## Testing Strategy

### Unit Tests

Add focused projector tests for:

- complete dogfood evidence from a representative v2 state;
- partial dogfood evidence with missing artifact index or phase timings;
- hard-blocked runs with missing checkpoint or state drift;
- runtime cost projection with parallel and serialized waves;
- runtime cost recommendations for file claims, risk, dependency, and
  verification bottlenecks;
- provider readiness classifications for unavailable CLI, auth-required,
  timeout, crash, malformed output, and success.

### CLI Tests

Add or extend tests for:

- `inspect` includes `dogfood_evidence`, `runtime_cost`, and
  `provider_readiness`;
- `explain` prioritizes v2 task failure classes over event-only summaries;
- `explain` can report a runtime hotspot when no hard blocker exists;
- `apply` remains blocked by existing readiness blockers even when diagnostic
  projections look healthy.

### API And Console Tests

Add or extend tests for:

- real v2 run detail includes the maturity loop fields;
- API returns projection errors as structured data for inspectable runs;
- console sections include operational maturity evidence;
- apply button state remains derived from apply readiness only.

### Scenario And Dogfood Tests

Extend deterministic fake-provider scenarios with expected maturity fields
where stable. Add a dogfood command or test helper that runs a real Waygent
fixture and checks:

- non-empty artifact index;
- task phase timings;
- provider attempts;
- verification evidence;
- real timestamps;
- precise `explain` result;
- runtime cost summary;
- dogfood evidence status.

The dogfood helper can run offline with fake provider by default. Live provider
dogfood remains opt-in.

### Live Provider Tests

Keep live smoke opt-in. Add offline replay fixtures for provider readiness
classification. When live smoke is explicitly enabled, assert that the live run
uses the same projection shape and does not bypass Waygent verification.

## Verification Commands

Default gate:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Docs-only checkpoint while drafting:

```bash
git diff --check
```

Optional live provider gate:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Graph refresh after meaningful structure changes:

```bash
graphify update .
```

## Acceptance Criteria

The design is implemented when all of the following are true:

- `inspect --json` exposes dogfood evidence, runtime cost, and provider
  readiness for real v2 runs.
- `explain` gives an operator a precise next diagnosis without falling back to
  `unknown` when state has a clearer failure class.
- API and console render the same maturity loop fields from shared projection
  shapes.
- Dogfood evidence can distinguish complete, partial, missing, and projection
  error states.
- Runtime cost projection explains serial barriers and phase hotspots from
  durable evidence.
- Provider readiness classifies unavailable, auth-required, failed, malformed,
  timeout, and ready cases without requiring live provider access by default.
- Apply readiness remains governed only by existing v2 completion audit,
  checkpoint, combined patch, reconciliation, and clean-checkout rules.
- Default verification commands pass.
- Graphify output is refreshed if the implementation changes meaningful code or
  documentation structure.

## Review Checklist

Before implementation planning, confirm:

- the loop is one cohesive operator maturity slice, not three unrelated UI
  additions;
- `waygent.run_state.v2` remains the only active runtime state authority;
- projections stay read-only and cannot authorize apply;
- live provider checks remain opt-in;
- no AgentRunway, KWS CPE, or KWS CME active routing is revived;
- console/API use shared projections rather than independent readiness logic;
- dogfood evidence is treated as acceptance evidence and operator diagnosis,
  not as a hidden mutation gate.
