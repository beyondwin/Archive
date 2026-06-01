# Waygent vs KWS Codex Plan Executor Comparison Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a neutral benchmark harness that compares Waygent and `kws-codex-plan-executor` on quality, time, cost, and recovery evidence without making either executor depend on the other.

**Architecture:** Keep comparison logic in `packages/testkit` and expose it through a root package script. The first slice is fixture-driven and dry-run safe; live provider execution is opt-in through an explicit environment variable. Reports are generated under an ignored benchmark report directory.

**Tech Stack:** TypeScript, Bun test, `@waygent/testkit`, Waygent run artifacts, CPE state artifacts, filesystem JSON/Markdown reports.

---

## Source Spec

- Design spec: `docs/superpowers/specs/2026-06-01-waygent-cpe-comparison-benchmark-design.md`
- Existing evidence:
  - `skills/waygent/evals/run.sh`
  - `bun run waygent:scenarios`
  - `skills/kws-codex-plan-executor/evals/run.sh`
  - `docs/2026-05-22-waygent-vs-cme-fixture-lab-analysis.md`

## File Structure Map

- Create `packages/testkit/src/executorComparison.ts`
  - Owns shared result types, quality scoring, and normalizers for Waygent and
    CPE-like artifacts.
- Create `packages/testkit/src/executorComparisonCli.ts`
  - Parses benchmark arguments, supports dry-run, blocks live mode unless
    `WAYGENT_CPE_BENCH_ALLOW_LIVE=1`, writes JSON and Markdown reports.
- Modify `packages/testkit/src/index.ts`
  - Exports comparison helpers.
- Create `packages/testkit/tests/executorComparison.test.ts`
  - Tests scoring, cost unknown handling, live-mode guard, and report shape.
- Modify `package.json`
  - Adds `executor:compare`.
- Modify `.gitignore`
  - Ignores generated `reports/` output.
- Create `docs/benchmarks/waygent-cpe/README.md`
  - Documents how to run the dry-run, offline, and live comparison modes.

## Task 1: Add Pure Comparison Types and Scoring

```yaml waygent-task
id: task_1_executor_comparison_scoring
title: Add pure comparison types and scoring
dependencies: []
file_claims:
  - path: packages/testkit/src/executorComparison.ts
    mode: owned
  - path: packages/testkit/src/index.ts
    mode: owned
  - path: packages/testkit/tests/executorComparison.test.ts
    mode: owned
risk: low
verify:
  - bun test packages/testkit/tests/executorComparison.test.ts
```

**Files:**
- Create: `packages/testkit/src/executorComparison.ts`
- Modify: `packages/testkit/src/index.ts`
- Create: `packages/testkit/tests/executorComparison.test.ts`

- [ ] **Step 1: Write failing tests for quality scoring**

