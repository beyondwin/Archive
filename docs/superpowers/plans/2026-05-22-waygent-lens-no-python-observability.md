# Waygent Lens No-Python Observability Implementation Plan

> **For agentic workers:** Implement task-by-task. Keep edits scoped. Do not
> route new Waygent runtime or Lens work into Python `components/agentlens`.

**Goal:** Finish the TypeScript-first Waygent Lens cutoff, align active docs and
CI with the current source, prove CLI/API/console inspection from real run
evidence, then delete the legacy Python AgentLens tree after explicit blocker
resolution.

**Architecture:** `waygent.run_state.v2`, `agentlens.event.v3`, and run
artifacts are the durable source of truth. Active readers are
`packages/lens-store`, `packages/lens-projectors`,
`packages/orchestrator/src/runCommands.ts`, `apps/api`, and `apps/console`.
Python `components/agentlens` has been deleted and is not a supported active
product surface.

**Tech Stack:** Bun, TypeScript project references, React/Vite, Rust kernel,
filesystem JSON/JSONL artifacts, `@waygent/contracts`, `@waygent/lens-store`,
`@waygent/lens-projectors`, `@waygent/orchestrator`.

---

## Source Design

- Design: `docs/superpowers/specs/2026-05-22-waygent-lens-no-python-observability-design.md`
- Architecture index: `docs/architecture/waygent.md`
- Active event contract: `docs/contracts/events.md`
- Active verification: `docs/operations/verification.md`

## Current Source Baseline

Already implemented:

- `packages/contracts/src/types.ts` defines `WaygentRunStateV2`,
  `ApplyReadinessProjection`, `ExecutionExplanationProjection`,
  `ProviderAttempt`, `ReviewResult`, `AgentLensEvent`, and artifact index
  shapes.
- `packages/lens-projectors/src/apply.ts` projects readiness from v2 state and
  completion audit instead of trusting successful verification events alone.
- `packages/lens-projectors/src/executionExplanation.ts` projects safe-wave
  barriers, phase timings, artifact-health summary, cost hotspots, and
  operator recommendations.
- `packages/lens-projectors/src/trust.ts` projects trust, failures, runway
  state, and timeline from events.
- `packages/lens-store/src/eventJournal.ts`, `artifactStore.ts`, and
  `runIndex.ts` provide the active filesystem evidence helpers.
- `packages/orchestrator/src/runCommands.ts` wires `inspect`, `explain`,
  `resume`, and `apply` to v2 state and Lens projectors.
- `apps/api/src/server.ts` exposes real run roots and includes v2 evidence,
  apply readiness, execution explanation, provider attempts, verification,
  recovery, drift, trust, failures, timeline, and events.
- `apps/console/src/uiModel.ts` and `apps/console/src/App.tsx` render real-run
  detail, execution intelligence, provider signals, recovery, verification,
  drift, and apply state.
- `packages/testkit/src/legacyCheck.ts` guards active product trees against
  Python runtime files and legacy routing.
- `tests/waygent-scenarios` cover real fake-provider replay expectations.

Corrected by this document update:

- Active routing docs no longer describe Python AgentLens as an active Waygent
  product surface.
- The stale `.github/workflows/dashboard-ci.yml` workflow that targeted the old
  `AgentLens/**` root is removed.

Resolved by the final cutoff:

- `components/agentlens/` has been deleted from tracked source and ignored
  local residue.
- KWS executor skill telemetry still references an `agentlens` CLI contract,
  but Task 4 treats it as skill-local/external best-effort observability, not
  an active Waygent product blocker.

## Execution Order

1. Lock active routing docs and CI away from Python AgentLens.
2. Tighten legacy checks so new active references cannot come back.
3. Add or confirm source-level parity tests for CLI/API/console using existing
   projectors.
4. Audit KWS executor telemetry and choose deletion behavior.
5. Delete `components/agentlens` only after blockers are resolved.
6. Run full no-Python verification and refresh Graphify if structure changed.

Human approval gates:

- before changing KWS executor telemetry behavior;
- before deleting `components/agentlens` (approved and completed);
- before removing historical migration docs.

---

### Task 1: Lock Active Routing Away From Python AgentLens

**Files:**

- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `.github/copilot-instructions.md`
- Modify: `README.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/architecture/agentlens.md`
- Modify: `docs/architecture/runtime.md`
- Modify: `docs/architecture/decisions.md`
- Modify: `docs/contracts/events.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/operations/verification.md`
- Delete or replace: `.github/workflows/dashboard-ci.yml`

