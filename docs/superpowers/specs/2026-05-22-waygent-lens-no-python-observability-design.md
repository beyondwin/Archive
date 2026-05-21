# Waygent Lens No-Python Observability Design

Date: 2026-05-22
Status: Source-aligned update for review

## Goal

Waygent should be inspectable end to end without the legacy Python
`components/agentlens` tree.

The product direction is now:

1. Waygent runtime records durable state, events, and artifacts.
2. `packages/lens-store` reads filesystem evidence.
3. `packages/lens-projectors` builds read-only trust, failure, readiness, and
   execution explanations.
4. `apps/api`, `apps/console`, and `waygent inspect/explain` expose those same
   facts.
5. Python AgentLens is removed after active routing, docs, CI, and KWS executor
   telemetry dependencies are dealt with explicitly.

This is not a new observability rewrite from scratch. Recent commits already
implemented much of the TypeScript/Rust Waygent path. The remaining work is to
finish the cutoff cleanly and avoid extending the Python tree by accident.

## Source-Audited Baseline

Current active source surfaces:

- `apps/cli/src/index.ts` dispatches `run`, `status`, `events`, `inspect`,
  `explain`, `resume`, `apply`, and `scaffold-plan` through
  `@waygent/orchestrator`.
- `packages/orchestrator/src/runCommands.ts` already reads v2 state, returns
  `execution_explanation` from `inspectRun`, makes `explainRun` prefer v2
  failure evidence, gates `resumeRun`, and revalidates apply readiness.
- `packages/orchestrator/src/orchestrator.ts` writes `waygent.run_state.v2`,
  `agentlens.event.v3`, provider attempts, verification records, checkpoint
  artifacts, combined apply evidence, completion audit, and artifact index.
- `packages/lens-store/src/eventJournal.ts`, `artifactStore.ts`, `runIndex.ts`,
  and `projection.ts` own current filesystem evidence helpers.
- `packages/lens-projectors/src/apply.ts`, `trust.ts`, and
  `executionExplanation.ts` already project apply readiness, trust/failures,
  timeline, safe-wave barriers, cost hotspots, and artifact-health summaries.
- `apps/api/src/server.ts` already exposes real run roots when
  `WAYGENT_RUN_ROOT` or an explicit API context is provided. It returns v2 state
  evidence, provider attempts, verification, recovery, drift, readiness, trust,
  timeline, and execution explanation.
- `apps/console/src/uiModel.ts` and `apps/console/src/App.tsx` already render a
  real-run detail model with execution intelligence, provider signals,
  verification, recovery, drift, and apply status.
- `packages/testkit/src/legacyCheck.ts` already guards active product trees
  against Python runtime files, legacy Waygent v1 state, AgentRunway routing,
  Graphify runtime dependencies, and active KWS event namespaces.
- `tests/waygent-scenarios/*.json` and
  `tests/integration/waygent-scenarios.test.ts` provide deterministic
  fake-provider replay coverage for readiness, blockers, provider attempts,
  and combined patch refs.

Cutoff surfaces addressed by this update:

- `AGENTS.md`, `CLAUDE.md`, `README.md`, active architecture docs,
  `docs/contracts/events.md`, `docs/operations/waygent.md`, and
  `docs/operations/verification.md` now route active work to the TypeScript
  Waygent Lens path.
- The stale `.github/workflows/dashboard-ci.yml` workflow, which targeted the
  old root `AgentLens/**` path, is removed.

Remaining blockers:

- `components/agentlens/` still contains the Python package, FastAPI app,
  dashboard assets, schemas, evaluator, tests, and docs.
- KWS executor skills still document best-effort calls to `agentlens run-open`,
  `agentlens event append`, `agentlens run-close`, and `agentlens events` under
  `kws-cpe.*` and `kws-cme.*`. Those skills are not the Waygent product
  runtime, but they are load-bearing local executor contracts.

## Non-Goals

- Do not add new Python AgentLens features.
- Do not add a Python compatibility shim for active Waygent events.
- Do not route active Lens work into `components/agentlens`.
- Do not reintroduce AgentRunway, KWS CPE, or KWS CME as Waygent runtime
  routing.
- Do not weaken completion audit, checkpoint manifest validation, dry-run
  evidence, combined patch evidence, reconciliation, or clean-checkout apply
  checks.
- Do not make demo data count as proof that real Waygent runs are inspectable.
- Do not rewrite KWS executor skill telemetry casually; treat it as a separate
  compatibility decision before deleting Python AgentLens.

## Target Architecture

### Active Runtime Evidence

`waygent run` remains the only active runtime writer. It writes:

- `agentlens.event.v3` events under `platform.*`, `runway.*`, `kernel.*`, and
  `lens.*`;
- `waygent.run_state.v2` as the authoritative runtime state;
- provider, worker, verification, checkpoint, dry-run, combined apply,
  recovery, and apply artifacts under the run root;
