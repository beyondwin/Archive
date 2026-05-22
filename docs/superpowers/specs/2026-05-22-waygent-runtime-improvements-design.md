# Waygent Runtime Improvements - Source-Audited Design Spec

Date: 2026-05-22
Status: Source-audited and test-verified revision

This document imports the FixThis draft
`docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md`
into the active Waygent project and rewrites it against the current source in
`/Users/kws/source/private/Archive`.

The imported draft had the right product direction, but several contracts were
out of date for the current Waygent runtime:

- it referenced package roots that do not exist in Archive, including old
  runtime, shared, and CLI package-root variants;
- it used an abbreviated event envelope with `type`, `run_id`, and `ts`, while
  the current contract uses `event_type`, `orchestrator_run_id`,
  `occurred_at`, sequence numbers, producer metadata, outcome, severity, and
  trust impact;
- it treated source checkout preflight, plan/spec audit preflight, and
  provider-output hooks as one mechanism, but the current code already has
  always-on source checkout preflight and process adapters that cannot
  intercept every provider tool call unless an event stream is available;
- it proposed `waygent.run_state.v3` too early. The active code and docs are
  v2-first, so most improvements should stay additive to
  `waygent.run_state.v2`; only multi-plan chaining should consider a schema
  boundary.

## S0. Source Audit Baseline

Re-audit evidence from 2026-05-22:

- `git status --short --branch --untracked-files=all` reported a clean
  checkout on `main...origin/main [ahead 1]`.
- Focused Bun tests passed for CLI parsing/commands, contracts, task packets,
  plan normalization, provider adapter normalization, and provider replay.
- `bun run waygent:scenarios` passed all 7 golden scenario replays.
- A direct probe confirmed `### Task N:` currently falls through as native
  markdown with `task_count: 0`.
- A direct probe confirmed repeated `--plan` and `--spec` flags are currently
  overwritten by the last value in `parseCli()`.

Active source paths:

- `apps/cli/src/index.ts` owns the current CLI command parser and dispatch.
- `packages/orchestrator/src/orchestrator.ts` owns run creation, source
  preflight, safe-wave execution, state mutation, completion audit,
  reconciliation, and final run projection.
- `packages/orchestrator/src/taskExecutor.ts` owns managed task worktrees,
  task packets, provider dispatch, kernel verification, checkpoint creation,
  checkpoint dry-runs, and task-local artifact indexing.
- `packages/orchestrator/src/runCommands.ts` owns `status`, `events`,
  `inspect`, `explain`, `resume`, and `apply`.
- `packages/contracts/src/types.ts` and `packages/contracts/src/schemas.ts`
  own `waygent.run_state.v2`, `agentlens.event.v3`, provider attempts, task
  packets, operator decisions, and projection contracts.
- `packages/context-packer/src/taskPacket.ts` builds `waygent.task_packet.v1`.
- `packages/provider-adapters/src/processAdapters.ts` normalizes Codex and
  Claude process output into `runway.worker_result.v1`.
- `packages/lens-projectors/src/*` owns read-only projections, including apply
  readiness, execution explanation, runtime cost, provider readiness, and
  operator decisions.
- `packages/lens-store/src/paths.ts` defines run storage as
  `<root>/<run_id>/state.json`, `events.jsonl`, `artifacts/`, and
  `projection.sqlite`.
- `skills/waygent/` owns the natural-language skill surface. It currently has
  no local modifications in this audit, but any future edit must still start
  with a fresh status check and preserve unrelated user changes.

Already implemented:

- `agentlens.event.v3` active event contract with product families
  `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.
- `waygent.run_state.v2` as the authoritative runtime state.
- Source checkout preflight that blocks related dirty files and records
  unrelated dirty files as warnings.
- Safe-wave scheduling, bounded concurrency, per-task worktrees, provider
  attempts, kernel verification, checkpoint manifests, checkpoint dry-runs,
  completion audit, reconciliation, and explicit apply.
- CLI verbs: `run`, `demo`, `status`, `events`, `inspect`, `explain`,
  `resume`, `apply`, `intent`, and `scaffold-plan`.
- Superpowers plan normalization for `## Task N:` sections with `- Create:`,
  `- Modify:`, `- Read:`, and `- Append:` file claims.
