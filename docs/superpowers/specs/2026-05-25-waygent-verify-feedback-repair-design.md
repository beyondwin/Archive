# Waygent — Verify→Worker Feedback + Repair Worker Design

- **Date**: 2026-05-25
- **Type**: Single implementation design (S1 of post-parity hardening trio)
- **Status**: Approved (brainstorming complete)
- **Depends on**: b65f86d (provider parity + role-aware routing D2), cd75ac7 (apply readiness stale reason fix)
- **Followups**: S2 apply granularity, S3 operator hygiene
- **Next artifact**: implementation plan via `superpowers:writing-plans`

## Why This Document

Today's `waygent_provider_parity_codex_claude_streaming_20260525_083920`
run exposed the cost of the existing recovery loop. A worker produced
~700 lines of substantively correct code on the first attempt. Two
small verify failures (one TS18048, one contract idPattern violation)
caused four expensive worker re-dispatches (≈2 hours of provider time,
27M cached read + 313K cached write + 103K output tokens on attempt 1
alone). Each retry regenerated the same broad implementation with new
small bugs. The recovery system has no way to tell a worker "fix this
specific failure on top of your prior diff." Verify→worker feedback is
absent, and `open_ai_repair_handoff` exists as a status label but has
no executable backing.

Additionally, the first attempt produced a verified-by-content diff but
no checkpoint manifest (worker session crashed before checkpoint
emission), so `waygent apply` was structurally blocked and the only
path to land the work was a manual chat-driven diff propagation.

This spec introduces a dedicated **repair worker** that receives the
prior worker's diff as its base, the failed verify evidence as its
task, and a tight scope-lock instruction. Repair attempts use a
separate budget and run on cheaper models by default. Successful
repair generates checkpoint artifacts identical to a first-pass
success, closing the apply-readiness gap.

## Goals

- **G1**. Verify failures with a successful prior worker_result auto-
  dispatch a repair attempt, not a full worker re-spawn.
- **G2**. Repair worker starts from the prior worker's diff (auto-
  applied to a fresh worktree), keeping changes incremental.
- **G3**. Repair worker_result is treated identically to a first-pass
  success for checkpoint generation. No special apply path required.
- **G4**. Operator entry point `waygent repair --run <id>` invokes the
  same code path manually, with optional `--instruction` steering and
  `--evidence` narrowing.
- **G5**. Repair budget is separate from the initial worker
  `max_attempts` (default `max_attempts: 2`). Initial attempt
  exhaustion no longer blocks repair.
- **G6**. Repair role integrates with the D2 role-aware model routing
  shipped in `b65f86d`. Default `repair` slot is `sonnet/medium` for
  cheap scoped fixes; presets override.

## Non-Goals

- Cross-task repair within a multi-task plan. One repair attempt
  targets one task. Cross-task is in scope for S2 (apply granularity).
- Self-edit / worker-rewinds-itself. Repair is always a separate
  dispatch with a separate attempt id.
- Operator hand-editing `worker_result.evidence` payloads through CLI.
- Schema version bump. All additions are optional under
  `evidence.additionalProperties: true` or new optional top-level
  RoleRouting / event fields.
- Repair worker reading other tasks' diffs (cross-task context).
- `error_code` taxonomy / `reason` enumeration — deferred to S3.
- Live progress streaming (D3) — separate spec.

## Architecture Overview

