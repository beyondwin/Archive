# Waygent No-Legacy Runtime Design

Date: 2026-05-22
Status: Historical; superseded for Python AgentLens by the no-Python Lens cutoff

> Status: historical. This design predates deletion of the legacy Python
> `components/agentlens` tree. Use current Waygent docs and the no-Python Lens
> cutoff plan for active routing.

## Goal

Make the active Waygent product runtime Waygent-native and v2-only while
preserving quality gates. This design intentionally splits the work into two
sequential phases so Phase 2 can start immediately after Phase 1 passes its
acceptance gates.

Phase 1 removes legacy compatibility from the TypeScript product runtime:
Waygent state handling, plan parsing, contracts, projectors, and active
operator docs.

Phase 2 removes or replaces the remaining AgentLens Python AgentRunway
compatibility surface: `agentlens agentrunway`, `agentrunway_projection`,
AgentRunway trust artifacts, and Python fixtures.

## Current Context

Waygent is now the active user-facing runtime. New runs use
`waygent.run_state.v2`, active events use `platform.*`, `runway.*`,
`kernel.*`, and `lens.*`, and apply readiness comes from v2 state plus
completion audit evidence.

Three legacy surfaces remain in the product path:

- `waygent.run_state.v1` fallback in orchestrator command handling.
- `agentrunway-task` plan-fence compatibility in plan parsing and discovery.
- `legacy_source: "agentrunway"` in TypeScript runway projection contracts.

AgentLens Python also still contains a larger read-compatibility surface for
historical AgentRunway trust-console artifacts. That surface is intentionally
not mixed into Phase 1 because it touches many Python schemas, fixtures,
commands, and evaluator tests.

## Non-Goals

Phase 1 does not delete `skills/kws-*`, historical migration/design documents,
or AgentLens Python AgentRunway compatibility code.

Phase 2 does not change Waygent safe-wave scheduling, provider adapters,
checkpoint semantics, or apply readiness rules except where AgentLens Python
names need to become Waygent-native.

The repository should keep a legacy guard. Removing legacy compatibility does
not mean removing the checks that prevent old namespaces from returning to the
active product path.

## Phase 1: Waygent Product Runtime Cleanup

### Runtime State

`packages/orchestrator` should support `waygent.run_state.v2` as the only
runtime state schema for `inspect`, `resume`, and `apply`.

Remove the v1 `WaygentRunState` interface and v1 `readRunState` /
`writeRunState` helpers from active runtime code. Keep the shared path helper
if useful, but reads and writes must validate through
`readRunStateV2` / `writeRunStateV2`.

`inspect` may still show event-derived status and failure summaries for runs
without v2 state, but it must not pretend a legacy state is authoritative.
`resume` and `apply` must block when v2 state is missing or invalid.

Recommended blockers:

- `missing_run_state_v2` when `state.json` is absent.
- `unsupported_run_state` when `state.json` exists but is not
  `waygent.run_state.v2`.
- `invalid_run_state_v2` when v2 schema validation fails.

### Plan Input

`waygent-task` is the only supported plan fence for new product execution.

Remove `agentrunway-task` from:

- `packages/orchestrator/src/planParser.ts`
- `packages/orchestrator/src/planDiscovery.ts`
- plan-parser tests that currently assert import compatibility

The parser error should explicitly tell operators to use `waygent-task`.
Plan discovery should ignore markdown files that only contain
`agentrunway-task`.

### Contracts And Projections

`LensRunwayProjection` should describe current Waygent projection state only.
Remove `legacy_source` from:

- `packages/contracts/src/types.ts`
- `packages/contracts/src/schemas.ts`
- `packages/lens-projectors/src/trust.ts`
- matching tests and fixtures

`projectRunwayProjection` should not special-case `agentrunway.*` events.
If historical events are still loaded through TypeScript fixtures, they should
be treated as ordinary events or rejected by the relevant contract test. They
must not create a product-level legacy projection mode.

### Active Documentation

Update active operator and review docs so they describe Waygent, not
AgentRunway, as the runtime surface. In particular:

- Rename `AgentRunway Checks` in `code_review.md` to `Waygent Runtime Checks`.
- Keep `AGENTS.md` guidance that historical names are read-compatibility
  context, but avoid wording that frames AgentRunway as an active route.
- Keep dated migration/design docs as history unless they actively instruct a
  current runtime route.

### Legacy Guard

Keep `packages/testkit/src/legacyCheck.ts` and strengthen it for the new
boundary:

- reject active `agentrunway-task` in `apps`, `packages`, `native`, and
  `tests`;
- reject active `waygent.run_state.v1` in product runtime code;
- reject `legacy_source` in TypeScript product contracts and projectors;
- keep existing checks for `skills/agent-runway`, `agentrunway.py`, and
  active KWS event namespaces.

The guard may allow AgentLens Python legacy files during Phase 1 if they are
explicitly outside the active product runtime scan.

## Phase 1 Data Flow

New run flow:

1. CLI resolves `run` input.
2. Plan discovery accepts only markdown containing `waygent-task`.
3. Orchestrator creates v2 state and validates every v2 read/write.
4. Safe-wave execution, provider attempts, verification, checkpoint creation,
   completion audit, trust projection, and reconciliation run unchanged.
5. `resume` and `apply` use v2 state only.

Read-only flow:

1. `status` and `events` may continue to read event journals.
2. `inspect` may show event-derived summaries when state is absent, but it
   must expose that v2 state is unavailable instead of falling back to v1.

Mutation flow:

1. `apply` checks source checkout cleanliness first.
2. `apply` blocks when v2 state is missing, unsupported, invalid, or not
   apply-ready.
3. Only v2 completion audit plus combined patch evidence can authorize source
   checkout mutation.