- [x] Replace root project shape guidance with active Waygent surfaces:
  `apps/cli`, `apps/api`, `apps/console`, `packages/lens-store`,
  `packages/lens-projectors`, `packages/orchestrator`,
  `packages/runway-control`, `packages/provider-adapters`, `native/kernel`,
  and `skills/waygent`.
- [x] Mark `components/agentlens` as deleted, not as an active component.
- [x] Remove Python AgentLens from default useful checks.
- [x] Replace README AgentLens links with TypeScript Lens architecture and
  event-contract links.
- [x] Update architecture docs so the active Lens storage/projection path is
  `packages/lens-store` and `packages/lens-projectors`.
- [x] Update event docs so `agentlens.event.v3` is a durable event schema name,
  not a dependency on Python AgentLens.
- [x] Remove Python pytest from active operations and verification checklists.
- [x] Remove stale Copilot routing references to the old Python AgentLens and
  AgentRunway surfaces.
- [x] Remove the stale `dashboard-ci` workflow unless it is replaced by a
  Waygent API/console workflow.

Verify:

```bash
rg -n "components/agentlens|python -m pytest|AgentLens backend|AgentLens lives|AgentLens docs" \
  AGENTS.md CLAUDE.md README.md docs/architecture docs/contracts docs/operations .github
git diff --check -- AGENTS.md CLAUDE.md README.md docs/architecture docs/contracts docs/operations .github
```

Expected: every hit is either an explicit legacy-pending-deletion warning or
historical context. No command should send active Waygent work to Python
AgentLens.

---

### Task 2: Tighten Legacy Check Coverage

**Files:**

- Modify: `packages/testkit/src/legacyCheck.ts`
- Modify: `packages/testkit/tests/legacyCheck.test.ts`

- [x] Extend `activeRoutingRoots` or pattern checks to flag active
  `components/agentlens`, `AgentLens backend`, and Python AgentLens pytest
  instructions in `AGENTS.md`, `CLAUDE.md`, `README.md`, `.github`, active
  architecture docs, active operations docs, apps, packages, native, and tests.
- [x] Keep migration docs and superpowers plan/spec history out of hard-fail
  scope unless they claim active routing.
- [x] Add tests that a fixture active doc containing `cd components/agentlens`
  or `python -m pytest` fails.
- [x] Add tests that historical migration text is allowed when it is outside
  active routing roots.

Verify:

```bash
bun test packages/testkit/tests/legacyCheck.test.ts
bun run check:legacy
```

Expected: both pass after active docs are updated.

---

### Task 3: Confirm Shared CLI/API/Console Projection Parity

**Files:**

- Modify if needed: `packages/orchestrator/src/runCommands.ts`
- Modify if needed: `apps/api/src/server.ts`
- Modify if needed: `apps/console/src/uiModel.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.test.ts`

Current code already exposes `execution_explanation` and v2 apply readiness.
This task is a parity hardening pass, not a rewrite.

- [x] Add a real fake-provider run assertion that `inspectRun`,
  `GET /runs/:runId`, and `buildRunDetailModel` agree on:
  run id, v2 status, trust status, apply readiness, checkpoint refs, combined
  patch ref, provider attempts, verification count, and first safe wave.
- [x] Assert console mapping does not recompute readiness from
  `runway.verification_result` when v2 readiness is `not_ready` or `blocked`.
- [x] Assert `explainRun` summary is grounded in v2 blocked-task evidence when
  present.
- [x] Prefer existing projector fields. Do not add a broad new inspection model
  unless it wraps current projections and removes duplication.