Create `packages/testkit/tests/executorComparison.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  scoreExecutorTrial,
  summarizeExecutorComparison,
  type ExecutorTrialResult
} from "../src/executorComparison";

function trial(overrides: Partial<ExecutorTrialResult> = {}): ExecutorTrialResult {
  return {
    schema: "waygent.executor_comparison.trial.v1",
    executor: "waygent",
    scenario_id: "simple-doc-change",
    repetition: 1,
    command: ["bun", "run", "waygent", "--", "run", "--plan", "plan.md"],
    started_at: "2026-06-01T00:00:00.000Z",
    completed_at: "2026-06-01T00:00:10.000Z",
    duration_ms: 10_000,
    outcome: "passed",
    quality: {
      score: 0,
      verification_passed: true,
      review_passed: null,
      apply_ready: true,
      out_of_scope_changes: [],
      residual_risks: []
    },
    cost: {
      cost_usd: 1.25,
      input_tokens: 1000,
      output_tokens: 200,
      cached_read_tokens: 0,
      cached_write_tokens: 0,
      dispatches: 1,
      source: "provider_usage"
    },
    recovery: {
      retries: 0,
      recovered_failures: [],
      final_blocker: null
    },
    artifact_refs: ["state.json", "events.jsonl"],
    ...overrides
  };
}

describe("executor comparison scoring", () => {
  test("awards a full score for verified clean apply-ready output", () => {
    expect(scoreExecutorTrial(trial())).toBe(100);
  });

  test("penalizes failed verification, blockers, missing artifacts, and out-of-scope changes", () => {
    expect(scoreExecutorTrial(trial({
      outcome: "blocked",
      quality: {
        score: 0,
        verification_passed: false,
        review_passed: false,
        apply_ready: false,
        out_of_scope_changes: ["unrelated.txt"],
        residual_risks: ["review_evidence_missing"]
      },
      recovery: {
        retries: 2,
        recovered_failures: ["malformed_result"],
        final_blocker: "review_evidence_missing"
      },
      artifact_refs: []
    }))).toBe(0);
  });

  test("summarizes winners without treating unknown cost as zero", () => {
    const waygent = trial({ executor: "waygent", cost: { ...trial().cost, cost_usd: null, source: "unknown" } });
    const cpe = trial({ executor: "kws-codex-plan-executor", duration_ms: 12_000 });
    const summary = summarizeExecutorComparison([waygent, cpe]);
    expect(summary.by_executor.waygent.trials).toBe(1);
    expect(summary.by_executor["kws-codex-plan-executor"].trials).toBe(1);
    expect(summary.by_executor.waygent.cost_usd_known).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `bun test packages/testkit/tests/executorComparison.test.ts`

Expected: FAIL because `executorComparison.ts` does not exist.

- [ ] **Step 3: Implement pure scoring and summary**

Create `packages/testkit/src/executorComparison.ts`:

```ts
export type ComparedExecutor = "waygent" | "kws-codex-plan-executor";
export type ExecutorTrialOutcome = "passed" | "failed" | "blocked" | "inconclusive";
export type ExecutorCostSource = "provider_usage" | "state_estimate" | "unknown";

export interface ExecutorTrialResult {
  schema: "waygent.executor_comparison.trial.v1";
  executor: ComparedExecutor;
  scenario_id: string;
  repetition: number;
  command: string[];
  started_at: string;
  completed_at: string;
  duration_ms: number;
  outcome: ExecutorTrialOutcome;
  quality: {
    score: number;
    verification_passed: boolean;
    review_passed: boolean | null;
    apply_ready: boolean | null;
    out_of_scope_changes: string[];
    residual_risks: string[];
  };
  cost: {
    cost_usd: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    cached_read_tokens: number | null;
    cached_write_tokens: number | null;
    dispatches: number | null;
    source: ExecutorCostSource;
  };
  recovery: {
    retries: number;
    recovered_failures: string[];
    final_blocker: string | null;
  };
  artifact_refs: string[];
}

export interface ExecutorComparisonSummary {
  schema: "waygent.executor_comparison.summary.v1";
  scenario_id: string;
  trials: number;
  by_executor: Record<ComparedExecutor, {
    trials: number;
    average_quality_score: number;
    average_duration_ms: number;
    cost_usd_known: boolean;
    total_cost_usd: number | null;
    passed: number;
    blocked: number;
    failed: number;
    inconclusive: number;
  }>;
}

export function scoreExecutorTrial(trial: ExecutorTrialResult): number {
  let score = 0;
  if (trial.quality.verification_passed) score += 30;
  if (trial.quality.review_passed !== false) score += 20;
  if (trial.quality.apply_ready === true || trial.outcome === "passed") score += 20;
  if (trial.quality.out_of_scope_changes.length === 0) score += 15;
  if (!trial.recovery.final_blocker) score += 10;
  if (trial.artifact_refs.length > 0) score += 5;
  return score;
}

export function summarizeExecutorComparison(trials: ExecutorTrialResult[]): ExecutorComparisonSummary {
  const scenarioId = trials[0]?.scenario_id ?? "unknown";
  return {
    schema: "waygent.executor_comparison.summary.v1",
    scenario_id: scenarioId,
    trials: trials.length,
    by_executor: {
      waygent: summarizeExecutor(trials, "waygent"),
      "kws-codex-plan-executor": summarizeExecutor(trials, "kws-codex-plan-executor")
    }
  };
}