## Phase 1 Error Handling

Compatibility fallback should be replaced by explicit blockers.

If a run lacks valid v2 state, `resume` should return only safe inspection or
human-decision actions. It must not infer apply readiness from old state or
from successful-looking events.

If `apply` encounters missing or unsupported state, it should append a
`runway.apply_blocked` event with the blocker reason and return blocked. It
must not synthesize a successful apply event.

If plan input uses `agentrunway-task`, parsing should fail with a direct
message that Waygent requires `waygent-task`.

## Phase 1 Tests

Update or add focused tests:

- v2 state read/write validation remains covered.
- v1 run-state round-trip test is removed.
- `resume` blocks without valid v2 state.
- `apply` blocks without valid v2 state.
- `agentrunway-task` plan fences are rejected or ignored by discovery.
- `LensRunwayProjection` no longer includes `legacy_source`.
- `legacyCheck` fails on active `agentrunway-task`, `waygent.run_state.v1`, and
  product `legacy_source`.

Default verification:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

## Phase 1 Quality And Optimization Targets

The cleanup should reduce branching, not just delete names.

Expected simplifications:

- `runCommands.ts` loses v1 fallback branches and event-only apply success.
- `runState.ts` exposes v2 helpers as the only product runtime state API.
- plan parsing and discovery regexes become Waygent-only.
- projector contract shape shrinks by removing legacy projection metadata.
- active docs use one runtime vocabulary.

Quality must not regress:

- safe-wave parallel execution still preserves sibling evidence on provider
  crashes;
- completion audit and reconciliation remain the apply readiness source;
- live provider smoke remains opt-in;
- console/API models still read real Waygent v2 runs;
- legacy guard remains in the default verification set.

## Phase 1 Acceptance Gate

Phase 1 is complete only when all of these are true:

- no active TypeScript product path supports `waygent.run_state.v1`;
- no active TypeScript product path accepts `agentrunway-task`;
- TypeScript contracts/projectors no longer expose `legacy_source`;
- `bun run check` passes;
- `bun run waygent:scenarios` passes;
- `bun run platform:demo` passes;
- `bun run check:legacy` passes;
- `bun run --cwd apps/console build` passes;
- `git diff --check` passes.

After this gate passes, Phase 2 can begin immediately using the Phase 2 design
below. No new brainstorming step is required unless Phase 1 reveals a new
AgentLens product constraint.

## Phase 2: AgentLens Python Cleanup

### Objective

Remove or replace AgentLens Python AgentRunway compatibility so AgentLens
observability is Waygent-native. This phase is deliberately separate because
the Python surface has broad tests and fixtures.

### Primary Decisions

Phase 2 should choose one of two implementation modes before editing code:

1. Remove AgentRunway trust-console compatibility entirely.
2. Rename and reshape it into Waygent-native trust artifacts.

The recommended mode is rename-and-reshape if AgentLens remains a product
component for Waygent console evidence. Full deletion is acceptable only if the
Waygent TypeScript API and console fully replace those Python trust artifacts.

### Candidate Removals Or Replacements

AgentLens command surface:

- remove or replace `agentlens agentrunway`;
- update CLI registration in `components/agentlens/src/agentlens/cli.py`;
- update help examples that still use `agentrunway.*`.

Evaluator and trust artifacts:

- replace `agentrunway_events.py` with Waygent event projection or remove it;
- replace `agentrunway_v2.py` with Waygent projection or remove it;
- update `engine.py` so trust artifact writing is not coupled to
  AgentRunway context detection;
- update `trust.py` wording and event matching from AgentRunway to Waygent;
- update `trust_artifacts.py` output names if projection artifacts remain.

Schemas and fixtures:

- remove or replace `agentrunway_projection.v1.schema.json`;
- update v2 schemas that hard-code `producer.name = agentrunway`;
- update trust report fields such as `agentrunway_run_id`;
- regenerate expected eval fixtures affected by trust artifact references;
- remove tests that only prove old AgentRunway read compatibility.

### Phase 2 Data Flow

If the rename-and-reshape mode is chosen:

1. AgentLens evaluator loads normal run documents and event streams.
2. It projects active Waygent events from `platform.*`, `runway.*`,
   `kernel.*`, and `lens.*`.
3. It writes Waygent-named trust artifacts.
4. CLI/API/UI consumers read Waygent trust artifacts without AgentRunway field
   names.

If full deletion is chosen:

1. AgentLens evaluator keeps only generic evaluation output.
2. Waygent-specific trust and apply readiness stay in TypeScript
   `packages/lens-projectors`, `apps/api`, and `apps/console`.
3. AgentLens Python no longer emits trust-console projection artifacts.

### Phase 2 Tests

Minimum verification:

```bash
cd components/agentlens
python -m pytest -q
cd ../..
bun run check
bun run check:legacy
git diff --check
```

If Python fixture churn is large, update fixtures in one intentional commit and
keep behavioral code changes separate where practical.

### Phase 2 Acceptance Gate

Phase 2 is complete only when:

- no active AgentLens Python command or schema uses AgentRunway as the current
  product name;
- remaining historical references are fixtures, migration notes, or explicitly
  archived compatibility docs;
- AgentLens pytest passes;
- TypeScript Waygent checks still pass;
- `check:legacy` still guards active product paths.

## Rollout Order

1. Implement Phase 1.
2. Run the Phase 1 acceptance gate.
3. Commit Phase 1.
4. Start Phase 2 from the same spec.
5. Decide Phase 2 mode: rename-and-reshape or full deletion.
6. Implement Phase 2.
7. Run Phase 2 acceptance gate.
8. Commit Phase 2.

This order preserves runtime quality while allowing immediate follow-through
from Waygent product cleanup into AgentLens Python cleanup.
