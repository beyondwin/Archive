# SP-2: Verify Env Worktree-Awareness

Sub-project of the Waygent Hardening Roadmap
(`docs/superpowers/specs/2026-05-23-waygent-hardening-roadmap.md`).

Goal: make verification accurately reflect worker worktree changes, including
integration tests that import `@waygent/*` packages. Today's verify env
symlinks `node_modules` from the main workspace, which transitively resolves
`@waygent/*` to main's `packages/*`, not the worktree's — so cross-package
worker edits are silently bypassed. SP-2 adds an `isolated_workspace_resolve`
strategy, a content-addressed snapshot cache that amortizes `bun install`
cost across worktrees, and strict-block semantics when isolation is
unavailable.

## 1. Goals and Non-Goals

### 1.1 Goals

- Resolve `@waygent/*` to the worker worktree's `packages/*` whenever a
  verify run depends on cross-package code.
- Keep unit-test-only verify on the existing fast path: no per-task
  `bun install` overhead when isolation is not required.
- Make isolation failures explicit blockers. No silent fall-through to the
  fast path.
- Decide strategy per task using either an explicit plan-task field
  (`verify_isolation`) or, when absent, a deterministic worktree-diff
  analysis.
- Emit evidence rich enough for Lens projections and the future
  `waygent diagnose` (SP-3) and `waygent retry` (SP-4) surfaces.

### 1.2 Non-Goals

- Auto-retry on isolation failure (deliberately excluded — Q3 decision).
- A degrade flag that lets isolation fail through to the fast path
  (deliberately excluded — same).
- `error_code` taxonomy and `waygent diagnose` integration — SP-3 owns.
- `apply --up-to` and per-task retry — SP-4 owns.
- Replacing bun as the workspace tool.

## 2. Decisions Confirmed in Brainstorming

| # | Question | Decision |
|---|---|---|
| Q1 | How is "this verify needs isolation" detected? | **(D)** Explicit plan-task tag + worktree-diff fallback when absent. |
| Q2 | How is the isolated workspace materialized? | **(D)** Single `bun install` path, results cached in a workspace-shared snapshot, materialized into each worktree with `@waygent/*` rewritten to worktree-local paths. |
| Q3 | What happens on isolation failure? | **(A)** Strict block. No auto-retry, no degrade. |

## 3. Architecture

All changes land in `packages/orchestrator`. Module boundaries:

```
taskExecutor.ts
    └─ verificationEnvironment.ts                  (thin: entrypoint + dispatcher)
         ├─ strategyDecider.ts                     (NEW: pure function, plan field + diff → strategy)
         ├─ inheritStrategy.ts                     (NEW: existing symlink logic, extracted)
         └─ isolatedStrategy/
              ├─ index.ts                          (NEW: cache lookup → prepare → verify)
              ├─ snapshot.ts                       (NEW: `.waygent/verify-env-snapshot/<key>/`)
              ├─ workspaceManifest.ts              (NEW: enumerate @waygent/* from packages/*/package.json)
              └─ cacheKey.ts                       (NEW: sha256(bun.lock + package manifests))
```

Rationale:
- `verificationEnvironment.ts` shrinks to a dispatcher. Existing call sites
  in `taskExecutor.ts` keep their signatures (with two new optional inputs).
- `strategyDecider` is pure → easy to unit test without fs/bun.
- `isolatedStrategy/` is a folder so cache, snapshot, and manifest concerns
  remain single-responsibility. SP-1's design contract prefers explicit
  module boundaries over a single growing file.

## 4. Data Model

### 4.1 Plan task field (additive)

```yaml
verify_isolation: "isolated" | "fast" | "auto"   # default: "auto"
```

- `"isolated"` — decider always picks isolated.
- `"fast"` — decider always picks inherit_node_modules. Worker's
  cross-package modifications are *not* auto-escalated — author intent
  overrides detection (see CPI-SP2-3).
- `"auto"` — diff-based decision (Section 5.1).
- Missing field → `"auto"`. Existing plans require no edits.