function summarizeExecutor(trials: ExecutorTrialResult[], executor: ComparedExecutor) {
  const selected = trials.filter((trial) => trial.executor === executor);
  const knownCosts = selected.filter((trial) => trial.cost.cost_usd !== null);
  return {
    trials: selected.length,
    average_quality_score: average(selected.map((trial) => trial.quality.score || scoreExecutorTrial(trial))),
    average_duration_ms: average(selected.map((trial) => trial.duration_ms)),
    cost_usd_known: knownCosts.length === selected.length && selected.length > 0,
    total_cost_usd: knownCosts.length === selected.length
      ? knownCosts.reduce((sum, trial) => sum + (trial.cost.cost_usd ?? 0), 0)
      : null,
    passed: selected.filter((trial) => trial.outcome === "passed").length,
    blocked: selected.filter((trial) => trial.outcome === "blocked").length,
    failed: selected.filter((trial) => trial.outcome === "failed").length,
    inconclusive: selected.filter((trial) => trial.outcome === "inconclusive").length
  };
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}
```

Modify `packages/testkit/src/index.ts`:

Append this export to `packages/testkit/src/index.ts` without removing the
existing exports:

```ts
export * from "./executorComparison";
```

- [ ] **Step 4: Run the test and confirm pass**

Run: `bun test packages/testkit/tests/executorComparison.test.ts`

Expected: PASS.

## Task 2: Normalize Existing Waygent and CPE Artifacts

```yaml waygent-task
id: task_2_executor_artifact_normalizers
title: Normalize existing Waygent and CPE artifacts
dependencies: [task_1_executor_comparison_scoring]
file_claims:
  - path: packages/testkit/src/executorComparison.ts
    mode: owned
  - path: packages/testkit/tests/executorComparison.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/testkit/tests/executorComparison.test.ts
```

**Files:**
- Modify: `packages/testkit/src/executorComparison.ts`
- Modify: `packages/testkit/tests/executorComparison.test.ts`

- [ ] **Step 1: Add failing tests for artifact normalization**

Append tests to `packages/testkit/tests/executorComparison.test.ts`:

```ts
import {
  normalizeCpeStateArtifact,
  normalizeWaygentInspectArtifact
} from "../src/executorComparison";

test("normalizes Waygent inspect and cost artifacts", () => {
  const result = normalizeWaygentInspectArtifact({
    scenario_id: "simple-doc-change",
    repetition: 1,
    command: ["bun", "run", "waygent", "--", "inspect", "--run", "run_a"],
    started_at: "2026-06-01T00:00:00.000Z",
    completed_at: "2026-06-01T00:00:10.000Z",
    inspect: {
      run_id: "run_a",
      status: "completed",
      state: {
        apply_readiness: { status: "ready" },
        cost_ledger: {
          totals: {
            cost_usd: 2.5,
            input_tokens: 100,
            output_tokens: 20,
            cached_read_tokens: 10,
            cached_write_tokens: 0,
            dispatches: 2
          }
        }
      },
      operator_decision: {
        primary_blocker: null
      }
    },
    artifact_refs: ["run-state.json", "events.jsonl"]
  });

  expect(result.executor).toBe("waygent");
  expect(result.outcome).toBe("passed");
  expect(result.cost.cost_usd).toBe(2.5);
  expect(result.quality.score).toBe(100);
});

test("normalizes CPE state artifacts with unknown cost preserved", () => {
  const result = normalizeCpeStateArtifact({
    scenario_id: "simple-doc-change",
    repetition: 1,
    command: ["kws-codex-plan-executor", "plan=plan.md"],
    started_at: "2026-06-01T00:00:00.000Z",
    completed_at: "2026-06-01T00:00:20.000Z",
    state: {
      lifecycle_outcome: "finished",
      completion_audit: {
        passed: true,
        verification_evidence: [{ status: "passed" }]
      },
      tasks: {
        task_a: {
          status: "completed",
          subagent_strategy: { mode: "local_fallback", reason: "fixture" }
        }
      }
    },
    artifact_refs: ["state.json", "context.json"]
  });

  expect(result.executor).toBe("kws-codex-plan-executor");
  expect(result.outcome).toBe("passed");
  expect(result.cost.source).toBe("unknown");
  expect(result.cost.cost_usd).toBeNull();
  expect(result.quality.verification_passed).toBe(true);
});
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `bun test packages/testkit/tests/executorComparison.test.ts`