- Read-only projections for operator decision, execution explanation, runtime
  cost by phase timing, dogfood evidence, provider readiness, and apply
  readiness.

Observed defects and gaps:

- The plan normalizer does not support the Superpowers standard
  `### Task N:` heading shape, even though the writing-plans skill emits that
  form.
- Current plan validation is split between native task parsing and
  Superpowers parse-time normalization. For recognized `## Task N:` sections,
  missing file claims and safe verification commands are already rejected before
  run creation. There is still no dedicated plan/spec audit for `### Task N:`,
  path escape, duplicate ownership, bad spec refs, dependency cycles, or
  invalid command shape as a named preflight phase.
- Task packets already contain a `decisions` array, but no runtime decisions
  register populates it and there is no `waygent decisions` verb.
- Every task receives the full spec text. There is no spec manifest or per-task
  spec slice.
- `runtime_cost` is a duration and parallelism projection. It is not a token
  usage ledger and has no USD budget cap.
- The runtime has a strong `FailureClass` union and `operator_decision`
  projection, but it does not classify agent escalations into structured
  `spec_blocker`, `env_blocker`, or `ambiguity` barriers.
- Apply already gates on checkpoint and completion evidence. The missing layer
  is method-level audit evidence such as TDD, review, and waiver policy.
- `--plan` and `--spec` are not repeatable; repeated flags overwrite previous
  values in the current parser.
- Requested model/reasoning is stored in `provider_profile`, but actual model
  attestation is not extracted from provider output. Codex model flags are not
  injected the way Claude model flags are.
- There is no `watch`, `cost`, `decisions`, or `orphans` verb.
- Hook-style enforcement must account for the current process-adapter boundary:
  pre-dispatch and final-output hooks are available immediately; per-tool hooks
  require provider event stream parsing.
- Natural-language intent parsing is hardcoded in
  `packages/orchestrator/src/naturalLanguageIntent.ts`, not versioned as a
  closed lexicon.

## S1. Correct Event Contract

All new events must use the existing `agentlens.event.v3` envelope:

```ts
type AgentLensEvent = {
  schema: "agentlens.event.v3";
  event_id: string;
  agentlens_run_id: string;
  orchestrator_run_id: string;
  producer: {
    name: string;
    kind: "orchestrator" | "kernel" | "provider" | "lens" | "policy";
    version: string;
  };
  event_type: string;
  occurred_at: string;
  sequence: number;
  phase: string;
  outcome: "success" | "failed" | "blocked" | "cancelled" | "running";
  severity: "debug" | "info" | "warning" | "error";
  trust_impact:
    | "supports_success"
    | "supports_failure"
    | "neutral"
    | "requires_review"
    | "contradicts_success";
  summary: string;
  payload: Record<string, unknown>;
  artifacts?: ArtifactReference[];
};
```

Commands and tests must query `.event_type`, not `.type`. Event JSON returned
by `waygent events` is currently wrapped as `{run_id, total_events, events}`.
Acceptance checks should therefore query `.events[]`.

New event types stay within active families:

| Family | New events |
|---|---|
| `platform.*` | `platform.plan_preflight_completed`, `platform.cost_accumulated`, `platform.cost_budget_warning`, `platform.cost_budget_paused`, `platform.chain_advanced`, `platform.orphan_advisory` |
| `runway.*` | `runway.decision_appended`, `runway.decision_superseded`, `runway.spec_slice_computed`, `runway.spec_slice_fallback_triggered`, `runway.failure_classified` |
| `kernel.*` | `kernel.hook_denied`, `kernel.hook_bypassed` |
| `lens.*` | `lens.model_attestation_confirmed`, `lens.model_attestation_mismatch`, `lens.evidence_validated`, `lens.evidence_apply_blocked`, `lens.evidence_apply_gated` |

