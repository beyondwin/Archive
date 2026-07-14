# Waygent Codex Superpowers P4 Production Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the P0-P3 candidate harness is production-ready for the approved personal-local boundary with replay, fault injection, model/method evals, live Codex canaries, and ten real plan dogfood runs.

**Architecture:** A deterministic acceptance evaluator consumes immutable evidence bundles; it never trusts a success summary. Historical local runs are read/redacted outside git, observed failures become committed synthetic fixtures, and live evidence is opt-in but mandatory for the final production verdict. Every candidate remains on a local feature branch and the user performs the merge.

**Tech Stack:** Bun, TypeScript, `bun:test`, Waygent CLI, JSON fixtures, Codex App Server, Git worktrees, Rust fault tests, Console projections.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- `P3_ACCEPTED` must pass before P4.
- Never commit raw files from `~/Library/Application Support/waygent/runs`.
- Historical data is untrusted and redacted before fixture generation.
- Synthetic regression fixtures preserve structure/signatures, not secrets, private paths, or full transcripts.
- Offline GREEN cannot substitute for live Codex startup/model/skill/thread evidence.
- Live success cannot waive deterministic replay, fault, sandbox, method, review, or branch tests.
- Dogfood includes every selected run result; do not omit failures.
- `production_ready` requires every mandatory criterion true.
- No push or protected-branch merge.
- Every helper, fixture, and local constant shown in a test snippet is defined in that named test file and returns the exact contract fields asserted by the task; do not rely on undeclared global test state.

## File Structure

- `packages/testkit/src/historyReplay.ts`: read/redact/project historical stores.
- `packages/testkit/src/faultCampaign.ts`: deterministic kill/lease/corruption/collision campaigns.
- `packages/testkit/src/modelPolicyEval.ts`: model-route and fallback golden evals.
- `packages/testkit/src/productionReadiness.ts`: final criteria evaluator.
- `tests/fixtures/production-regressions/`: synthetic provider/path/retry/security fixtures.
- `tests/fixtures/dogfood/waygent-production-dogfood.json`: exact ten plan/spec cases.
- `docs/operations/production-readiness.md`: operator runbook and evidence interpretation.

## Task Ownership And Risk

| Task | Owner boundary | Risk | Dependency |
| --- | --- | --- | --- |
| 1 | read-only historical replay and redacted report | high | P3 acceptance |
| 2 | committed synthetic regressions through public runtime paths | high | Task 1 |
| 3 | injected real writer/orchestrator and Rust fault campaigns | high | Task 2 |
| 4 | model/method policy plus old-vs-candidate harness comparison | high | Task 3 |
| 5 | guarded improvement loop on a local feature branch | high | Task 4 |
| 6 | live startup canaries and ten completed dogfood plans | high | Task 5 |
| 7 | content-addressed verdict, independent review and runbook | high | Task 6 |

Tasks are sequential because every later verdict consumes sealed evidence from
the prior task. Each commit stages only exact task paths; broad directory or
repository staging is forbidden.

---

### Task 1: Replay And Redact Historical Local Runs

**Files:**

- Create: `packages/testkit/src/historyReplay.ts`
- Modify: `packages/testkit/src/index.ts`
- Create: `packages/testkit/tests/historyReplay.test.ts`
- Create: `apps/cli/tests/productionReplay.test.ts`
- Modify: `apps/cli/src/index.ts`

**Interfaces:**

- Produces: `replayHistoricalRuns`, `HistoricalReplayReport`.
- CLI: `waygent production-replay --root <run-root> --json` is read-only.

- [ ] **Step 1: Write RED replay/privacy tests**

```ts
test("history replay never returns raw provider text or absolute home", async () => {
  const report = await replayHistoricalRuns({ root: privateFixtureRoot });
  const serialized = JSON.stringify(report);
  expect(serialized).not.toContain("sk-waygent-history-marker");
  expect(serialized).not.toContain("/Users/example");
});

test("state-only, unsealed and sealed runs are classified honestly", async () => {
  const report = await replayHistoricalRuns({ root: mixedFixtureRoot });
  expect(report.by_mode).toEqual({
    historical_state_only: 1,
    legacy_unsealed: 1,
    sealed: 1,
    corrupt: 1
  });
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/testkit/tests/historyReplay.test.ts \
  apps/cli/tests/productionReplay.test.ts
```