| Surface | Change |
|---|---|
| `packages/orchestrator/src/orchestrator.ts` | Post-`worker_result` git-diff capture; dispatch_repair branch in recovery loop; new worktree base-apply step. |
| `packages/orchestrator/src/recoveryExecutor.ts` | New `dispatch_repair` action with prerequisite check and separate `max_attempts: 2` budget. |
| `packages/orchestrator/src/executionProfile.ts` | `RoleRouting.repair?: AgentProfile`; preset `roles.repair` mappings; resolveRoleSlot extension. |
| `packages/orchestrator/src/runCommands.ts` | New `repairRun(...)` for `waygent repair` CLI. |
| `packages/orchestrator/src/repairPacket.ts` *(new)* | `buildRepairPacket()` composes P2-shape packet from worker_result + verifications + plan slice. |
| `packages/contracts/src/{schemas,types}.ts` | Additive: `worker_result.evidence.patch_ref/patch_sha256/patch_byte_length`; `runway.recovery_action` enum + `dispatch_repair`; event types `runway.repair_dispatched`, `runway.repair_result`; `RoleRouting.repair?`. |
| `packages/lens-projectors/src/{apply.ts,timeline.ts}` | Surface `repair_*` events in timeline + readiness projection treats repair worker_result identically. |
| `apps/cli/src/index.ts` | `waygent repair` command parsing + flag wiring. |
| `apps/cli/tests/` + `packages/orchestrator/tests/` + `tests/integration/` | Coverage for new flow. |

No new top-level packages, no MCP changes, no provider-adapter
changes. Repair worker uses the same `processAdapters.ts`
infrastructure as initial workers (claude/codex/fake), just with role
= `repair`.

## Detailed Design

### 1. Patch Capture

After every `worker_result.status === "completed"`, the orchestrator
runs `git diff main --binary` in the worktree, hashes it, writes the
artifact, and stamps the evidence:

```ts
const patch = execGit(["diff", "main", "--binary"], { cwd: worktree });
if (patch.length > 0) {
  const sha256 = digest(patch);
  const ref = `artifacts/worker/${task_id}/attempt_${attempt}_patch.diff`;
  writeArtifact(paths.root, ref, patch, "text/x-diff");
  worker_result.evidence.patch_ref = ref;
  worker_result.evidence.patch_sha256 = sha256;
  worker_result.evidence.patch_byte_length = patch.byteLength;
}
```

Empty diff → no patch_ref is set, and the result is not eligible for
repair (no base to patch on top of).

Size guard: if `patch.byteLength > 1_048_576` (1 MB), the patch is
still written but `worker_result.evidence.patch_truncated_warning =
true` is set. Repair attempts on oversized patches fall back to
worktree re-use (W1) instead of fresh-worktree-replay (W2). This
covers the rare large-binary-fixture edge case.

The same artifact serves the existing checkpoint manifest pipeline.
`checkpoint.patch_ref` reuses `worker_result.evidence.patch_ref`
verbatim; no double capture.

### 2. Recovery Executor Dispatch

`recoveryExecutor` learns a new action and prerequisite:

```ts
const REPAIR_ACTION = "dispatch_repair" as const;

function chooseRecoveryAction(input: RecoveryInput): RecoveryDecision {
  if (
    input.failure_class === "verification_failed"
    && input.prior_worker_result?.status === "completed"
    && typeof input.prior_worker_result.evidence?.patch_ref === "string"
    && input.prior_worker_result.evidence.patch_ref.length > 0
    && input.repair_budget.current < input.repair_budget.max_attempts
  ) {
    return { action: REPAIR_ACTION, attempt_number: input.repair_budget.current + 1, max_attempts: input.repair_budget.max_attempts };
  }
  // existing branches unchanged
}
```

Repair budget defaults: `{ max_attempts: 2, current: 0 }`. Stored on
state under `state.repair_budget[task_id]`. Exhaustion →
`request_decision` with allowed_actions including `waygent repair`
(operator may still manually invoke; manual invocation does not raise
the cap, it returns `repair_budget_exhausted` instead).

`adapter_crashed`, `timeout`, `malformed_result` failure classes do
not route to repair (no patch to base on). They take the existing
retry path.

### 3. Repair Task Packet (P2 shape)

```ts
interface RepairTaskPacket {
  schema: "runway.repair_task_packet.v1";
  task_id: string;
  attempt_id: string;
  role: "repair";
  prior_diff_ref: string;            // artifact ref already applied to worktree
  prior_worker_summary: string;       // short paragraph from prior worker_result.summary
  failed_verifications: Array<{
    verification_id: string;
    command: string;
    exit_code: number | null;
    timed_out: boolean;
    stdout_excerpt: string;           // ≤16 KB (head 8K + tail 8K + marker if truncated)
    stderr_excerpt: string;           // same cap
  }>;
  passed_verifications: Array<{ verification_id: string; command: string }>;
  operator_instruction?: string;       // present when --instruction passed
  scope_lock_instruction: string;      // fixed boilerplate (see §4)
}
```