The current code uses dotted event names such as `platform.run_started`.
New names should keep the dotted family prefix. The suffix can use underscores
or dots, but a single style must be chosen per event group and tested through
`agentlens.event.v3` schema validation.

## S2. Current Package Boundaries

The implementation must use the current monorepo shape:

| Concern | Current home |
|---|---|
| CLI parsing and command surface | `apps/cli/src/index.ts` |
| Run lifecycle and state mutation | `packages/orchestrator/src/orchestrator.ts` |
| Task execution and provider dispatch | `packages/orchestrator/src/taskExecutor.ts` |
| Run commands | `packages/orchestrator/src/runCommands.ts` |
| State and event contracts | `packages/contracts/src/types.ts`, `packages/contracts/src/schemas.ts` |
| Task packet construction | `packages/context-packer/src/taskPacket.ts` |
| Provider normalization | `packages/provider-adapters/src/*` |
| Read-only projections | `packages/lens-projectors/src/*` |
| Run storage | `packages/lens-store/src/*` |
| Waygent skill | `skills/waygent/*` |

Do not introduce a new runtime package tree for these changes. Use small
focused modules under the existing owner package, for example:

- `packages/orchestrator/src/planPreflight.ts`
- `packages/context-packer/src/specManifest.ts`
- `packages/orchestrator/src/costLedger.ts`
- `packages/orchestrator/src/runtimeHooks.ts`
- `packages/orchestrator/src/orphanRuns.ts`
- `packages/lens-projectors/src/failureBarrier.ts`

## S3. CLI Surface

Existing CLI parsing stores a single value per flag. Before implementing any
repeatable flag, `parseCli()` must preserve repeated values for that flag.

Recommended additions:

| Surface | Behavior |
|---|---|
| `waygent run --plan-preflight off|deterministic|full` | New plan/spec audit. Source checkout preflight remains always-on and separate. |
| `waygent run --spec-slice off|manifest` | Dispatch task packets with per-task spec slices when available. |
| `waygent run --budget-cap <USD> --budget-action warn|pause|off` | Persist run budget and evaluate at safe boundaries. |
| `waygent run --hook-config <path>|off` | Enable built-in final-output hooks plus configured hooks. |
| `waygent run --plan <p1> --spec <s1> --plan <p2> --spec <s2>` | Multi-plan chain, only after repeatable parsing and chain state are implemented. |
| `waygent decisions --run <id>|--last` | Render decisions register. |
| `waygent cost --run <id>|--last` | Render token/cost ledger. |
| `waygent watch --run <id>|--last` | Tail event journal as operator-readable transitions or JSONL. |
| `waygent orphans` | List orphan run/worktree directories; deletion stays explicit per id. |

The CLI entrypoint currently prints JSON for every command. Human-readable
output can be added later, but acceptance tests should not assume text mode
unless the task explicitly implements it.

## S4. Run State Additions

Most fields should be additive to `waygent.run_state.v2`:

```ts
type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
  cached_read_tokens: number;
  cached_write_tokens: number;
};

type DecisionEntry = {
  decision_id: string;
  task_id: string;
  decision: string;
  files: string[];
  made_at: string;
  supersedes: string | null;
};

type SpecManifest = {
  spec_path: string | null;
  spec_total_chars: number;
  sections: Record<string, {
    id: string;
    title: string;
    range: [number, number];
    byte_offset: [number, number];
  }>;
  task_to_sections: Record<string, {
    sections: string[];
    fallback_used: boolean;
    source: "explicit" | "heuristic" | "fallback";
  }>;
  fallback_policy: "full_spec_on_blocker" | "halt_on_blocker";
  built_at: string;
};

type CostLedger = {
  by_task: Record<string, {
    usage: TokenUsage;
    cost_usd: number;
    dispatches: number;
    last_at: string;
    model: string | null;
  }>;
  by_role: Record<string, { usage: TokenUsage; cost_usd: number; dispatches: number }>;
  by_model: Record<string, { usage: TokenUsage; cost_usd: number; dispatches: number }>;
  totals: TokenUsage & { cost_usd: number; dispatches: number };
  price_table_commit: string;
};
```