Expected: FAIL because normalizer functions do not exist.

- [ ] **Step 3: Implement defensive normalizers**

Add to `packages/testkit/src/executorComparison.ts`:

```ts
interface WaygentInspectInput {
  scenario_id: string;
  repetition: number;
  command: string[];
  started_at: string;
  completed_at: string;
  inspect: Record<string, unknown>;
  artifact_refs: string[];
}

interface CpeStateInput {
  scenario_id: string;
  repetition: number;
  command: string[];
  started_at: string;
  completed_at: string;
  state: Record<string, unknown>;
  artifact_refs: string[];
}

export function normalizeWaygentInspectArtifact(input: WaygentInspectInput): ExecutorTrialResult {
  const state = record(input.inspect.state);
  const applyReadiness = record(state.apply_readiness);
  const costLedger = record(state.cost_ledger);
  const totals = record(costLedger.totals);
  const operatorDecision = record(input.inspect.operator_decision);
  const primaryBlocker = record(operatorDecision.primary_blocker);
  const outcome = primaryBlocker.code ? "blocked" : String(input.inspect.status) === "failed" ? "failed" : "passed";
  const trial: ExecutorTrialResult = {
    schema: "waygent.executor_comparison.trial.v1",
    executor: "waygent",
    scenario_id: input.scenario_id,
    repetition: input.repetition,
    command: input.command,
    started_at: input.started_at,
    completed_at: input.completed_at,
    duration_ms: durationMs(input.started_at, input.completed_at),
    outcome,
    quality: {
      score: 0,
      verification_passed: outcome === "passed",
      review_passed: null,
      apply_ready: applyReadiness.status === "ready",
      out_of_scope_changes: [],
      residual_risks: primaryBlocker.code ? [String(primaryBlocker.code)] : []
    },
    cost: {
      cost_usd: numberOrNull(totals.cost_usd),
      input_tokens: numberOrNull(totals.input_tokens),
      output_tokens: numberOrNull(totals.output_tokens),
      cached_read_tokens: numberOrNull(totals.cached_read_tokens),
      cached_write_tokens: numberOrNull(totals.cached_write_tokens),
      dispatches: numberOrNull(totals.dispatches),
      source: totals.cost_usd === undefined ? "unknown" : "provider_usage"
    },
    recovery: {
      retries: 0,
      recovered_failures: [],
      final_blocker: primaryBlocker.code ? String(primaryBlocker.code) : null
    },
    artifact_refs: input.artifact_refs
  };
  trial.quality.score = scoreExecutorTrial(trial);
  return trial;
}

export function normalizeCpeStateArtifact(input: CpeStateInput): ExecutorTrialResult {
  const audit = record(input.state.completion_audit);
  const verificationEvidence = Array.isArray(audit.verification_evidence) ? audit.verification_evidence : [];
  const passed = input.state.lifecycle_outcome === "finished" && audit.passed === true;
  const blocker = passed ? null : String(input.state.handoff_reason ?? "cpe_not_finished");
  const trial: ExecutorTrialResult = {
    schema: "waygent.executor_comparison.trial.v1",
    executor: "kws-codex-plan-executor",
    scenario_id: input.scenario_id,
    repetition: input.repetition,
    command: input.command,
    started_at: input.started_at,
    completed_at: input.completed_at,
    duration_ms: durationMs(input.started_at, input.completed_at),
    outcome: passed ? "passed" : "blocked",
    quality: {
      score: 0,
      verification_passed: verificationEvidence.some((item) => record(item).status === "passed"),
      review_passed: null,
      apply_ready: null,
      out_of_scope_changes: [],
      residual_risks: blocker ? [blocker] : []
    },
    cost: {
      cost_usd: null,
      input_tokens: null,
      output_tokens: null,
      cached_read_tokens: null,
      cached_write_tokens: null,
      dispatches: null,
      source: "unknown"
    },
    recovery: {
      retries: 0,
      recovered_failures: [],
      final_blocker: blocker
    },
    artifact_refs: input.artifact_refs
  };
  trial.quality.score = scoreExecutorTrial(trial);
  return trial;
}

function durationMs(startedAt: string, completedAt: string): number {
  return Math.max(0, Date.parse(completedAt) - Date.parse(startedAt));
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
```