### 4.2 Evidence schema (additive, `runway.verification_environment`)

```typescript
export type VerificationStrategy =
  | "none"
  | "inherit_node_modules"
  | "isolated_workspace_resolve";

export type IsolationStatus =
  | "not_required"
  | "prepared"
  | "unavailable";

export interface VerificationEnvironmentEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: VerificationStrategy;

  decision: {
    requested: "isolated" | "fast" | "auto";
    resolved: "isolated" | "fast";
    reason: string;
  };

  isolation_status: IsolationStatus;
  isolated_packages: string[];
  resolved_paths: Record<string, string>;
  cache: {
    hit: boolean;
    key: string;
    snapshot_path: string | null;
  } | null;

  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}
```

Existing evidence consumers read only `status`, `strategy`, `cleanup_status` —
no breaking change.

### 4.3 Worker envelope

Workers do not consume verify env decision input directly. The decision is
made by the orchestrator using the worker's worktree diff post-hoc. Workers
populate the SP-1 envelope fields (`policy_ack`, `stale_test_candidates`,
`design_ambiguity_flagged`) per Section 9.

## 5. Flow

```
[1] decide → [2] dispatch → [3a] fast prepare    OR   [3b] isolated prepare
                                                          ├─ [3b.1] cache lookup
                                                          ├─ [3b.2] (miss) bun install in snapshot
                                                          ├─ [3b.3] materialize snapshot to worktree
                                                          └─ [3b.4] manifest verify
                            → [4] runVerificationCommands
                            → [5] cleanup
                            → [6] emit evidence
                            → [7] (on isolated failure) strict block
```

### 5.1 Strategy decision rules (pure function, `strategyDecider.ts`)

```text
input:  task.verify_isolation ∈ {"isolated","fast","auto"}  (default "auto")
        worktreeDiff = git status --porcelain (worker worktree vs base ref)
output: { resolved: "isolated"|"fast", reason: string }

rules:
  - if requested == "isolated" → resolved="isolated", reason="explicit_tag"
  - if requested == "fast"     → resolved="fast",     reason="explicit_tag"
  - if requested == "auto":
      diff_targets = { top-level packages/X seen in worktreeDiff }
      if |diff_targets| == 0          → resolved="fast",     reason="diff_no_package_changes"
      if |diff_targets| == 1          → resolved="fast",     reason="diff_single_package"
      if |diff_targets| >= 2          → resolved="isolated", reason="diff_cross_package"
      if diff touches bun.lock or root package.json
                                       → resolved="isolated", reason="diff_lockfile_touched"
```

### 5.2 Isolated prepare

- **Cache location**: `<workspace>/.waygent/verify-env-snapshot/<cache_key>/`.
  Workspace-shared, not worktree-local — worktrees branched from compatible
  states reuse the same snapshot.
- **`cache_key`** is `sha256` of a canonical input built as follows:
  1. `bun.lock` raw contents (UTF-8 bytes).
  2. For each `packages/*/package.json` sorted lexicographically by path,
     append `<relative_path>\0` then the file's raw UTF-8 bytes then `\0`.
  3. Append root `package.json` re-serialized via
     `JSON.stringify(value, Object.keys(value).sort(), 0)` over only the
     `workspaces` and `dependencies` keys (so unrelated root key changes
     do not invalidate the cache).
  Content-addressed; safe to share across worktrees.
- **On miss**: clone worktree to a tmpdir → `bun install --frozen-lockfile`
  → move resulting `node_modules` to `<snapshot_path>/node_modules` →
  write `<snapshot_path>/manifest.json` listing `@waygent/*` packages.