- latest-run metadata through `packages/lens-store`;
- artifact index entries for inspection and reconciliation.

The event schema name remains `agentlens.event.v3` for now. That name is a
durable contract label, not a dependency on the Python AgentLens implementation.

### Active Lens Read Path

The active Lens read path is TypeScript:

```text
run root
  -> packages/lens-store
  -> packages/lens-projectors
  -> packages/orchestrator inspect/explain
  -> apps/api
  -> apps/console
```

The shared model does not need to invent a second scheduler or trust engine. It
should compose the current projections:

- trust and failures from `projectTrustReport` and `projectFailureSummary`;
- apply readiness from `projectApplyReadinessFromState`;
- safe-wave and cost explanation from `projectExecutionExplanationFromState`;
- event timeline from `projectTimeline`;
- durable state and artifact refs from `waygent.run_state.v2`.

If a future `WaygentRunInspection` envelope is added, it should wrap these
existing projections instead of duplicating readiness, trust, or task-status
logic.

### API And Console

`apps/api` is the product read API. Real run roots should be preferred when a
run root is configured. Demo data remains only a local fallback.

`apps/console` should map API detail into UI state without recomputing apply
readiness. It may reshape data for presentation, but the source status,
readiness, trust, failure, and artifact evidence must come from the shared
TypeScript projections or v2 state.

### CLI

`waygent inspect` returns structured JSON for debugging, tests, and operator
inspection. `waygent explain` returns a concise operator summary grounded in
v2 state and the same projectors. The same run should not produce conflicting
readiness, trust, or blocker facts between CLI, API, and console.

### Python Legacy Boundary

`components/agentlens` is legacy. It may remain in the repository only while
deletion blockers are unresolved.

Deletion includes:

- Python package metadata and CLI commands;
- Python schemas and validators;
- Python evaluator and trust artifact code;
- Python FastAPI app and dashboard assets;
- Python tests, fixtures, caches, and local virtualenv guidance;
- active docs, CI, or agent instructions that point to Python AgentLens.

Historical migration docs may mention Python AgentLens when clearly framed as
past context. Active docs and agent instructions must not send new work there.

## Deletion Blockers

Before deleting `components/agentlens`, resolve these explicitly:

1. Active Waygent docs and default verification must stop listing Python
   AgentLens as a supported product surface.
2. Stale dashboard CI must be removed or replaced with Waygent API/console
   checks.
3. `bun run check:legacy` should scan active routing docs for
   `components/agentlens` and Python AgentLens verification references.
4. KWS executor skills must either:
   - be declared historical/external to the Waygent product deletion, with no
     expectation that their telemetry is supported by this checkout, or
   - be migrated to a TypeScript Lens-compatible command or no-op telemetry
     adapter before Python removal.
5. `rg` over active docs, apps, packages, tests, and CI must show no active
   Python AgentLens instructions.

## Error Handling

- Missing event journal: return an explicit missing-evidence or run-not-found
  result; do not mark the run trusted.
- Missing v2 state: `inspect` and API may show events, but apply readiness is
  not ready and resume/apply remain blocked by missing state.
- Invalid v2 state: report the state validation failure and avoid inferring
  readiness.
- Missing checkpoint or combined patch artifact: apply readiness stays blocked
  or not ready through the existing runtime gates.
- Digest or byte-length drift: reconciliation blocks readiness.
- API unavailable: console may use demo fallback only when visibly labeled as
  demo/unavailable.
- Python AgentLens absent: active Waygent runtime must still run, inspect,
  explain, resume, and apply through TypeScript packages.

## Testing Strategy

Default active verification:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Use native kernel checks when native files change:

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

Use live provider checks only when explicitly requested and locally
authenticated:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Python AgentLens pytest is not part of active Waygent verification after this
cutoff. If it is run during the deletion audit, it is historical confidence
only, not an active product gate.

## Acceptance Criteria

- Active docs describe Lens as the TypeScript read path in `packages/lens-store`
  and `packages/lens-projectors`.
- Active docs and CI no longer route new work into `components/agentlens`.
- A real `waygent run` can be inspected through CLI, API, and console using
  current TypeScript projections.
- Apply readiness remains based on v2 state, completion audit, checkpoint
  manifests, combined patch evidence, reconciliation, and clean checkout state.
- `bun run check:legacy` flags active Python AgentLens routing references.
- Deletion of `components/agentlens` has an explicit blocker decision for KWS
  executor telemetry.
- Historical references are either under migration/spec history or clearly
  marked as historical.

## Review Checklist

- Does any active doc still call Python AgentLens an active Waygent component?
- Does any default verification command still run `python -m pytest` under
  `components/agentlens`?
- Does API, console, or CLI derive apply readiness independently of
  `projectApplyReadinessFromState` or v2 state?
- Does the design treat KWS executor telemetry as a deliberate blocker instead
  of ignoring it?
- Can `components/agentlens` be deleted in a later patch without changing
  active Waygent runtime behavior?
