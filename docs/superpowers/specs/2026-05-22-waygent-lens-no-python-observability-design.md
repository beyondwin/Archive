# Waygent Lens No-Python Observability Design

Date: 2026-05-22
Status: Draft for written-spec review

## Goal

Waygent should let an operator inspect a real `waygent run` end to end without
depending on the legacy Python AgentLens implementation.

The target is a TypeScript-first Lens path:

1. Waygent runtime records durable events, state, and artifacts.
2. Lens packages project that evidence into timeline, trust, failure,
   readiness, and artifact-health views.
3. API and console show the same projection for real runs.
4. CLI `inspect` and `explain` read the same projection.
5. The remaining Python AgentLens tree is removed as legacy code.

This replaces the old split where Python `components/agentlens` still carried
schemas, evaluator code, and web APIs while the active Waygent runtime had
already moved to Bun, TypeScript, and Rust.

## Current Source Context

The current active Waygent path is already TypeScript/Rust:

- `apps/cli` starts runs and exposes status, events, inspect, explain, resume,
  and apply commands.
- `packages/orchestrator` owns run lifecycle, task execution, v2 run state,
  event emission, provider attempts, verification, completion audit, and apply.
- `packages/lens-store` owns filesystem event and artifact helpers.
- `packages/lens-projectors` owns trust, failure, timeline, and apply
  projections.
- `apps/api` can read real Waygent run roots and expose run detail.
- `apps/console` can render real run detail, but still has demo-model residue
  and shallow explanation surfaces.
- `native/kernel` is the future kernel boundary for process/worktree behavior.

The legacy Python implementation remains under `components/agentlens`, but it
is no longer the active product path. It still has v1/v2 schemas, evaluator
logic, commands, tests, and a web app. New Waygent Lens work must not extend
that tree.

## Non-Goals

- Do not add new Python AgentLens features.
- Do not preserve Python AgentLens CLI, FastAPI routes, schemas, tests, or web
  assets as active supported surfaces.
- Do not introduce a Python compatibility shim for Waygent event v3.
- Do not emit active `kws-cpe.*`, `kws-cme.*`, `kws.orchestrator.*`, or
  `agentrunway.*` runtime events.
- Do not let API or console mutate Waygent execution state.
- Do not relax checkpoint, dry-run, completion-audit, reconciliation, or clean
  checkout apply gates.
- Do not make demo fixtures count as proof that real Waygent runs are visible.

## Target Architecture

### Runtime Evidence

`waygent run` remains the only runtime writer. It writes:

- `agentlens.event.v3` event journal entries under `platform.*`, `runway.*`,
  `kernel.*`, and `lens.*`;
- `waygent.run_state.v2` as the authoritative execution state;
- provider, verification, task packet, checkpoint, dry-run, combined patch,
  recovery, and apply artifacts under the run root;
- latest-run metadata through `packages/lens-store`.

Provider adapters and subagents never write Lens state directly. They return
bounded evidence to Waygent, and Waygent decides what becomes durable.

### Lens Projection

`packages/lens-projectors` becomes the single projection layer for active
Waygent inspection.

It should expose a stable `WaygentRunInspection` model with:

- run header: run id, workspace, status, lifecycle outcome, current phase,
  source branch, started/updated/completed timestamps;
- safe-wave explanation: ready tasks, withheld tasks, concurrency, timing, and
  barrier reasons;
- task timeline: task status, risk, dependencies, file claims, attempts,
  checkpoints, timing, latest failure, and decision packet refs;
- provider evidence: provider attempts, process evidence refs, exit status,
  timeout/crash/malformed result signals, and worker result refs;
- verification evidence: commands, kernel result refs, status, digests, and
  changed-file evidence where available;
- trust and failure summary: trusted/failed/insufficient evidence, failure
  classes, recovery actions, and operator next action;
- apply readiness: readiness status, reason, checkpoint refs, combined patch
  ref, and source of the decision;
- artifact health: expected critical artifacts, missing artifacts, digest or
  byte-length drift, and reconciliation blockers;
- event timeline: ordered event summaries from `agentlens.event.v3`.

This model is a projection. It does not authorize apply by itself. Apply
authorization remains in runtime readiness checks and `waygent apply`.

### API

`apps/api` is the product read API for Lens views.

Required active endpoints:

- `GET /healthz`;
- `GET /runs`;
- `GET /runs/:runId`;
- `GET /runs/:runId/events`;
- `GET /runs/:runId/trust`;
- `GET /runs/:runId/failures`;
- `GET /events/stream`.