- [ ] **Step 4: Run the test and confirm pass**

Run: `bun test packages/testkit/tests/executorComparison.test.ts`

Expected: PASS.

## Task 3: Add Dry-Run CLI and Report Writer

```yaml waygent-task
id: task_3_executor_comparison_cli
title: Add dry-run CLI and report writer
dependencies: [task_2_executor_artifact_normalizers]
file_claims:
  - path: packages/testkit/src/executorComparisonCli.ts
    mode: owned
  - path: packages/testkit/tests/executorComparison.test.ts
    mode: owned
  - path: package.json
    mode: owned
  - path: .gitignore
    mode: owned
risk: medium
verify:
  - bun test packages/testkit/tests/executorComparison.test.ts
```

**Files:**
- Create: `packages/testkit/src/executorComparisonCli.ts`
- Modify: `packages/testkit/tests/executorComparison.test.ts`
- Modify: `package.json`
- Modify: `.gitignore`

- [ ] **Step 1: Add failing tests for live guard and Markdown rendering**

Append tests:

```ts
import {
  assertLiveBenchmarkAllowed,
  renderExecutorComparisonMarkdown
} from "../src/executorComparison";

test("blocks live benchmark execution without explicit environment opt-in", () => {
  expect(() => assertLiveBenchmarkAllowed({})).toThrow("WAYGENT_CPE_BENCH_ALLOW_LIVE=1");
  expect(() => assertLiveBenchmarkAllowed({ WAYGENT_CPE_BENCH_ALLOW_LIVE: "1" })).not.toThrow();
});

test("renders a markdown comparison table", () => {
  const markdown = renderExecutorComparisonMarkdown(summarizeExecutorComparison([
    trial({ quality: { ...trial().quality, score: 100 } }),
    trial({ executor: "kws-codex-plan-executor", duration_ms: 12_000, quality: { ...trial().quality, score: 80 } })
  ]));
  expect(markdown).toContain("| Executor | Trials | Avg quality | Avg duration | Cost known | Total cost |");
  expect(markdown).toContain("| waygent | 1 | 100.0 | 10000ms | yes | $1.25 |");
  expect(markdown).toContain("| kws-codex-plan-executor | 1 | 80.0 | 12000ms | yes | $1.25 |");
});
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `bun test packages/testkit/tests/executorComparison.test.ts`

Expected: FAIL because live guard and Markdown renderer do not exist.

- [ ] **Step 3: Implement live guard and Markdown renderer**

Add to `packages/testkit/src/executorComparison.ts`:

```ts
export function assertLiveBenchmarkAllowed(env: Record<string, string | undefined> = process.env): void {
  if (env.WAYGENT_CPE_BENCH_ALLOW_LIVE !== "1") {
    throw new Error("live executor comparison requires WAYGENT_CPE_BENCH_ALLOW_LIVE=1");
  }
}

export function renderExecutorComparisonMarkdown(summary: ExecutorComparisonSummary): string {
  const rows = (Object.keys(summary.by_executor) as ComparedExecutor[]).map((executor) => {
    const item = summary.by_executor[executor];
    const costKnown = item.cost_usd_known ? "yes" : "no";
    const cost = item.total_cost_usd === null ? "unknown" : `$${item.total_cost_usd.toFixed(2)}`;
    return `| ${executor} | ${item.trials} | ${item.average_quality_score.toFixed(1)} | ${Math.round(item.average_duration_ms)}ms | ${costKnown} | ${cost} |`;
  });
  return [
    `# Executor Comparison: ${summary.scenario_id}`,
    "",
    "| Executor | Trials | Avg quality | Avg duration | Cost known | Total cost |",
    "|----------|--------|-------------|--------------|------------|------------|",
    ...rows,
    ""
  ].join("\n");
}
```

- [ ] **Step 4: Add CLI entry and package script**

Create `packages/testkit/src/executorComparisonCli.ts`:

```ts
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  assertLiveBenchmarkAllowed,
  renderExecutorComparisonMarkdown,
  summarizeExecutorComparison,
  type ExecutorTrialResult
} from "./executorComparison";