Expected: replay command/types do not exist.

- [ ] **Step 3: Implement read-only replay**

```ts
export interface HistoricalReplayReport {
  schema: "waygent.historical_replay_report.v1";
  observed_runs: number;
  readable_runs: number;
  by_mode: Record<string, number>;
  integrity_failures: Array<{ run_id_hash: string; reason: string }>;
  projection_equivalent: number;
  secret_findings: number;
}
```

Hash run identifiers in exported reports, redact paths, read via compatibility
APIs, and never repair/write historical files. Against the current machine,
assert `observed_runs >= 147` while recording the actual count.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/testkit/tests/historyReplay.test.ts \
  apps/cli/tests/productionReplay.test.ts
git add -- packages/testkit/src/historyReplay.ts packages/testkit/src/index.ts \
  packages/testkit/tests/historyReplay.test.ts apps/cli/tests/productionReplay.test.ts \
  apps/cli/src/index.ts
git commit -m "feat(testkit): replay historical Waygent runs safely"
```

### Task 2: Promote Observed Failures Into Synthetic Regression Fixtures

**Files:**

- Create: `tests/fixtures/production-regressions/provider-startup-missing.json`
- Create: `tests/fixtures/production-regressions/space-path-java.json`
- Create: `tests/fixtures/production-regressions/unchanged-verification-loop.json`
- Create: `tests/fixtures/production-regressions/artifact-collision.json`
- Create: `tests/fixtures/production-regressions/secret-output.json`
- Create: `tests/integration/waygent-production-regressions.test.ts`

**Interfaces:**

- Consumes: P0/P3 normalized contracts only.
- Produces: deterministic regressions for the actual failure classes found during design research.

- [ ] **Step 1: Author exact redacted fixture records**

Use these required assertions:

```ts
test.each(regressions)("$name", async (fixture) => {
  const result = await runProductionRegression(fixture);
  expect(result.actual_failure_class).toBe(fixture.expected_failure_class);
  expect(result.provider_attempts).toBe(fixture.expected_provider_attempts);
  expect(result.verifications).toBe(fixture.expected_verifications);
  expect(result.duplicate_artifact_refs).toEqual([]);
  expect(result.persisted_secret_findings).toBe(0);
});
```

Provider-startup fixture expects zero attempts/verifications. Space-path fixture
expects success with one argv element containing the space. Unchanged-loop
fixture expects one circuit-open decision and no repeated execution.

- [ ] **Step 2: Run RED**

```bash
bun test tests/integration/waygent-production-regressions.test.ts
```

Expected: fixtures/runner absent or one of the approved invariants fails.

- [ ] **Step 3: Connect fixtures to the real P0-P3 code paths**

Do not create a parallel test-only classifier. Use provider preflight,
CommandObservation, circuit, artifact store, redaction and sealed projectors
through public package exports.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test tests/integration/waygent-production-regressions.test.ts
git add -- tests/fixtures/production-regressions/provider-startup-missing.json \
  tests/fixtures/production-regressions/space-path-java.json \
  tests/fixtures/production-regressions/unchanged-verification-loop.json \
  tests/fixtures/production-regressions/artifact-collision.json \
  tests/fixtures/production-regressions/secret-output.json \
  tests/integration/waygent-production-regressions.test.ts
git commit -m "test(waygent): lock observed production regressions"
```

### Task 3: Run Deterministic Fault Campaigns

**Files:**