The API should read real run roots by default when `WAYGENT_RUN_ROOT` or an
explicit context run root is present. Demo data may remain only as a local dev
fallback, clearly separated from real-run behavior.

Run detail should be backed by `WaygentRunInspection`, not by console-specific
ad hoc mapping.

### Console

`apps/console` becomes the primary visual surface for real Waygent runs.

The console should answer:

1. What ran, what is running, or why did it stop?
2. Which tasks were parallelized, serialized, or withheld?
3. What evidence exists for provider output and verification?
4. Why is trust marked trusted, failed, or insufficient?
5. Is apply ready, blocked, already applied, or not ready?
6. Which artifacts prove or block the readiness decision?

Expected sections:

- Runs;
- Overview;
- Safe Waves;
- Tasks;
- Events;
- Evidence;
- Trust;
- Apply;
- Artifacts;
- Recovery.

The console should avoid deriving readiness from successful verification events
alone. It should show the projector result produced from v2 state, events,
completion audit, and reconciliation evidence.

### CLI

`waygent inspect` and `waygent explain` should use the same projector as the
API.

- `inspect` returns structured JSON suitable for debugging and tests.
- `explain` returns a concise operator summary: current status, blocking
  reason, next allowed action, trust status, readiness status, and the most
  important evidence refs.

The same run should not produce contradictory answers across CLI, API, and
console.

### Python Legacy Removal

`components/agentlens` is removed as an active supported component.

Removal includes:

- Python package metadata and commands;
- Python schemas and validators;
- Python evaluator and trust artifact code;
- Python FastAPI app and web assets;
- Python tests and fixtures;
- docs that describe Python AgentLens as active;
- root instructions that list `components/agentlens` as an active target.

Historical references may remain in migration docs only when clearly marked as
old context. Active docs must say Lens is now the TypeScript projection and
inspection layer inside Waygent.

## Sequential Implementation Phases

### Phase 0: Direction Lock And Inventory

Update repository guidance so agents do not continue adding Python AgentLens
work.

Files likely touched:

- `AGENTS.md`;
- `CLAUDE.md`;
- `docs/architecture/waygent.md`;
- `docs/contracts/events.md`;
- `skills/waygent/SKILL.md` if command descriptions mention Python AgentLens.

Done when:

- active docs describe Lens as `packages/lens-store`,
  `packages/lens-projectors`, `apps/api`, and `apps/console`;
- Python AgentLens is described as legacy pending deletion, not a supported
  active surface;
- `git diff --check` passes.

### Phase 1: Projection Contract

Add the shared inspection model to `packages/lens-projectors`.

Files likely touched:

- `packages/contracts/src/types.ts`;
- `packages/contracts/src/schemas.ts` if the inspection model is schema-backed;
- `packages/lens-projectors/src/inspection.ts`;
- `packages/lens-projectors/src/index.ts`;
- `packages/lens-projectors/tests/inspection.test.ts`.

Done when:

- a real `runWaygentDemo` run can be projected into `WaygentRunInspection`;
- blocked, failed, completed, and apply-ready cases have tests;
- missing v2 state returns an explicit unsupported or partial inspection
  result instead of guessing readiness.

### Phase 2: API Uses The Shared Projection

Move `apps/api` run detail to the shared inspection projection.

Files likely touched:

- `apps/api/src/server.ts`;
- `apps/api/tests/api.test.ts`;
- `apps/api/tests/events.test.ts`.

Done when:

- `GET /runs/:runId` returns projection-backed run detail;
- `GET /runs` derives status, trust, and apply state from the same projection;
- API tests create real Waygent run roots and assert real detail fields;
- demo fallback is clearly separated from real-run behavior.

### Phase 3: Console Model Becomes API-First

Simplify `apps/console/src/uiModel.ts` so it maps API inspection responses
rather than reconstructing readiness and task status from scattered fields.

Files likely touched:

- `apps/console/src/uiModel.ts`;
- `apps/console/src/uiModel.test.ts`;
- `apps/console/src/App.tsx`.

Done when:

- console model tests use projection-shaped API fixtures;
- console no longer treats demo model as the authoritative shape;
- missing or partial inspection data renders visibly but does not imply apply
  readiness.

### Phase 4: Console Product Surface

Upgrade the visible console to inspect actual Waygent work.

Files likely touched:

- `apps/console/src/App.tsx`;
- `apps/console/src/styles.css`;
- `apps/console/src/uiModel.test.ts`;
- optional small presentational components under `apps/console/src`.

Done when:

- Overview shows run status, trust, apply readiness, current phase, workspace,
  and timestamps;