Recommended v2 additions:

```ts
interface WaygentRunStateV2 {
  decisions_register?: DecisionEntry[];
  spec_manifest?: SpecManifest;
  cost_ledger?: CostLedger;
  budget_cap_usd?: number | null;
  budget_action?: "warn" | "pause" | "off";
}

interface WaygentRunStateTaskV2 {
  evidence_policy?: TaskEvidencePolicy;
  hook_retries?: number;
  model_used?: ModelAttestation[];
}

interface ProviderAttempt {
  requested_model?: { model: string | null; reasoning: string | null };
  actual_model?: { model: string | null; reasoning: string | null; source: string };
  usage?: TokenUsage | null;
  usage_source?: "provider_json" | "event_stream" | "unknown";
}
```

Do not use file-level `flock` for normal cost accumulation unless a future task
introduces direct concurrent child writes. The current parent orchestrator
collects task results and mutates state through `RunExecutionContext`, so
run-state writes can remain serialized in the parent process.

`waygent.run_state.v3` should be reserved for multi-plan chain state if the
chain cannot stay additive. A v3 change must land with v2 read compatibility
tests and explicit `unsupported_run_state` behavior for older consumers.

## S5. Provider Boundary Corrections

Provider output is currently normalized into `runway.worker_result.v1`:

```ts
type WorkerResult = {
  schema: "runway.worker_result.v1";
  task_id: string;
  candidate_id: string;
  status: "completed" | "failed" | "blocked";
  changed_files: string[];
  summary: string;
  evidence: Record<string, unknown>;
  failure_class?: FailureClass;
};
```

The imported draft's prose format with `STATUS:`, `SUMMARY:`, and
`METHOD_AUDIT:` is not the current provider contract. New provider-level data
should be captured as structured JSON in `worker.evidence` or provider process
metadata, then copied into run state and artifacts by Waygent.

Initial model and usage extraction should be best-effort:

- Claude may expose model and usage in JSON wrappers or event streams depending
  on CLI output mode.
- Codex JSONL may expose model and token usage in event envelopes, but the
  current adapter only normalizes the final worker object.
- Fake provider should emit zero usage and actual model `fake`.
- If the provider does not expose usage, record `usage: null`, dispatch count,
  provider, requested model, and `usage_source: "unknown"`; do not infer cost
  from prompt length as authoritative spend.

## S6. Improvement Designs

### F1. Plan/Spec Preflight And Normalizer Compatibility

Separate two preflights:

- source checkout preflight: already implemented and always-on;
- plan/spec preflight: new deterministic/rubric audit before provider
  dispatch.

Deterministic rules:

- support both `## Task N:` and `### Task N:` in Superpowers plans;
- every task has at least one explicit file claim or native
  `waygent-task.file_claims`;
- every task has at least one safe verification command or native
  `waygent-task.verify`;
- file claims stay inside the workspace and do not escape through `..`;
- dependencies reference known task ids and remain acyclic;
- `--spec` path-like inputs must resolve to files.

Rubric rules can be added later through the provider adapter, but deterministic
rules should be the default first slice. Plan/spec preflight should fail before
a run is created. Source checkout preflight may still create a blocked run
because that blocked run is useful evidence.

### F2. Decisions Register

Use the existing task-packet `decisions` field. The runtime appends decisions
from structured `worker.evidence.key_decision` after verified task completion.

Persistence:

- `run_state.decisions_register[]`;
- `<run_root>/DECISIONS.md` projection;
- `waygent decisions --run <id>|--last`;
- task packets receive prior decisions before provider dispatch.

Empty, `(none)`, and `n/a` decisions are ignored. Supersession should be
explicit through `worker.evidence.supersedes`.

### F3. Spec Manifest And Slicing

Build the manifest in `packages/context-packer` and use it when creating task
packets. Dispatch still falls back to the full spec when:

- no spec exists;
- no matching section is found;
- a previous task failure indicates missing context;
- `--spec-slice off` is set.

The event payload must use `event_type: "runway.spec_slice_computed"` and
include `{task_id, sections_used, slice_bytes, fallback_used, fallback_reason}`.

### F4. Token Cost Ledger And Budget Cap

This is distinct from the existing `runtime_cost` duration projection.

Provider dispatch should record:

- requested model and reasoning;
- actual model and reasoning when available;
- token usage when available;
- cost using a repo-local price table;
- dispatch count even when usage is unknown.

Budget evaluation should run at safe parent-process boundaries:

- before dispatching a safe wave;
- after each provider attempt has been merged into parent state;
- before checkpoint and apply gates when a cost cap is configured.

Do not pause in the middle of a provider process. If a cap is exceeded during a
task, finish recording that task's evidence, then pause before the next unsafe
step.

### F5. Failure Barrier Projection

Do not create a second failure system that competes with `FailureClass` and
`waygent.operator_decision.v1`. Add a projection layer that maps runtime
failure evidence to operator-facing barrier types:

```ts
type FailureBarrierType =
  | "spec_blocker"
  | "env_blocker"
  | "ambiguity"
  | "quality_fail"
  | "verification_fail"
  | "budget_paused"
  | "checkpoint_missing"
  | "evidence_missing";
```

The projector should read from:

- `state.tasks[*].latest_failure_class`;
- `state.recovery`;
- `state.apply`;
- `provider_attempts`;
- verification records;
- operator decision blockers;
- cost ledger budget pause state.

`waygent explain` should include the structured barrier inside the existing
operator decision response.

### F6. Apply Method Evidence Overlay

Apply is already blocked unless checkpoint and completion evidence pass. This
feature adds method evidence, not a replacement trust model.

Source of method evidence:

- runtime-owned verification records are authoritative for verification;
- provider-owned TDD/review audit is advisory unless validated by files and
  commands;
- waivers must be explicit and allowlisted.

Policy should be additive:

- default off at first release;
- `--require-method-evidence` or `--require-evidence` blocks apply when enabled;
- missing method evidence emits `lens.evidence_apply_blocked`;
- successful validation emits `lens.evidence_apply_gated`.

### F7. Model Attestation

Attestation compares requested and actual provider model:

- requested comes from `provider_profile` and provider process options;
- actual comes from provider JSON or event stream;
- unavailable actual model is recorded as `unknown`, not as a match.

Codex and Claude adapters need separate extractors. Fake provider returns a
confirmed `fake` attestation. Cost ledger must use actual model when known and
fall back to requested model only with `source: "requested_fallback"`.

### F8. Watch

`waygent watch` should read the JSONL event journal and print one event per
line. It is read-only and must not mutate run state.

Terminal handling should account for current events, not a non-existent
`run.completed` event. The first version can exit when state reads as
`completed`, `blocked`, `failed`, or `applied`, or when a `--timeout` expires.

### F9. Runtime Hooks

The current process adapters cannot reliably intercept every internal Codex or
Claude tool call. Therefore hooks ship in tiers:

1. pre-dispatch hooks over task packet, file claims, command policy, and prompt;
2. final-output hooks over normalized worker result and raw stdout/stderr;
3. event-stream tool-call hooks only after provider event stream parsing exists.

Built-ins:

- dangerous command scan over task packet commands and provider stdout/stderr;
- debug artifact scan over changed files before checkpoint sealing;
- structured worker-result validation over `runway.worker_result.v1`.

Hook denials use a separate `hook_retries` budget and emit `kernel.hook_denied`.

### F10. Multi-Plan Chain

This is the only feature that may justify a schema boundary. Before adding
`waygent.run_state.v3`, implement repeatable flag parsing and evaluate whether
a chain can be represented as a run group over multiple v2 runs.

Preferred first design:

- `waygent run-chain` or repeatable `waygent run --plan ... --plan ...`;
- one chain id;
- one event journal for chain-level events;
- one v2 child run per plan;
- shared cost ledger at chain level.

