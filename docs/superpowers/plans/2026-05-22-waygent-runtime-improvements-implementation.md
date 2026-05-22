# Waygent Runtime Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the imported runtime-improvements draft into the active
Waygent codebase by implementing source-audited plan/spec preflight, decisions,
spec slicing, cost controls, failure barriers, method evidence, model
attestation, watch/orphan/operator verbs, hooks, and chain support without
weakening current apply readiness.

**Architecture:** Keep `waygent.run_state.v2` and the current
`agentlens.event.v3` envelope as the source of truth for the first slices. Add
small modules under existing owners (`apps/cli`, `packages/orchestrator`,
`packages/contracts`, `packages/context-packer`, `packages/provider-adapters`,
`packages/lens-projectors`, and `skills/waygent`) instead of creating a new
runtime package. Reserve a schema boundary for multi-plan chain only after v2
compatibility is proven.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/contracts`,
`@waygent/orchestrator`, `@waygent/context-packer`,
`@waygent/provider-adapters`, `@waygent/lens-projectors`, JSONL event journals,
filesystem run artifacts, Waygent skill evals.

---

## Source Design

- `docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md`

## Source Audit Corrections

The FixThis draft was not copied verbatim. These corrections are mandatory:

- Use `apps/cli/src/index.ts`, not a non-existent CLI package path.
- Use `packages/orchestrator`, `packages/contracts`, `packages/context-packer`,
  `packages/provider-adapters`, and `packages/lens-projectors`, not
  non-existent runtime/shared package paths.
- Use event field `.event_type`, not `.type`.
- Use `state.json`, not `run_state.json`.
- Use provider roles `implement`, `review`, `fix`, and `verify_assist`, not
  prose role names.
- Use risk value `medium`, not `mid`.
- Treat source checkout preflight and plan/spec audit preflight as separate
  mechanisms.
- Treat hook enforcement as process-adapter-aware. Per-tool hooks are not
  available until provider event streams are parsed.
- Preserve the existing dirty `skills/waygent/SKILL.md` until Task 11 starts
  with a fresh git status and merges user changes carefully.

## File Structure

- `apps/cli/src/index.ts`: parse new flags and verbs; support repeatable
  values where required.
- `apps/cli/tests/cli.test.ts`: CLI command and flag coverage.
- `packages/contracts/src/types.ts`: add additive state, provider-attempt,
  cost, decision, evidence, model, and hook types.
- `packages/contracts/src/schemas.ts`: validate new additive fields and events.
- `packages/contracts/tests/contracts.test.ts`: contract coverage.
- `packages/orchestrator/src/planPreflight.ts`: deterministic plan/spec audit.
- `packages/orchestrator/src/orchestrator.ts`: call preflight, spec slicing,
  cost, decisions, model attestation, hooks, and budget checks at safe
  boundaries.
- `packages/orchestrator/src/taskExecutor.ts`: carry spec slices, provider
  metadata, method evidence, hook checks, and model/cost data through task
  execution.
- `packages/orchestrator/src/runCommands.ts`: add `decisions`, `cost`,
  `watch`, and `orphans` command helpers plus inspect/explain fields.
- `packages/orchestrator/src/runtimeHooks.ts`: built-in hook evaluation.
- `packages/orchestrator/src/costLedger.ts`: usage and USD accumulation.
- `packages/orchestrator/src/orphanRuns.ts`: stale run/worktree scanner.
- `packages/orchestrator/src/planChain.ts`: repeatable plan/spec chain runner,
  if chain is implemented in this slice.
- `packages/orchestrator/tests/*`: focused runtime tests.
- `packages/context-packer/src/specManifest.ts`: section parsing and task
  slicing.
- `packages/context-packer/src/taskPacket.ts`: include decisions and sliced
  spec context.
- `packages/context-packer/tests/*`: task packet and spec slicing tests.
- `packages/provider-adapters/src/types.ts`: provider usage and actual-model
  metadata shapes.
- `packages/provider-adapters/src/processAdapters.ts`: best-effort extraction
  from provider JSON or event stream output.
- `packages/provider-adapters/tests/*`: provider extraction coverage.
- `packages/lens-projectors/src/failureBarrier.ts`: structured barrier
  projection over existing runtime evidence.
- `packages/lens-projectors/src/index.ts`: export new projection.
- `packages/lens-projectors/tests/*`: projection tests.
- `skills/waygent/references/nl-lexicon.md`: versioned NL lexicon.
- `skills/waygent/evals/check_skill_contract.py`: lexicon contract checks.
- `docs/operations/waygent.md`: operator docs after implementation.
- `docs/contracts/events.md`: new event list after implementation.
- `docs/contracts/run-state.md`: additive state fields after implementation.

## Execution Order

Parallel-safe after Task 1:

- Task 2 decisions, Task 3 spec slicing, Task 8 watch, Task 11 lexicon, and
  Task 12 orphan advisory can be developed independently if file scopes stay
  separate.

Sequential/shared-core:

- Task 1 must happen first because it fixes plan normalization and preflight
  semantics.
- Task 4 cost ledger should land before Task 5 budget-aware failure barriers.
- Task 6 method evidence should land after Task 5 so missing evidence has a
  typed operator barrier.
- Task 7 model attestation should land before cost ledger is treated as exact
  by model.
- Task 9 hooks should land after method evidence and failure barriers.
- Task 10 multi-plan chain should land after cost and spec slicing.

## Task 1: Plan/Spec Preflight And Normalizer Compatibility

**Files:**

- Modify: `packages/orchestrator/src/planNormalizer.ts`
- Create: `packages/orchestrator/src/planPreflight.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `packages/orchestrator/tests/planNormalizer.test.ts`
- Create: `packages/orchestrator/tests/planPreflight.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Extend `TASK_HEADING` to support both `## Task N:` and `### Task N:`.
- Keep source checkout preflight always-on.
- Add `--plan-preflight off|deterministic|full`, defaulting to
  `deterministic` for fake/demo tests and `off` for live provider runs until
  the burn-in is explicitly approved.
- Deterministic preflight fails before run creation when plan/spec structure is
  invalid.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/planPreflight.test.ts apps/cli/tests/cli.test.ts
bun run waygent -- run --provider fake --workspace /tmp/waygent-fixture --root /tmp/waygent-runs --run run_bad_plan --plan bad-plan.md --plan-preflight deterministic
```

Expected:

- `### Task 1:` Superpowers plans normalize.
- Missing file claims or verification commands fail with a deterministic
  preflight error before `<root>/<run_id>/state.json` exists.
- Dirty related source checkout behavior remains unchanged and still produces
  blocked run evidence.

**Risk:** medium. This touches run startup. Keep source preflight and plan
preflight names separate.

**Depends:** none.

## Task 2: Decisions Register

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/orchestrator/src/decisions.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/tests/decisions.test.ts`
- Modify: `packages/context-packer/tests/taskPacket.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Append decisions only after verified task completion.
- Read the decision from `worker.evidence.key_decision`.
- Ignore empty, `(none)`, and `n/a`.
- Render `<run_root>/DECISIONS.md` atomically by writing a temp file and
  renaming it.
- Inject prior decisions into subsequent task packets through the existing
  `decisions` field.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/decisions.test.ts packages/context-packer/tests/taskPacket.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- `waygent decisions --last` returns a JSON payload with decisions for the
  latest run.
- `DECISIONS.md` exists for runs with decisions and contains an explicit empty
  stub for runs with none.
- Task packets after the first verified decision include prior decisions.

**Risk:** low. This is additive evidence.

**Depends:** Task 1 recommended.

## Task 3: Spec Manifest And Task Slicing

**Files:**

- Create: `packages/context-packer/src/specManifest.ts`
- Modify: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/context-packer/tests/specManifest.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorRunV2.test.ts`

**Implementation notes:**

- Parse `##` and `###` markdown headings into deterministic section ids.
- Resolve explicit spec refs from task instructions when present.
- Fallback to full spec when the resolver is empty or confidence is low.
- Store `spec_manifest` on v2 state.
- Emit `runway.spec_slice_computed` with the current `agentlens.event.v3`
  envelope.

**Acceptance:**

```bash
bun test packages/context-packer/tests/specManifest.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
bun run waygent:scenarios
```

Expected:

- A task with explicit spec refs receives only those sections in its
  `task_packet.spec_excerpt`.
- A task without matches receives the full spec and records fallback evidence.
- Event checks use `.events[] | select(.event_type=="runway.spec_slice_computed")`.

**Risk:** medium. Slicing can starve agents of context. Keep full-spec fallback.

**Depends:** Task 1.

## Task 4: Provider Usage Cost Ledger And Budget Cap

**Files:**

- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Create: `packages/orchestrator/src/costLedger.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/provider-adapters/tests/providerUsage.test.ts`
- Create: `packages/orchestrator/tests/costLedger.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Record dispatch count even when token usage is unknown.
- Use zero usage for fake provider.
- Do not infer authoritative spend from prompt length.
- Accumulate cost through parent state mutation after task results return.
- Evaluate budget before safe-wave dispatch and after provider result replay.
- If budget is exceeded, finish recording evidence, set a paused/blocked state,
  and prevent the next unsafe step.

**Acceptance:**

```bash
bun test packages/provider-adapters/tests/providerUsage.test.ts packages/orchestrator/tests/costLedger.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- `waygent cost --last` returns totals, by role, by model, and by task.
- Fake-provider runs show dispatches and zero USD cost.
- A configured pause budget emits `platform.cost_budget_paused` and blocks the
  next wave without losing completed task evidence.

**Risk:** medium. Provider usage formats can drift. Preserve `usage_source`.

**Depends:** Task 1.

## Task 5: Failure Barrier Projection

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/lens-projectors/src/failureBarrier.ts`
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Create: `packages/lens-projectors/tests/failureBarrier.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Do not replace `FailureClass`.
- Add an operator-facing barrier projection for `spec_blocker`,
  `env_blocker`, `ambiguity`, `quality_fail`, `verification_fail`,
  `budget_paused`, `checkpoint_missing`, and `evidence_missing`.
- Surface the barrier in `explain` and `inspect` through the existing operator
  decision response.

**Acceptance:**

```bash
bun test packages/lens-projectors/tests/failureBarrier.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- Verification failures project to `verification_fail`.
- Dirty related source checkout projects to `env_blocker` or the chosen source
  blocker mapping.
- Budget pause projects to `budget_paused`.
- Existing `resume` decisions do not regress.

**Risk:** medium. Projection wording can confuse operators if it contradicts
existing `FailureClass`. Keep raw evidence refs in every barrier.

**Depends:** Task 4 for budget barriers.

## Task 6: Apply Method Evidence Overlay

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/orchestrator/src/evidencePolicy.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/checkpointArtifacts.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/tests/evidencePolicy.test.ts`
- Modify: `packages/orchestrator/tests/applyEngine.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Keep current checkpoint/completion/reconciliation apply gates intact.
- Add opt-in `--require-evidence` or `--require-method-evidence`.
- Runtime verification records satisfy verification evidence.
- Provider TDD and review evidence must come from structured
  `worker.evidence.method_audit`, not parsed prose.
- Waiver reasons are allowlisted.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/evidencePolicy.test.ts packages/orchestrator/tests/applyEngine.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- Existing apply readiness still passes without method evidence when the flag is
  off.
- With the flag on, missing required method evidence blocks apply with
  `lens.evidence_apply_blocked`.
- Allowed waivers unblock docs-only/config-only/generated-only tasks.

**Risk:** high. This changes apply semantics when enabled. Keep it opt-in
until dogfood data proves the policy is practical.

**Depends:** Task 5.

## Task 7: Model Attestation

**Files:**

- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/fakeProvider.ts`
- Modify: `packages/orchestrator/src/executionProfile.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/provider-adapters/tests/modelAttestation.test.ts`
- Create: `packages/orchestrator/tests/modelAttestation.test.ts`

**Implementation notes:**

- Requested model comes from `provider_profile`.
- Actual model is provider-backed when extractable, otherwise `unknown`.
- Fake provider attests `fake`.
- Cost ledger uses actual model when known and records requested fallback when
  unknown.

**Acceptance:**

```bash
bun test packages/provider-adapters/tests/modelAttestation.test.ts packages/orchestrator/tests/modelAttestation.test.ts
bun run waygent:scenarios
```

Expected:

- Fake provider emits `lens.model_attestation_confirmed`.
- A fixture mismatch emits `lens.model_attestation_mismatch`.
- Inspect shows per-task model data without claiming unknown models matched.

**Risk:** low to medium. Attestation is read-only, but provider formats can
drift.

**Depends:** Task 4 preferred.

## Task 8: Watch Verb

**Files:**

- Create: `packages/orchestrator/src/watchRun.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/tests/watchRun.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Read `events.jsonl` incrementally.
- Support `--filter all|task_transition|failure|cost`.
- Support `--json` JSONL output.
- Support `--timeout <duration>` for tests.
- Exit on terminal state or timeout.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/watchRun.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- `waygent watch --last --json --timeout 1s` emits newline-delimited JSON
  events.
- Human-readable mode uses actual event names and risk value `medium`.

**Risk:** low. Read-only.

**Depends:** none.

## Task 9: Runtime Hooks

**Files:**

- Create: `packages/orchestrator/src/runtimeHooks.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/orchestrator/tests/runtimeHooks.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- Implement pre-dispatch and final-output hooks first.
- Add changed-file debug artifact scan before checkpoint sealing.
- Do not claim per-tool hook coverage until provider event streams are parsed
  and tested.
- Use separate `hook_retries` budget.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/runtimeHooks.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- Dangerous verification or provider-output command evidence is denied.
- Debug artifacts in changed files block checkpoint sealing unless allowlisted.
- Missing/invalid worker result shape remains `malformed_result` and also
  records hook evidence when the hook path detects it.

**Risk:** high. Hooks can create false positives. Provide `--hook-config off`
and record bypass evidence.

**Depends:** Task 5 and Task 6.

## Task 10: Multi-Plan Chain

**Files:**

- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/src/planChain.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Create: `packages/orchestrator/tests/planChain.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Implementation notes:**

- First change `parseCli()` so repeatable `--plan` and `--spec` values are not
  overwritten.
- Prefer a chain id over multiple v2 child runs for the first implementation.
- Only introduce `waygent.run_state.v3` if single-file chain state is approved.
- Chain budget and decisions are shared at chain level; child run evidence
  remains v2-compatible.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/planChain.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- Mismatched plan/spec counts fail before any run is created.
- Plan 2 does not start if Plan 1 blocks.
- Cost ledger includes both child runs or both chain indices.
- Existing single-plan `waygent run` behavior is unchanged.

**Risk:** high. This can disturb core run semantics. Keep it after the smaller
operator improvements.

**Depends:** Task 3 and Task 4.

## Task 11: NL Lexicon Versioning

**Files:**

- Create: `skills/waygent/references/nl-lexicon.md`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/README.md`
- Modify: `skills/waygent/evals/check_skill_contract.py`
- Modify: `packages/orchestrator/src/naturalLanguageIntent.ts`
- Modify: `packages/orchestrator/tests/naturalLanguageIntent.test.ts`

**Implementation notes:**

- Start with `git status --short -- skills/waygent` and preserve current user
  changes.
- Keep explicit CLI flags higher priority than NL mappings.
- Store Korean and English mappings in a versioned lexicon.
- The runtime parser may import a generated/static mirror, but the skill docs
  remain the human source.

**Acceptance:**

```bash
cd /Users/kws/source/private/Archive && skills/waygent/evals/run.sh
bun test packages/orchestrator/tests/naturalLanguageIntent.test.ts
```

Expected:

- The eval requires `references/nl-lexicon.md`.
- `SKILL.md` points to the lexicon instead of carrying a long inline mapping
  table.
- Existing Korean intents still pass.

**Risk:** medium because `skills/waygent/SKILL.md` is currently dirty.

**Depends:** none.

## Task 12: Orphan Run Advisory

**Files:**

- Create: `packages/orchestrator/src/orphanRuns.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `packages/orchestrator/tests/orphanRuns.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `docs/operations/waygent.md`

**Implementation notes:**

- Scan actual run roots: `<root>/<run_id>/state.json`,
  `<root>/<run_id>/events.jsonl`, `<root>/<run_id>/artifacts/`.
- Scan worktrees under `<root>/worktrees` unless overridden.
- Never auto-delete.
- Refuse `--delete-all`.
- Delete exactly one validated orphan with `--delete <id> --yes`.

**Acceptance:**

```bash
bun test packages/orchestrator/tests/orphanRuns.test.ts apps/cli/tests/cli.test.ts
bun run waygent:scenarios
```

Expected:

- Startup advisory is non-blocking.
- `waygent orphans` lists stale invalid run dirs.
- `waygent orphans --delete <id> --yes` deletes one validated orphan and
  refuses ambiguous ids.

**Risk:** low if deletion stays explicit and narrow.

**Depends:** none.

## Final Verification

For docs-only updates to this plan:

```bash
git -C /Users/kws/source/private/Archive diff --check -- docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md docs/superpowers/plans/2026-05-22-waygent-runtime-improvements-implementation.md
! rg -n "<waygent>/|packages/runtime/|packages/shared/|select\\(\\.type==|risk=mid|::[^\\n]*::(implementer|reviewer|verifier)" /Users/kws/source/private/Archive/docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md /Users/kws/source/private/Archive/docs/superpowers/plans/2026-05-22-waygent-runtime-improvements-implementation.md | grep -v "rg -n"
```

For implementation:

```bash
cd /Users/kws/source/private/Archive
bun test packages/orchestrator/tests packages/context-packer/tests packages/provider-adapters/tests packages/lens-projectors/tests apps/cli/tests
bun run waygent:scenarios
bun run waygent:dogfood
bun run check
```

Opt-in live provider smoke:

```bash
cd /Users/kws/source/private/Archive
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Live smoke is not part of default verification unless the operator confirms
local CLI auth, time, and cost are acceptable.

## Self-Review Checklist

- [ ] All file paths use the active Archive Waygent repository layout.
- [ ] New events use `agentlens.event.v3` and `.event_type`.
- [ ] Plan/spec preflight is distinct from source checkout preflight.
- [ ] Most fields stay additive to `waygent.run_state.v2`.
- [ ] Multi-plan chain is the only candidate for a schema boundary.
- [ ] Cost ledger does not claim exact USD cost when provider usage is unknown.
- [ ] Method evidence does not weaken current checkpoint/completion/apply gates.
- [ ] Hooks do not promise per-tool coverage before provider event streams are
      parsed.
- [ ] Task 11 preserves existing dirty skill changes.
- [ ] Orphan cleanup never auto-deletes.