- Create: `packages/testkit/src/faultCampaign.ts`
- Create: `packages/testkit/tests/faultCampaign.test.ts`
- Create: `tests/integration/waygent-fault-campaign.test.ts`
- Modify: `packages/lens-store/src/eventJournal.ts`
- Modify: `packages/lens-store/src/writerLease.ts`
- Modify: `packages/lens-store/src/artifactStore.ts`
- Modify: `packages/orchestrator/src/runExecutionContext.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `native/kernel/crates/event-journal/src/lib.rs`
- Create: `native/kernel/crates/event-journal/tests/event_journal.rs`
- Create: `native/kernel/crates/process-supervisor/tests/process_supervisor.rs`

**Interfaces:**

- Produces: `runFaultCampaign(input): FaultCampaignReport`.
- Campaigns: process kill, partial append, projection crash, lease takeover/race, duplicate dispatch, artifact collision.

- [ ] **Step 1: Write RED campaign assertions**

```ts
test("100 seeded failure points preserve one deterministic next action", async () => {
  const report = await runFaultCampaign({ seed: 20260710, iterations: 100 });
  expect(report.journal_corruptions_accepted).toBe(0);
  expect(report.duplicate_dispatches).toBe(0);
  expect(report.artifact_overwrites).toBe(0);
  expect(report.projection_mismatches).toBe(0);
});
```

Rust tests use the same canonical hash and lease fixtures and kill the writer
between append/sync/projection boundaries.

- [ ] **Step 2: Run RED**

```bash
bun test packages/testkit/tests/faultCampaign.test.ts \
  tests/integration/waygent-fault-campaign.test.ts
cargo test --manifest-path native/kernel/Cargo.toml -p event-journal -p process-supervisor
```

Expected: campaign module absent or a fault produces corruption/duplicate action.

- [ ] **Step 3: Implement seeded fault injection**

Add explicit dependency-injected fault hooks at the real TypeScript append,
sync, projection rename, lease CAS, dispatch reservation and artifact exclusive-
create boundaries listed in `Files`; production constructors use sealed no-op
implementations and no environment variable can activate them. The integration
test must call the public orchestrator/store paths and assert every named hook
was reached, preventing a parallel test-only implementation. After each injected
stop, replay the journal, compare projection hash, inspect lease generation, and
calculate the next action twice to prove determinism.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/testkit/tests/faultCampaign.test.ts \
  tests/integration/waygent-fault-campaign.test.ts
cargo test --manifest-path native/kernel/Cargo.toml -p event-journal -p process-supervisor
git add -- packages/testkit/src/faultCampaign.ts packages/testkit/tests/faultCampaign.test.ts \
  tests/integration/waygent-fault-campaign.test.ts packages/lens-store/src/eventJournal.ts \
  packages/lens-store/src/writerLease.ts packages/lens-store/src/artifactStore.ts \
  packages/orchestrator/src/runExecutionContext.ts packages/orchestrator/src/taskExecutor.ts \
  native/kernel/crates/event-journal/src/lib.rs \
  native/kernel/crates/event-journal/tests/event_journal.rs \
  native/kernel/crates/process-supervisor/tests/process_supervisor.rs
git commit -m "test(waygent): survive deterministic runtime faults"
```

### Task 4: Evaluate Model Routing And Superpowers Method Quality

**Files:**

- Create: `packages/testkit/src/modelPolicyEval.ts`
- Create: `packages/testkit/src/methodPolicyEval.ts`
- Create: `packages/testkit/src/harnessBaselineEval.ts`
- Create: `packages/testkit/tests/modelPolicyEval.test.ts`
- Create: `packages/testkit/tests/methodPolicyEval.test.ts`
- Create: `packages/testkit/tests/harnessBaselineEval.test.ts`
- Create: `tests/fixtures/evals/model-policy-v1.json`
- Create: `tests/fixtures/evals/method-policy-v1.json`
- Create: `tests/fixtures/evals/harness-baseline-v1.json`

**Interfaces:**

- Produces: deterministic route/method verdicts plus old-vs-candidate quality/latency evidence on identical cases.
- Enforces: no Luna/ultra, no Terra writes, exact skill chains and artifact gates.