Verify:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
```

Expected: parity assertions pass.

---

### Task 4: Audit KWS Executor Telemetry Before Python Deletion

**Files:**

- Read: `skills/kws-claude-multi-agent-executor/SKILL.md`
- Read: `skills/kws-claude-multi-agent-executor/AGENTS.md`
- Read: `skills/kws-codex-plan-executor/SKILL.md`
- Read: KWS executor `references/`, `docs/`, `evals/`, and helper scripts
  that mention `agentlens`.
- Create or modify: a short decision note under `docs/architecture/decisions.md`
  or the no-Python plan if no ADR convention is available.

- [x] Inventory `agentlens run-open`, `agentlens event append`,
  `agentlens run-close`, `agentlens events`, `AGENTLENS_HOME`,
  `AGENTLENS_PARENT_RUN_ID`, `agentlens_orchestration_run`, `kws-cpe.*`, and
  `kws-cme.*` references in KWS executor skills.
- [x] Decide one of:
  - KWS telemetry is historical/external to active Waygent and is allowed to
    degrade when Python AgentLens is removed;
  - KWS telemetry moves to a TypeScript Lens-compatible command;
  - KWS telemetry becomes explicit no-op best-effort with clear warnings.
- [x] Do not rewrite skill behavior without following each skill's local
  protocol and eval requirements.
- [x] Document the chosen policy before deleting Python AgentLens.

Audit result:

- `skills/kws-codex-plan-executor` uses `kws-cpe.*` event namespaces,
  `agentlens_orchestration_run`, and best-effort `agentlens run-open`,
  `agentlens event append`, `agentlens run-close`, and `agentlens events`
  references in SKILL, references, evals, and helper scripts.
- `skills/kws-claude-multi-agent-executor` uses `kws-cme.*` event namespaces,
  `AGENTLENS_HOME`, `AGENTLENS_PARENT_RUN_ID`,
  `agentlens_orchestration_run`, and best-effort `agentlens run-open`,
  `agentlens event append`, `agentlens run-close`, and `agentlens events`
  references in SKILL, ARCHITECTURE, docs, evals, and helper scripts.
- Policy: preserve those references as skill-local/external observability. They
  are allowed to degrade if no external `agentlens` CLI exists after deleting
  the Python product tree. Do not route them into active Waygent Lens as part
  of this deletion.

Verify:

```bash
rg -n "agentlens run-open|agentlens event append|agentlens run-close|agentlens events|AGENTLENS_|kws-cpe|kws-cme" skills
git diff --check
```

Expected: the remaining references are either intentionally preserved by policy
or scheduled for a separate skill-local migration.

---

### Task 5: Delete Legacy Python AgentLens

**Files:**

- Delete: `components/agentlens/`
- Modify any active docs, CI, package scripts, ignore rules, or Graphify output
  that still point to the deleted tree.

Preconditions:

- Task 1 active routing cutoff is complete.
- Task 2 legacy checks pass.
- Task 3 parity tests pass.
- Task 4 KWS telemetry policy is approved.

Steps:

- [x] Run a final active-reference search:

```bash
rg -n "components/agentlens|AgentLens backend|python -m pytest|agentlens.event.v2|agentlens.waygent_projection" \
  AGENTS.md CLAUDE.md README.md docs apps packages native tests .github package.json
```

- [x] Delete `components/agentlens/`.
- [x] Remove generated Python cache and virtualenv references that only applied
  to the deleted tree.
- [x] Keep historical migration references only when clearly historical.

Verify:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Use native kernel checks if native files changed.

---

### Task 6: Refresh Graphify And Close Documentation

**Files:**

- Modify if present: `graphify-out/GRAPH_REPORT.md`
- Modify if present: `graphify-out/graph.json`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/operations/verification.md`
- Modify: this plan if any task ordering changed during execution.

- [x] Run `graphify update .` after meaningful structure deletion or movement.
- [x] Confirm `GRAPH_REPORT.md` built commit matches current `HEAD` at
  generation time.
- [x] Update architecture and operations docs with the final no-Python state.
- [ ] Record verification results in the final commit or PR description.

Verify:

```bash
git rev-parse HEAD
rg -n "Graph Freshness|Built from commit" graphify-out/GRAPH_REPORT.md
git diff --check
```

Expected: Graphify output is fresh if retained.

## Final Verification Set

Run the smallest sufficient subset for the touched files. For full no-Python
closure:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

If native files changed:

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

If KWS executor skill behavior changed, also run the relevant skill evals after
following the skill-local protocol:

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh
cd skills/kws-claude-multi-agent-executor && ./evals/run.sh
```

## Self-Review Checklist

- Active docs no longer direct new Waygent work to Python AgentLens.
- `agentlens.event.v3` is framed as an event contract label, not Python runtime
  dependency.
- CLI/API/console readiness all derive from v2 state and shared projectors.
- KWS executor telemetry has an explicit approved policy before Python deletion.
- `components/agentlens` deletion does not remove active Waygent runtime code.
- Historical references remain only where they are clearly historical.