Stdout/stderr cap: `excerpt(text, 16384)` returns the full text if
under cap, else `head(8192) + "\n---<truncated>---\n" + tail(8192)`.
Picks both ends so initial error lines and final test summary survive.

Plan/spec full bodies are *not* included. The worker reads source
directly from the worktree (which already has prior_diff applied).
This keeps the packet small and avoids context drift between the
packet copy and the worktree truth.

### 4. Repair Worker Role + System Prompt

New role constant `"repair"` joins `"implement" | "review" |
"verify_assist"` in `WorkerRoleSlot`.

`ExecutionProfile.roles.repair?: AgentProfile`. Preset defaults:
- `max-quality`: `{ model: "opus", reasoning: "high" }`
- `balanced`: `{ model: "sonnet", reasoning: "medium" }`
- `cost-saver`: `{ model: "sonnet", reasoning: "medium" }`

Fallback chain unchanged (`merged.role_models?.repair ??
merged.subagent_model ?? base.roles?.repair?.model ??
base.subagent.model`). Operator overrides via `--role-model
repair=<name>` and `--role-reasoning repair=<level>`.

System prompt (`scope_lock_instruction`):
```
You are the Waygent repair worker.
The worktree already contains a prior worker's diff (see git status).
A subset of verifications failed; their evidence is in the task packet.

Your task:
- Read failed_verifications carefully — especially stdout/stderr excerpts.
- Make the SMALLEST changes needed to make the failed verifications pass.
- Do NOT add new features, refactor unrelated code, or change passing verifications.
- Do NOT revert prior changes unless a specific change directly caused a failure.
- Honor the worktree's task_packet write policy.
- Return runway.worker_result.v1 with status=completed and a short summary describing the fix.
```

### 5. Worktree Base Setup