If the product needs one state file with `plan_chain[]`, introduce
`waygent.run_state.v3` with migration and read-compatibility tests.

### F11. NL Lexicon Versioning

Move natural-language mappings out of hardcoded regex/prose into a versioned
lexicon:

- `skills/waygent/references/nl-lexicon.md`;
- optional runtime mirror in `packages/orchestrator/src/nlLexicon.ts` or JSON;
- eval coverage in `skills/waygent/evals/check_skill_contract.py`;
- explicit-wins-over-NL rules.

`skills/waygent/SKILL.md` was clean in the 2026-05-22 audit. Task 11 must
still start with `git status --short -- skills/waygent` because skill files are
operator-facing contracts and may receive user edits between audits.

### F12. Orphan Run Advisory

Use actual run storage:

- run roots live under `defaultRunRoot()` unless `--root` is supplied;
- each run root should contain `state.json`, `events.jsonl`, and `artifacts/`;
- worktrees live under `<root>/worktrees` unless overridden.

Advisory scan should report:

- stale run dirs without valid `state.json`;
- stale worktrees with missing corresponding run state;
- duplicate run roots that cannot be resumed.

Never auto-delete. `waygent orphans --delete <id> --yes` should delete exactly
one resolved orphan after validation.

## S7. Testing Strategy

Every implementation slice should include:

- contract tests in `packages/contracts/tests`;
- focused orchestrator tests in `packages/orchestrator/tests`;
- CLI tests in `apps/cli/tests/cli.test.ts` for every new flag or verb;
- scenario replay updates under `tests/waygent-scenarios` only when the event
  sequence intentionally changes;
- `bun run waygent:scenarios` for runtime replay;
- `bun run waygent:dogfood` when run evidence or maturity projection changes;
- `bun run check` before shipping code changes.

Docs-only verification for this imported document is:

```bash
git -C /Users/kws/source/private/Archive diff --check -- docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md docs/superpowers/plans/2026-05-22-waygent-runtime-improvements-implementation.md
! rg -n "<waygent>/|packages/runtime/|packages/shared/|select\\(\\.type==|risk=mid|::[^\\n]*::(implementer|reviewer|verifier)" /Users/kws/source/private/Archive/docs/superpowers/specs/2026-05-22-waygent-runtime-improvements-design.md /Users/kws/source/private/Archive/docs/superpowers/plans/2026-05-22-waygent-runtime-improvements-implementation.md | grep -v "rg -n"
```

The second command should print nothing after the self-filter.

## S8. Open Questions

1. Should the public flag be `--preflight` or `--plan-preflight` now that source
   checkout preflight already exists? Recommendation: `--plan-preflight` to
   avoid semantic overlap.
2. Should multi-plan chaining be one v3 state file or a chain id coordinating
   multiple v2 child runs? Recommendation: chain id plus v2 child runs first;
   v3 only if the UX needs single-file chain state.
3. Which provider outputs expose actual token usage reliably enough for cost
   accounting? Recommendation: implement extractors with `unknown` fallback and
   treat budget math as exact only when `usage_source` is provider-backed.
4. Should method evidence be required by default? Recommendation: no. Start
   opt-in because the runtime currently validates verification and checkpoint
   evidence, but not TDD method discipline.
5. Which provider event streams are stable enough for tool-call hooks?
   Recommendation: start with pre-dispatch and final-output hooks, then add
   event-stream hooks after adapter tests prove the stream shape.

## S9. References

- Plan: `docs/superpowers/plans/2026-05-22-waygent-runtime-improvements-implementation.md`
- Current runtime source: `packages/orchestrator/src/orchestrator.ts`
- Current CLI source: `apps/cli/src/index.ts`
- Current contracts: `packages/contracts/src/types.ts`,
  `packages/contracts/src/schemas.ts`
- Current run storage: `packages/lens-store/src/paths.ts`
- Current provider adapters: `packages/provider-adapters/src/processAdapters.ts`
- Current operations doc: `docs/operations/waygent.md`