const args = process.argv.slice(2);
const live = args.includes("--live");
const scenarioArg = args.find((arg) => arg.startsWith("--scenario="));
const scenarioId = scenarioArg?.split("=")[1] || "manual";

if (live) assertLiveBenchmarkAllowed();

const now = new Date().toISOString();
const trials: ExecutorTrialResult[] = [];
const summary = summarizeExecutorComparison(trials);
const outDir = join("reports", "executor-comparison", `${now.replace(/[:.]/g, "-")}-${scenarioId}`);
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, "report.json"), JSON.stringify({ summary, trials, dry_run: !live }, null, 2) + "\n");
writeFileSync(join(outDir, "summary.md"), renderExecutorComparisonMarkdown(summary));
console.log(JSON.stringify({ outDir, dry_run: !live, planned: { scenario_id: scenarioId } }, null, 2));
```

Modify `package.json`:

```json
"waygent:dogfood": "bun test tests/integration/waygent-dogfood-evidence.test.ts",
"executor:compare": "bun run packages/testkit/src/executorComparisonCli.ts"
```

Keep the existing scripts unchanged and insert the new script after
`waygent:dogfood`.

Modify `.gitignore`:

```gitignore
reports/
```

- [ ] **Step 5: Run CLI smoke**

Run: `bun run executor:compare -- --scenario=smoke`

Expected: PASS and writes `reports/executor-comparison/<timestamp>-smoke/`.

Run: `bun run executor:compare -- --scenario=smoke --live`

Expected: FAIL with `WAYGENT_CPE_BENCH_ALLOW_LIVE=1`.

## Task 4: Document the Comparison Workflow

```yaml waygent-task
id: task_4_executor_comparison_docs
title: Document comparison workflow
dependencies: [task_3_executor_comparison_cli]
file_claims:
  - path: docs/benchmarks/waygent-cpe/README.md
    mode: owned
  - path: docs/superpowers/specs/2026-06-01-waygent-cpe-comparison-benchmark-design.md
    mode: read_only
  - path: docs/superpowers/plans/2026-06-01-waygent-cpe-comparison-benchmark.md
    mode: read_only
risk: low
verify:
  - git diff --check
```

**Files:**
- Create: `docs/benchmarks/waygent-cpe/README.md`

- [ ] **Step 1: Write the benchmark README**

Create `docs/benchmarks/waygent-cpe/README.md`:

````md
# Waygent vs KWS Codex Plan Executor Benchmark

This benchmark compares Waygent and `kws-codex-plan-executor` without making
either executor depend on the other.

## Dry Run

```bash
bun run executor:compare -- --scenario=smoke
```

Dry run writes a report skeleton and prints the planned scenario. It does not
run live providers.

## Offline Gates

```bash
skills/waygent/evals/run.sh
bun run waygent:scenarios
skills/kws-codex-plan-executor/evals/run.sh
```

These gates measure deterministic harness overhead and regression coverage.

## Live Trial

Live trials can spend provider credits and must be explicitly enabled:

```bash
WAYGENT_CPE_BENCH_ALLOW_LIVE=1 bun run executor:compare -- --scenario=<id> --repetitions=3 --live
```

Do not apply generated patches from benchmark runs unless a later operator
step explicitly reviews and applies a verified checkpoint.

## Report Fields

- quality score
- wall-clock duration
- cost and token usage when known
- retries and recovered failures
- final blocker
- artifact refs
````

- [ ] **Step 2: Run docs hygiene**

Run: `git diff --check`

Expected: PASS.

## Final Verification

Run:

```bash
bun test packages/testkit/tests/executorComparison.test.ts
bun run executor:compare -- --scenario=smoke
git diff --check
```

If `reports/executor-comparison/` is untracked after the smoke command, remove
or ignore that generated output before committing unless the operator asks to
preserve the evidence pack.

## Execution Notes

- Do not run live provider comparison without
  `WAYGENT_CPE_BENCH_ALLOW_LIVE=1`.
- Do not apply patches from benchmark runs.
- Do not import CPE code from Waygent runtime packages.
- Use the benchmark output to decide which CPE guardrails should be promoted
  into Waygent, not to make CPE a Waygent dependency.