Per-repair dispatch (W2):
1. Create fresh worktree at `runs/worktrees/<run_id>/task_<task>_repair_<n>/`.
2. `git apply --binary <prior_diff_ref>`. Bail with
   `dispatch_repair_blocked: prior_patch_apply_failed` on conflict
   (should not happen; main hasn't moved).
3. Spawn worker with role=repair using normal `processAdapters.ts`
   flow.
4. After worker exits: capture *new* diff (patch capture step above).
   This is the cumulative diff (prior + repair edits), used for
   checkpoint and any subsequent repair.

Fallback (W1) when `patch_truncated_warning`: skip step 1; re-spawn
into the prior worktree directly.

### 6. CLI Surface

```
waygent repair --run <id>
               [--task <task_id>]
               [--instruction "<note>"]
               [--evidence <verification_id>[,...]]
               [--dry-run]
```

Behavior:
- No flags after `--run`: picks the task with the most recent
  `worker_result.status === "completed"` + `verification_failed`
  combination. Errors `no_repairable_task` if none.
- `--task`: required when ≥2 candidate tasks exist.
- `--instruction`: appended verbatim to packet under
  `operator_instruction`.
- `--evidence`: comma-separated `verification_id`s. Only those appear
  in `failed_verifications`; others move to `passed_verifications`
  (treated as out-of-scope, not failures). Worker is told to focus.
- `--dry-run`: prints the assembled packet as JSON to stdout, emits
  no events, dispatches no worker, does not increment budget.

Return shape:
```json
{ "command": "repair", "run_id": "...", "task_id": "...", "status": "dispatched" | "blocked", "reason"?: "...", "attempt_id"?: "..." }
```

Blocked reasons: `no_repairable_task`, `repair_budget_exhausted`,
`prior_patch_apply_failed`, `dirty_source_checkout` (existing live
check).

### 7. Events

New event types under existing `agentlens.event.v3` schema:

`runway.repair_dispatched`
- phase: `repair`, outcome: `success`
- payload: `{ task_id, attempt_id, attempt_number, max_attempts, role: "repair", prior_diff_ref, evidence_refs: [verification artifact paths] }`

`runway.repair_result`
- phase: `repair`, outcome: `success` | `failed`
- payload: `{ task_id, attempt_id, status: "completed" | "failed" | "blocked", patch_ref?, summary, failure_class? }`

Existing `runway.verification_result` fires for post-repair verify
runs. Existing `runway.recovery_decision_required` fires on budget
exhaustion.

### 8. Apply Readiness

No code change needed. A repaired worker_result with all verifications
passing produces a checkpoint via the existing
`writeCheckpointManifest` path, sourced from
`worker_result.evidence.patch_ref`. `projectApplyReadinessFromState`
sees `state.tasks[task].checkpoint_refs.length > 0` and returns
`ready`.

This closes the gap that forced today's manual diff propagation.

## Schema and Event Changes (Summary)

Additive only — no version bump:

- `runway.worker_result.v1` evidence (additionalProperties:true, no
  schema change needed):
  - `patch_ref?: string`
  - `patch_sha256?: string`
  - `patch_byte_length?: number`
  - `patch_truncated_warning?: boolean`
- `runway.recovery_action` enum extension:
  - `"dispatch_repair"`
- `WorkerRoleSlot` extension:
  - `"repair"` alongside existing slots
- `RoleRouting` interface (TS-only, no JSON schema yet):
  - `repair?: AgentProfile`
- New `agentlens.event.v3` event types:
  - `runway.repair_dispatched`
  - `runway.repair_result`
- `WaygentRunStateV2` extension:
  - `repair_budget?: Record<string, { max_attempts: number; current: number }>` keyed by `task_id`

All existing fixtures and tests remain valid. Adding `patch_ref` to
prior fixtures' `worker_result.evidence` is an additive change.

## Cross-Path Invariants

- A repair attempt always runs against a worktree whose `git diff main`
  starts non-empty (prior diff applied). Empty initial worktree =
  repair never dispatched (prerequisite check fails).
- Checkpoint manifests sourced from repair worker_result reference the
  cumulative diff (prior + repair), never just the repair delta.
- Repair budget is per-task and never resets within a run. Restarting
  the run via `waygent run --run <id>` does not reset because the
  state carries forward.
- `dispatch_repair` action is exclusive with `retry_with_evidence` for
  a given (task, attempt) pair — recovery executor picks one.

## Testing Strategy

**Unit (`packages/orchestrator/tests/`)**
- `recoveryExecutor.test.ts` — new `repairAction.test.ts`: action
  selection matrix across all `failure_class` × `prior_worker_result`
  × `patch_ref present` × `budget remaining` combinations.
- `repairPacket.test.ts` — packet shape with full evidence, with
  excerpts hitting 16KB cap (head+tail+marker), with `--evidence`
  narrowing, with `--instruction` injection.
- `executionProfile.test.ts` — `roleProfileFor(profile, "repair")`
  fallback chain across presets. `--role-model repair=opus` override.
- `patchCapture.test.ts` — diff capture on success, no capture on
  empty diff, oversized patch sets warning flag, sha256 stable.

**Integration (`packages/orchestrator/tests/` + `tests/integration/`)**
- Fixture A — verify-failure-then-repair-success: fake provider
  returns `completed` then `verification_failed` then `completed`;
  expect dispatch_repair event, post-repair verify pass, checkpoint
  created, apply readiness ready.
- Fixture B — no-patch-no-repair: worker_result has empty changed_files
  and no patch_ref; verify fails; expect existing retry path, no
  repair dispatch.
- Fixture C — repair-budget-exhaustion: two repair attempts fail;
  expect `recovery_decision_required` with `waygent repair` listed in
  allowed_actions; manual `waygent repair` returns
  `repair_budget_exhausted`.
- Fixture D — operator-instruction: `waygent repair --instruction
  "check executionProfile.ts line 138"` injects instruction into
  packet; assertion on packet content.
- `tests/integration/waygent-scenarios.test.ts` gains one scenario:
  `repair_to_apply_ready`.

**CLI (`apps/cli/tests/`)**
- `repair.test.ts` — `--dry-run` writes nothing, prints JSON;
  `--evidence v1,v2` parsing; `--task` resolution with 0/1/2+
  candidates; `--instruction` propagation.

**Coverage target**: every new code path has at least one fixture-
driven test. New types compile under existing `tsc -b apps/*
packages/*`.

## Risks and Mitigations

- **R1 — Patch artifact size growth**. Real worker diffs are 10–500 KB
  typically; today's run produced ~50KB. 1MB cap is generous.
  Mitigation set; long-term: store deltas if needed.
- **R2 — Repair worker enters "redo everything" mode**. The
  scope_lock_instruction + small role model default (sonnet/medium)
  + structurally narrow packet (no full plan body) all reduce this.
  Fixture C regression test ensures budget exhaustion fires cleanly
  when repair diverges.
- **R3 — Verify excerpts leak secrets**. tsc and bun test output are
  the typical sources, both safe. Custom verification commands that
  echo env vars are an existing risk surface unchanged by this work.
  Mitigation: documentation note in plan, not new code.
- **R4 — Repair fixes one verify but breaks another (regression)**.
  Always run *full* verify set after repair. Surfaces immediately as
  a new `verification_failed` event, triggering normal recovery.
- **R5 — Repair worker reverts prior good work**. Scope_lock prompt
  + file_claims policy reuse (worker cannot touch files outside
  task's claimed paths). orchestrator enforces this at result
  validation time regardless of role.
- **R6 — D2 role routing breaks**. `roleProfileFor(profile,
  "repair")` is a new slot. Unit test matrix ensures fallback
  semantics match existing slots. Preset defaults reviewed
  individually.
- **R7 — `dispatch_repair` and `retry_with_evidence` both fire for
  one attempt boundary**. Mutually exclusive in `chooseRecoveryAction`;
  unit test enforces exclusivity.

## Plan Shape Estimate

~10–12 waygent-task steps under a single `task_id`. Phase grouping:

1. **Patch capture infrastructure** (2 steps)
   - Orchestrator hook: git diff capture + artifact write.
   - Add `patch_ref` / `patch_sha256` / `patch_byte_length` to
     `worker_result.evidence` plus contract test for additive shape.

2. **Schema + role extensions** (1 step)
   - `WorkerRoleSlot` += `"repair"`; `RoleRouting.repair?`;
     `ExecutionProfile` preset defaults; event type constants;
     `runway.recovery_action` enum entry.

3. **Repair packet builder** (1 step)
   - `repairPacket.ts` with excerpt cap; tests for caps and
     `--evidence`/`--instruction` projection.

4. **Recovery executor mapping** (2 steps)
   - `chooseRecoveryAction` extension; `state.repair_budget`
     plumbing; tests for action selection matrix.

5. **Orchestrator repair dispatch** (2 steps)
   - New worktree path + `git apply` of prior_diff_ref; role=repair
     dispatch via existing `processAdapters`; result handling +
     checkpoint generation reuse.

6. **CLI `waygent repair`** (1 step)
   - Command parser, flag wiring, `--dry-run` mode, return shape.

7. **Events + Lens projection** (1 step)
   - Event emit at dispatch + result; timeline projector update.

8. **Integration fixtures + scenarios** (1–2 steps)
   - Fixtures A/B/C/D; waygent-scenarios.test.ts case.

## Open Questions

- Should `--evidence` allow excluding *all* failed verifications (i.e.,
  empty failed set)? Likely return `no_repairable_task`. Resolved
  during implementation.
- Should checkpoint manifest carry attempt lineage (initial → repair_1
  → repair_2 patch refs separately)? v1 stores only the cumulative
  patch_ref. Multi-attempt lineage can be added later under
  `checkpoint.attempt_chain[]` without schema bump.
- Should `waygent run` accept a `--repair-budget <n>` flag at run
  creation time? Out of scope for v1; default 2 is sufficient per
  data so far.