- [ ] **Step 1: Write RED policy eval tests**

```ts
test("approved routes pass and forbidden routes fail", () => {
  const report = evaluateModelPolicy(loadModelPolicyFixture());
  expect(report.mandatory_passed).toBe(report.mandatory_total);
  expect(report.forbidden_routes_accepted).toBe(0);
});

test("method evaluator rejects prompt-only imitation", () => {
  const report = evaluateMethodPolicy(promptImitationFixture);
  expect(report.status).toBe("blocked");
  expect(report.blockers).toContain("skill_injection_missing");
});

test("candidate cannot trade quality for lower latency", () => {
  const report = compareHarnessBaseline(baselineAndCandidateFixture);
  expect(report.case_ids_equal).toBe(true);
  expect(report.quality_regressions).toEqual([]);
  expect(report.latency_delta_ms).toBeNumber();
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/testkit/tests/modelPolicyEval.test.ts \
  packages/testkit/tests/methodPolicyEval.test.ts \
  packages/testkit/tests/harnessBaselineEval.test.ts
```

Expected: eval modules/fixtures absent.

- [ ] **Step 3: Implement evidence-based evals**

Offline routes must exactly match the approved policy. Live comparison runs each
golden case three times when models are available and records acceptance,
review findings, repairs, latency and tokens. A fallback becomes eligible only
when every mandatory deterministic acceptance passes; cost/speed alone never wins.
Compare the pre-P0 baseline harness and candidate on the exact same fixture IDs,
plan/spec hashes and acceptance commands. Record completion, method compliance,
review findings, repair count, merge-readiness, latency and tokens. Any quality
regression blocks P4; latency is reported but cannot compensate for quality.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/testkit/tests/modelPolicyEval.test.ts \
  packages/testkit/tests/methodPolicyEval.test.ts \
  packages/testkit/tests/harnessBaselineEval.test.ts
git add -- packages/testkit/src/modelPolicyEval.ts packages/testkit/src/methodPolicyEval.ts \
  packages/testkit/src/harnessBaselineEval.ts packages/testkit/tests/modelPolicyEval.test.ts \
  packages/testkit/tests/methodPolicyEval.test.ts \
  packages/testkit/tests/harnessBaselineEval.test.ts tests/fixtures/evals/model-policy-v1.json \
  tests/fixtures/evals/method-policy-v1.json tests/fixtures/evals/harness-baseline-v1.json