- **On hit**: proceed directly to materialize.
- **Materialize**: hardlink (`cp -al`) or symlink the snapshot's
  `node_modules` into the worktree. Then *rewrite* `@waygent/*` entries
  inside the worktree's `node_modules` to point to worktree-local
  `packages/*` (not the snapshot's). This is the load-bearing step —
  cache reuses the dependency graph, worktree-local links surface worker
  edits.
- **Manifest verify**: enumerate `@waygent/*` from the worktree's
  `packages/*/package.json`. Compare with the snapshot's manifest. Drift
  (new/removed package) → `isolation_status="unavailable"`,
  `reason="isolation_unavailable.manifest_drift"`. Snapshot is invalidated
  and strict-blocked.

### 5.3 Cleanup

- Remove worktree-local links/hardlinks created during materialize.
- **Snapshot cache is preserved** for reuse by subsequent tasks/runs.
- Cleanup failures are recorded in `cleanup_status="failed"` but do not
  escalate to task failure (matches current behavior for the fast path).

### 5.4 Cache eviction

- LRU on `<snapshot_path>` directory mtime. Default `N=5`. Configurable via
  `WAYGENT_VERIFY_SNAPSHOT_KEEP` env var.
- Eviction runs synchronously *after* the new snapshot is finalized on the
  miss path (so the snapshot just produced is never evicted). On hit paths,
  eviction does not run.

## 6. Error Handling

| `reason` code                         | Stage      | Action       | Cleanup |
|---------------------------------------|------------|--------------|---------|
| `isolation_unavailable.bun_install`   | 5.2 install| strict block | remove partial snapshot |
| `isolation_unavailable.snapshot_io`   | 5.2 fs ops | strict block | remove partial snapshot |
| `isolation_unavailable.materialize`   | materialize| strict block | clean partial worktree links |
| `isolation_unavailable.manifest_drift`| manifest   | strict block | remove snapshot |
| `isolation_unavailable.cache_key_io`  | cache key  | strict block | not needed |
| `decision_input_missing`              | decider    | strict block | not needed |
| `source_node_modules_missing`         | fast       | status=skipped (unchanged) | not needed |

Strict block route: `environmentBlockedVerification(taskId, "isolation_unavailable.<code>")`,
which is the existing API. The new `runway.verification_environment`
event with `outcome="failed"` is emitted in addition to the existing
`runway.verification_result` event with `failure_class="verification_environment_unavailable"`.

Sample failed-isolation event:

```json
{
  "event_type": "runway.verification_environment",
  "outcome": "failed",
  "summary": "Isolated workspace resolve unavailable: bun_install exited 1",
  "payload": {
    "task_id": "task_5",
    "strategy": "isolated_workspace_resolve",
    "isolation_status": "unavailable",
    "decision": { "requested": "auto", "resolved": "isolated", "reason": "diff_cross_package" },
    "failure": {
      "code": "isolation_unavailable.bun_install",
      "exit_code": 1,
      "stderr_tail_sha256": "…",
      "stderr_tail_ref": "artifacts/verification-environment/<run>/<task>/stderr.tail"
    },
    "cache": { "hit": false, "key": "sha256:abcdef…", "snapshot_path": null }
  }
}
```

Stderr is written to an artifact, not embedded in the event payload — the
event carries sha256 and a path ref.

## 7. Testing Strategy

### 7.1 Unit tests (`packages/orchestrator/tests/`)

- `strategyDecider.test.ts` — all seven decision branches.
- `cacheKey.test.ts` — stable hashing, lockfile change → new key,
  package add → new key.
- `workspaceManifest.test.ts` — enumeration, drift detection.
- `inheritStrategy.test.ts` (renamed from existing `verificationEnvironment.test.ts`)
  — regression coverage for the fast path; no behavior change.

### 7.2 Integration tests (`packages/orchestrator/tests/isolatedStrategy.integ.test.ts`)

Gated by `WAYGENT_RUN_INTEG_TESTS=1`. Scenarios:

- A. Cache cold path — first isolated prepare creates snapshot, manifest
  passes, `@waygent-test/foo` resolves to worktree-local path.
- B. Cache hit — second call with identical state → `cache.hit=true`,
  `bun install` not re-invoked.
- C. Manifest drift — add new `packages/baz` after snapshot → next call
  strict-blocks with `manifest_drift`.
- D. `bun install` failure — corrupt lockfile → strict block, event
  payload validated.
- E. Cleanup — after isolated verify, worktree has no leftover links;
  snapshot is preserved.

### 7.3 Reproduction test (`tests/sp2-reproduction/cross-package-edit.test.ts`)

The acceptance gate for SP-2 v1, derived directly from the roadmap's
success criterion for failure mode A. Synthetic clean main; worker
worktree edits two packages so that one imports the other's exported
value. Verify command's output must show the worker's value, not main's.
Without SP-2, this test fails — main's value leaks through. With SP-2,
isolation kicks in (`diff_cross_package`) and the worker's value
surfaces.

### 7.4 Regression coverage

- `bun run check`, `bun run platform:demo`, `bun run waygent:scenarios`
  pass.
- Without `WAYGENT_RUN_INTEG_TESTS=1`, isolated code path is dead — wall
  clock for unit verify within ±10 % of pre-SP-2 baseline.

## 8. Migration and Rollout

### 8.1 Backward compatibility

- Plans without `verify_isolation` work unchanged. Decider's "auto"
  branch favors fast for single-package or zero-package diffs, which is
  the common case.
- Behavior change is limited to tasks where the worker (a) edits two or
  more `packages/*` directories, or (b) touches `bun.lock` or root
  `package.json`, or (c) carries an explicit `verify_isolation:"isolated"`.
  Pre-SP-2, cases (a) and (b) silently verified against main's code. The
  new behavior is the intended fix.

### 8.2 Task sequencing (preview of plan)

```
[T1] inheritStrategy extraction + dispatcher skeleton (zero behavior change)
[T2] strategyDecider + unit tests (all callers forced to "fast")
[T3] isolatedStrategy core: cacheKey, workspaceManifest, snapshot, materialize
     + integration tests (7.2 scenarios A–E)
[T4] dispatcher consumes decider output — auto activated
     + evidence schema extension + event emission
     + plan field parser in design-contract
[T5] sp2-reproduction test (7.3) — acceptance gate
[T6] docs: docs/operations/verification.md + AGENTS.md + skills/waygent/SKILL.md
```

T1–T3 are behavior-neutral. T4 is the first user-visible change. T5 proves
failure mode A is closed.

### 8.3 Kill switches

- `WAYGENT_DISABLE_VERIFICATION_ENV=1` — existing, disables verify env
  entirely.
- `WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1` — new, fine-grained switch.
  Forces every task to fast regardless of `verify_isolation` value. When
  active, fall-through is not a policy violation; evidence records
  `decision.reason="killed_by_env_var"`.

### 8.4 Disk footprint

- `.waygent/verify-env-snapshot/` — verify `.waygent/` is in
  `.gitignore` (plan includes an explicit check task).
- LRU keeps at most `N=5` snapshots per workspace.
- Monitoring delegated to SP-3 telemetry.

### 8.5 Rollback

- T4 is the only behavior-changing commit. Reverting T4 disables `auto`
  escalation and restores pre-SP-2 behavior.
- Evidence schema is additive — Lens consumers do not need to roll back.

### 8.6 Dependencies

- No new external dependencies. `bun` is already required.
- SP-1 design-contract package is already merged. SP-2 spec/plan must pass
  `waygent lint-design` and `waygent lint-plan` (per Section 9.5).
- SP-3 will consume SP-2's `isolation_unavailable.*` `reason` namespace
  when building the `error_code` taxonomy.

## 9. SP-1 Contract Integration

### 9.1 Cross-Path Invariants

```yaml
cross_path_invariants:
  - id: "CPI-SP2-1"
    policy: |
      On isolation_unavailable, no code path falls through to
      inherit_node_modules. Isolation failure is always surfaced as a
      verify failure.
    bound_paths:
      - packages/orchestrator/src/verificationEnvironment.ts
      - packages/orchestrator/src/taskExecutor.ts        # verify phase
      - packages/orchestrator/src/isolatedStrategy/index.ts
    symptom_when_violated: |
      A task whose worker edited cross-package code shows
      verification_result.status="passed" while
      runway.verification_environment.isolation_status != "prepared".

  - id: "CPI-SP2-2"
    policy: |
      strategyDecider's resolved value appears unchanged in both the
      verify env payload and the verification_result payload. Dispatcher
      and event emitter reference the same decision object.
    bound_paths:
      - packages/orchestrator/src/strategyDecider.ts
      - packages/orchestrator/src/verificationEnvironment.ts
      - packages/orchestrator/src/taskExecutor.ts        # event emission
    symptom_when_violated: |
      runway.verification_environment.decision.resolved="isolated" but
      verification_result.strategy="inherit_node_modules".

  - id: "CPI-SP2-3"
    policy: |
      An explicit verify_isolation:"fast" is never auto-escalated. Author
      intent overrides diff-based detection.
    bound_paths:
      - packages/orchestrator/src/strategyDecider.ts
    symptom_when_violated: |
      A task with verify_isolation:"fast" emits
      decision.reason="diff_cross_package" and resolved="isolated".
```

### 9.2 Compatibility Constraints (sample, full list in plan.md)

```yaml
compatibility_constraints:
  - test: packages/orchestrator/tests/inheritStrategy.test.ts
    must_pass: true
    design_sentence: |
      [Section 3] "verificationEnvironment.ts shrinks to a dispatcher.
      Existing call sites keep their signatures." inherit_node_modules
      behavior is unchanged.

  - test: bun run platform:demo
    must_pass: true
    design_sentence: |
      [Section 4.2] "Existing evidence consumers read only status,
      strategy, cleanup_status — no breaking change."
```

### 9.3 Prescriptive vs illustrative code blocks

- Prescriptive (worker must copy verbatim): the
  `VerificationEnvironmentEvidence` type in Section 4.2; the failure
  table in Section 6.
- Illustrative (worker may adapt): Section 5.1 decision pseudocode,
  Section 5.2 cache_key composition (worker may pick `sha256` vs
  `blake3`; the *content* set is prescriptive).

### 9.4 Worker envelope expectations

- `policy_ack` — one line per CPI-SP2-1/2/3 stating where and how the
  worker enforced it.
- `stale_test_candidates` — expected to be empty; inheritStrategy tests
  are preserved by design.
- `design_ambiguity_flagged` — worker should surface anything not
  resolved by this spec. Section 5.2 now defines `cache_key` ordering
  precisely; remaining ambiguities are expected to be empty, but the
  worker must still populate the field (as `[]` if nothing was unclear).

### 9.5 Lint gate

SP-2 spec and plan must pass `waygent lint-design` and `waygent lint-plan`
during spec self-review (checklist item 9).

## 10. Success Criteria

- **Reproduction** (per roadmap) — `tests/sp2-reproduction/cross-package-edit.test.ts`
  passes only with SP-2 active. Without SP-2 (T4 reverted), it fails
  because main's `packages/*` masks the worker's edits.
- **No regression** — `WAYGENT_RUN_INTEG_TESTS` unset, unit verify wall
  clock within ±10 % of pre-SP-2 baseline. `bun run check`,
  `platform:demo`, `waygent:scenarios` pass.
- **Operator surface** — every isolation failure surfaces as
  `runway.verification_environment` with `outcome="failed"` and
  `isolation_status="unavailable"`. Zero instances of a verify_result
  passing with `isolation_status` other than `"prepared"` or
  `"not_required"`.

## 11. Open Questions

- **Hardlink vs symlink for materialize step**. Hardlink is faster to
  resolve but requires the same filesystem; symlink is more portable
  but adds a resolution hop. Decide empirically during T3. The
  decision must be recorded in the spec amendment, not silently in
  code.

## 12. Next Action

Spec self-review (placeholders, internal consistency, scope check,
ambiguity check), then user review, then invoke
`superpowers:writing-plans` skill to author
`docs/superpowers/plans/2026-05-24-waygent-sp2-verify-env.md`.