- Safe Waves show ready/withheld tasks, barrier reasons, and concurrency;
- Tasks show status, file claims, attempts, checkpoints, and latest failure;
- Evidence shows provider attempts and verification/kernel refs;
- Artifacts show critical artifact health and reconciliation blockers;
- Apply section shows why apply is ready or blocked.

### Phase 5: CLI Inspect/Explain Alignment

Route CLI inspection through the shared projection.

Files likely touched:

- `packages/orchestrator/src/runCommands.ts`;
- `packages/orchestrator/tests/runCommands.test.ts`;
- `packages/orchestrator/tests/runCommandsV2.test.ts`;
- `apps/cli/tests/cli.test.ts`.

Done when:

- `waygent inspect --last` returns the same inspection facts as API detail;
- `waygent explain --last` summarizes status, blocker, trust, readiness, and
  next action from the projection;
- CLI, API, and console fixtures no longer drift in meaning.

### Phase 6: Python Legacy Deletion

Delete Python AgentLens after the TypeScript Lens path covers real run
inspection.

Files likely removed or updated:

- remove `components/agentlens/`;
- update root docs and AGENTS references;
- update package/test scripts that still mention Python AgentLens;
- update migration docs only when they incorrectly describe Python as active;
- remove stale Python verification commands from active default checks.

Done when:

- `rg "components/agentlens|python -m pytest|agentlens.event.v2|agentlens.waygent_projection"` returns only historical migration references or no active references;
- `bun run check` passes;
- `bun run platform:demo` passes;
- `bun run waygent:scenarios` passes;
- `bun run --cwd apps/console build` passes;
- `git diff --check` passes.

## Data Flow

```text
waygent run
  -> packages/orchestrator
  -> waygent.run_state.v2 + agentlens.event.v3 + artifacts
  -> packages/lens-store
  -> packages/lens-projectors WaygentRunInspection
  -> apps/api
  -> apps/console

waygent inspect/explain
  -> packages/orchestrator runCommands
  -> packages/lens-projectors WaygentRunInspection
```

No Python component participates in the active flow.

## Error Handling

- Missing event journal: inspection returns a run-not-found or missing-evidence
  error, not a trusted result.
- Missing v2 state: inspection is partial and apply readiness is not ready.
- Invalid v2 state: inspection reports state validation failure and does not
  infer readiness.
- Missing critical artifact: artifact health marks the artifact missing and
  apply readiness remains blocked or not ready.
- Digest or byte-length mismatch: artifact health reports drift and the run is
  unsafe to apply.
- Projection failure: API/CLI return explicit projection error fields; console
  renders a blocked/partial state instead of crashing.
- Console API unavailable: demo fallback is allowed only as local dev fallback
  and must be labeled as demo data.

## Testing Strategy

### Unit Tests

- `packages/lens-projectors/tests/inspection.test.ts` covers completed,
  blocked, failed, missing-state, invalid-state, and missing-artifact runs.
- Console UI model tests cover projection-shaped API responses.
- API tests cover real run roots, event stream filtering, trust, failures, and
  partial inspection results.

### Integration Tests

- Create a real fake-provider Waygent run and assert CLI/API/console model
  agree on status, trust, tasks, readiness, and checkpoint refs.
- Create a blocked run and assert withheld/barrier reasons are visible.
- Corrupt or remove a critical artifact and assert artifact health blocks
  readiness.
- Remove `state.json` and assert inspection is partial and not ready.

### Deletion Verification

After Python removal:

```bash
rg "components/agentlens|agentlens.event.v2|agentlens.waygent_projection|python -m pytest"
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run --cwd apps/console build
git diff --check
```

Expected result: only historical migration references may remain from the `rg`
check. Active instructions and commands should not point to Python AgentLens.

## Acceptance Criteria

- A real `waygent run` can be inspected through CLI, API, and console from the
  same TypeScript projection.
- API and console show actual task, event, provider, verification, checkpoint,
  trust, apply, recovery, and artifact-health evidence.
- Apply readiness is never inferred from provider success or verification
  success alone.
- Python AgentLens is not part of the active flow and is deleted in the final
  cleanup phase.
- Active docs and agent instructions no longer tell agents to work in
  `components/agentlens`.
- No legacy KWS or AgentRunway runtime namespace is reintroduced.
- Default Bun/console verification passes after the migration.

## Review Checklist

- Does every active read path use `WaygentRunInspection` or the underlying
  shared projector?
- Does any API or console code still guess apply readiness independently?
- Are Python files absent from the active implementation scope?
- Are historical references clearly marked as historical?
- Can deletion of `components/agentlens` be done after the TS path proves
  parity, without blocking earlier projection/API/console work?