git commit -m "test(waygent): evaluate model and method policies"
```

### Task 5: Prove The Improvement Loop End To End

**Files:**

- Create: `tests/integration/waygent-improvement-loop.test.ts`
- Create: `tests/fixtures/improvement/provider-startup-cluster.json`
- Modify: `packages/orchestrator/src/improvementCandidates.ts`
- Modify: `packages/orchestrator/src/improvementWorkspace.ts`
- Modify: `packages/lens-projectors/src/improvementCandidates.ts`

**Interfaces:**

- Proves: cluster → exact Superpowers chain → local design/plan branch → replay/canary evidence → merge-ready, never self-merge.

- [ ] **Step 1: Write RED end-to-end test**

```ts
test("improvement candidate remains local and method-complete", async () => {
  const before = snapshotRepositoryRefsAndStatus(sourceCheckout, fakeRemote);
  const result = await runImprovementFixture(providerStartupCluster);
  expect(result.skills).toEqual([
    "brainstorming",
    "writing-plans",
    "test-driven-development",
    "requesting-code-review",
    "verification-before-completion"
  ]);
  expect(snapshotSourceStatusAndProtectedRefs(sourceCheckout, fakeRemote))
    .toEqual(before.source_and_protected);
  expect(result.command_observations.some((item) => item.argv.includes("push")))
    .toBe(false);
  expect(result.status).toBe("merge_ready");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test tests/integration/waygent-improvement-loop.test.ts
```

Expected: P3 prepares a candidate but does not execute/replay/verify the full chain.

- [ ] **Step 3: Implement fixture-driven improvement execution**

Use a separate local branch/worktree and the P1/P2 production path. Store
standing-autonomy basis honestly. Compare baseline/candidate against the
cluster fixture and require independent review plus fresh verification.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test tests/integration/waygent-improvement-loop.test.ts
git add -- tests/integration/waygent-improvement-loop.test.ts \
  tests/fixtures/improvement/provider-startup-cluster.json \
  packages/orchestrator/src/improvementCandidates.ts \
  packages/orchestrator/src/improvementWorkspace.ts \
  packages/lens-projectors/src/improvementCandidates.ts
git commit -m "test(waygent): prove the guarded improvement loop"
```

### Task 6: Run Twenty Startup Canaries And Ten Real Plan Dogfoods

**Files:**

- Create: `tests/fixtures/dogfood/waygent-production-dogfood.json`
- Create: `packages/testkit/src/liveCanary.ts`
- Create: `packages/testkit/src/dogfoodCampaign.ts`
- Create: `packages/testkit/tests/dogfoodCampaign.test.ts`
- Modify: `tests/integration/waygent-live-provider-smoke.test.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `package.json`

**Interfaces:**

- CLI: `waygent live-canary --count 20 --json` and `waygent dogfood-campaign --manifest <path> --json`.
- Produces: immutable campaign reports with every attempt, no success filtering.

- [ ] **Step 1: Add the exact ten-case manifest**

```ts
const casePaths = [
  ["docs/superpowers/plans/2026-07-10-waygent-codex-superpowers-p0-trust-foundation.md", "docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md"],
  ["docs/superpowers/plans/2026-07-10-waygent-codex-superpowers-p1-method-contract.md", "docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md"],
  ["docs/superpowers/plans/2026-07-10-waygent-codex-superpowers-p2-worker-plane.md", "docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md"],
  ["docs/superpowers/plans/2026-07-10-waygent-codex-superpowers-p3-console-improvement.md", "docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md"],
  ["docs/superpowers/plans/2026-06-23-waygent-codex-best-loop.md", "docs/superpowers/specs/2026-06-23-waygent-codex-best-loop-design.md"],
  ["docs/superpowers/plans/2026-05-22-waygent-operational-maturity-loop.md", "docs/superpowers/specs/2026-05-22-waygent-operational-maturity-loop-design.md"],
  ["docs/superpowers/plans/2026-05-24-waygent-full-plan-intake-hardening.md", "docs/superpowers/specs/2026-05-24-waygent-full-plan-intake-hardening-design.md"],
  ["docs/superpowers/plans/2026-05-24-waygent-quality-recovery-context-review.md", "docs/superpowers/specs/2026-05-24-waygent-quality-recovery-context-review-design.md"],
  ["docs/superpowers/plans/2026-05-26-waygent-closure-review-cost-reliability.md", "docs/superpowers/specs/2026-05-26-waygent-closure-review-cost-reliability-design.md"],
  ["docs/superpowers/plans/2026-06-01-waygent-recovery-review-loop.md", "docs/superpowers/specs/2026-06-01-waygent-recovery-review-loop-design.md"]
] as const;

const manifest = materializeDogfoodManifest({
  repository_identity: sha256(normalizeGitRemoteUrl(readOriginUrl())),
  candidate_document_commit: readCleanHead(),
  case_paths: casePaths,
  target_base_for_plan: (planPath) =>
    firstParentOfFirstDocumentCommit(planPath),
  default_expected_noop: false
});
```

`materializeDogfoodManifest` reads plan/spec bytes from the clean candidate
document commit and writes `plan_sha256`/`spec_sha256` into every case. It also
writes the repository identity, a 40-hex target base commit, `expected_noop`,
and `noop_basis`. Each target base must exist and receive a disposable worktree.
If the first-parent algorithm does not produce a meaningful pre-implementation
base, the executor must pin a different reviewed ancestor with evidence; it may
not fall back to current HEAD. `expected_noop=true` is allowed only with a
content-addressed proof that the pinned target base already satisfies the plan.

- [ ] **Step 2: Write campaign RED tests**

Assert manifest paths/hashes, exactly ten cases, every result retained, all
production runs use App Server/skills/model/sandbox evidence, and no case pushes
or merges. A completed no-op still requires method/review/verification evidence.
Assert every plan/spec digest matches bytes at `candidate_document_commit`,
every target base/repository identity is valid, each run uses a new disposable
worktree at that base, and an unapproved no-op is incomplete.

```ts
test("production dogfood requires all ten selected plans to complete", () => {
  const report = evaluateDogfoodCampaign(campaignFixture);
  expect(report.selected).toBe(10);
  expect(report.reported).toBe(10);
  expect(report.completed).toBe(10);
  expect(report.technical_blocks).toBe(0);
  expect(report.status).toBe("passed");
});
```

- [ ] **Step 3: Run deterministic RED/GREEN tests**

```bash
bun test packages/testkit/tests/dogfoodCampaign.test.ts
```

Expected RED before implementation; expected GREEN after campaign/manifest validation.

- [ ] **Step 4: Run live campaigns**

```bash
bun run waygent -- live-canary --count 20 --json
bun run waygent -- dogfood-campaign \
  --manifest tests/fixtures/dogfood/waygent-production-dogfood.json --json
```

Expected: startup canaries 20/20 ready. All ten dogfood runs complete the full
execution lifecycle and produce merge-ready local branches or verified no-op
completion with the same method/review/verification evidence. A technical block
is retained in the campaign report but does not count as completed and blocks
`PRODUCTION_READY`. Any missing/incomplete run, invalid skill/model/sandbox/
review evidence, duplicate ID/artifact, push, or protected mutation fails P4.

- [ ] **Step 5: Commit code and manifest, not private run artifacts**

```bash
git add -- tests/fixtures/dogfood/waygent-production-dogfood.json \
  packages/testkit/src/liveCanary.ts packages/testkit/src/dogfoodCampaign.ts \
  packages/testkit/tests/dogfoodCampaign.test.ts \
  tests/integration/waygent-live-provider-smoke.test.ts apps/cli/src/index.ts package.json
git commit -m "test(waygent): add live and dogfood campaigns"
```

### Task 7: Evaluate And Publish The Production Readiness Report

**Files:**

- Create: `packages/testkit/src/productionReadiness.ts`
- Create: `packages/testkit/tests/productionReadiness.test.ts`
- Modify: `packages/testkit/src/index.ts`
- Modify: `apps/cli/src/index.ts`
- Create: `apps/cli/tests/productionReadiness.test.ts`
- Create: `docs/operations/production-readiness.md`
- Modify: `docs/operations/verification.md`
- Modify: `docs/README.md`
- Modify: `removed-repository-map/REPORT.md`
- Modify: `removed-repository-map/graph.json`

**Interfaces:**

- CLI: `waygent production-readiness --json`.
- Produces: `waygent.production_readiness.v1` report and `PRODUCTION_READY` only when every mandatory criterion passes.

- [ ] **Step 1: Write the mandatory evaluator as RED tests**

```ts
const allGreenBundle = writeReadinessFixtureBundle({
  commit: currentFixtureCommit,
  live_age_minutes: 5,
  dogfood_completed: 10
});

test("one failed mandatory criterion blocks readiness", () => {
  const report = evaluateProductionReadiness(
    tamperCriterion(allGreenBundle, "persisted_raw_secrets_zero")
  );
  expect(report.status).toBe("blocked");
  expect(report.failed).toContain("evidence_digest_mismatch");
});

test("all approved criteria produce readiness", () => {
  const report = evaluateProductionReadiness(allGreenBundle);
  expect(report.status).toBe("production_ready");
  expect(report.failed).toEqual([]);
});

test.each(["missing_ref", "wrong_commit", "stale_live", "forged_count"])(
  "%s evidence cannot manufacture readiness",
  (mutation) => expect(evaluateProductionReadiness(
    mutateReadinessBundle(allGreenBundle, mutation)
  ).status).toBe("blocked")
);
```

Mandatory criteria are exactly: 100% required method evidence; zero invalid
verification after startup/skill failure; zero ungrounded same-fingerprint
repeat; 100% replay/projection equality; zero duplicate dispatch/overwrite after
faults; zero write/protected violations; zero persisted secrets; zero SSE gap/
duplicate; all regression fixtures; no old-vs-candidate quality regression;
20/20 startup canaries; exactly ten selected dogfood cases fully completed;
independent review/fresh whole-run verification
for every merge-ready branch; zero remote push/protected merge.

- [ ] **Step 2: Run RED**

```bash
bun test packages/testkit/tests/productionReadiness.test.ts \
  apps/cli/tests/productionReadiness.test.ts
```

Expected: evaluator and CLI absent.

- [ ] **Step 3: Implement report and operator runbook**

Define a content-addressed `ProductionReadinessEvidenceBundle`: each criterion
contains numerator, denominator and immutable artifact refs with schema, digest,
producer command observation, source commit, Codex binary/protocol/model pins,
produced timestamp and freshness class. The evaluator opens every ref through
the artifact store, verifies digest/schema/commit and recomputes counts from the
referenced records. Deterministic evidence must match the candidate commit; live
startup/model/dogfood evidence must be no older than 24 hours. Missing, stale,
tampered, cross-commit or aggregate-only evidence blocks. The report contains
the bundle root hash, residual risks and blockers without private paths/logs.
The runbook explains rerun commands and makes clear that only the user merges.

- [ ] **Step 4: Verify implementation and create the candidate commit**

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:skill-evals
bun run waygent:console-check
bun run waygent:native-tests
git diff --check
git diff --check
git add -- packages/testkit/src/productionReadiness.ts \
  packages/testkit/tests/productionReadiness.test.ts packages/testkit/src/index.ts \
  apps/cli/src/index.ts apps/cli/tests/productionReadiness.test.ts \
  docs/operations/production-readiness.md docs/operations/verification.md docs/README.md \
  removed-repository-map/REPORT.md removed-repository-map/graph.json
git commit -m "test(waygent): prove production readiness"
```

This commit contains evaluator/runtime/docs/retired repository-map tooling code only. Pre-commit
evidence is diagnostic and cannot satisfy the final current-commit criterion.

- [ ] **Step 5: Independently review and evaluate the clean committed HEAD**

Confirm `git status --porcelain` is empty. Use `requesting-code-review` with Sol
xhigh over the entire feature-branch diff. If review requires a change, make it,
stage only the Task 7 files, commit, and restart Step 5. With an approved clean
HEAD, run:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:skill-evals
bun run waygent:console-check
bun run waygent:native-tests
bun run waygent -- production-readiness --json
git diff --exit-code
git diff --cached --exit-code
```

Expected: readiness is `production_ready` and every artifact ref is bound to
this clean HEAD. Final review/readiness/live evidence stays in the ignored
content-addressed evidence root. Do not create another commit after this run;
doing so makes the evidence stale and requires repeating Step 5.

## Execution Order

- Sequential: Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Kill Switches

```text
WAYGENT_LIVE_CANARY=off|on
WAYGENT_DOGFOOD_CAMPAIGN=off|on
WAYGENT_IMPROVEMENT_LAB=off|read-only|prepare|execute-local
WAYGENT_PRODUCTION_VERDICT=disabled|evaluate
```

- Kill switches disable activity, never rewrite evidence or turn a missing gate green.
- A blocked live campaign keeps the candidate branch and report for diagnosis.
- Production verdict is recomputed from evidence; it is not manually editable.

## Review

Use `code_review.md`. Block P4 for raw historical data in git, selected-success
reporting, nondeterministic fault results, LLM-only quality verdicts, missing
live evidence, unrepresented dogfood failure, secret leakage, readiness criterion
waiver, remote push, or protected-branch mutation.
