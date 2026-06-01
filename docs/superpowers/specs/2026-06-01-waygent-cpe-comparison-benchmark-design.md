# Waygent vs KWS Codex Plan Executor Comparison Benchmark Design

- **Date**: 2026-06-01
- **Type**: Approved comparison design
- **Status**: Approved design, pending implementation plan execution
- **Scope**: Neutral benchmark harness and reporting for comparing Waygent and
  `kws-codex-plan-executor` on quality, time, runtime overhead, recovery, and
  cost.

## 1. Goal

Build a repeatable comparison path that can answer:

- Which executor produces higher-quality task outcomes on the same plan/spec?
- Which executor reaches verified or apply-ready state faster?
- Which executor spends fewer provider tokens and less estimated cost?
- Which executor fails more safely when provider output, verification, or dirty
  checkout conditions are imperfect?

The benchmark must compare the two systems without making either one a runtime
dependency of the other.

## 2. Boundary

Waygent is the product runtime. It must keep owning scheduling, worker
worktrees, provider attempts, verification, checkpoints, review, Lens events,
resume, and apply for Waygent runs.

`kws-codex-plan-executor` is a Codex execution skill. It may remain a benchmark
competitor and a source of proven design ideas, but it must not be called from
Waygent runtime code and must not become a Waygent product dependency.

The comparison harness is a neutral testkit/reporting tool. It may read
Waygent run artifacts and CPE state artifacts, but it does not apply patches,
retry live work, or mutate source checkouts except in explicitly isolated
benchmark workspaces.

## 3. Benchmark Layers

### 3.1 Contract and offline overhead

This layer measures deterministic harness overhead and regression coverage:

- `skills/waygent/evals/run.sh`
- `bun run waygent:scenarios`
- `skills/kws-codex-plan-executor/evals/run.sh`

This layer is cheap and runs locally. It does not prove live implementation
quality, but it establishes baseline validation cost and regression surface.

Current observed baseline from this checkout:

| Gate | Result | Wall time |
|------|--------|-----------|
| `skills/waygent/evals/run.sh` | pass | 0.07s |
| `bun run waygent:scenarios` | 14 pass / 0 fail | 6.06s |
| `skills/kws-codex-plan-executor/evals/run.sh` | 8 fixtures pass | 11.07s |

These values are evidence for this checkout only. They should be re-measured
when the harness is implemented.

### 3.2 Artifact normalization

Both executors should be normalized into a shared result shape:

```ts
export interface ExecutorTrialResult {
  schema: "waygent.executor_comparison.trial.v1";
  executor: "waygent" | "kws-codex-plan-executor";
  scenario_id: string;
  repetition: number;
  command: string[];
  started_at: string;
  completed_at: string;
  duration_ms: number;
  outcome: "passed" | "failed" | "blocked" | "inconclusive";
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
    source: "provider_usage" | "state_estimate" | "unknown";
  };
  recovery: {
    retries: number;
    recovered_failures: string[];
    final_blocker: string | null;
  };
  artifact_refs: string[];
}
```

The first implementation should normalize existing artifacts and synthetic
fixtures before it runs live providers.

### 3.3 Live A/B trial

The live layer runs the same plan/spec under both executors, in isolated
workspaces, with a fixed repetition count.

Recommended first trial:

- repetitions: 3
- provider: Codex for both paths when possible
- Waygent profile: `balanced`
- CPE mode: `headless`, `subagents=on`
- budget cap: required
- apply: disabled unless both trial outputs pass and the operator explicitly
  requests apply

Live trial execution must require an explicit environment switch:

```bash
WAYGENT_CPE_BENCH_ALLOW_LIVE=1 bun run executor:compare -- --scenario <id> --repetitions 3
```

Without that switch, the command only validates fixture inputs and reports what
would run.

## 4. Quality Scoring

Use a simple, auditable score instead of a hidden judge:

| Signal | Points |
|--------|--------|
| Required verification passed | 30 |
| Review passed or not required | 20 |
| Apply-ready or clean terminal completion | 20 |
| No out-of-scope changes | 15 |
| No unresolved blocker | 10 |
| Clear artifact refs for state, logs, and diff | 5 |

The maximum score is 100. A trial with missing artifact refs is
`inconclusive`, not a silent failure.

Optional LLM review can be added later, but it must be recorded as a separate
review signal and must not replace deterministic checks.

## 5. Time and Performance Metrics

Record:

- wall-clock `duration_ms`
- provider-attempt duration
- verification duration
- review duration when available
- number of dispatches
- number of retries
- time to first blocker
- time to apply-ready or equivalent terminal state

For Waygent, prefer `inspect`, `cost`, state timing fields, provider attempts,
and runtime-cost projections. For CPE, prefer `state.json`, `context.json`,
headless logs, final output, and any recorded command observations.

## 6. Cost Metrics

Cost is best-effort because provider usage visibility differs by host.

Waygent should read:

- `cost_ledger`
- `provider_attempts[].usage`
- `provider_attempts[].actual_model`
- `platform.cost_accumulated` events when present

CPE should read:

- state completion evidence
- headless JSONL/final artifacts
- command logs if they contain provider usage
- unknown usage as `source: "unknown"` rather than inventing a value

The report must separate unknown cost from zero cost.

## 7. Output

The benchmark writes a JSON report and a Markdown summary:

```text
reports/executor-comparison/<timestamp>-<scenario-id>/
  report.json
  summary.md
  waygent/
  cpe/
```

The report directory is generated output. The implementation should add
`reports/` to `.gitignore` so generated benchmark reports stay out of git unless
the operator explicitly wants to preserve a benchmark evidence pack.

## 8. Acceptance Criteria

- A pure normalizer can score synthetic Waygent and CPE artifacts without
  running live providers.
- The CLI can run in dry-run mode and show the exact commands that would be
  executed.
- Live mode is blocked unless `WAYGENT_CPE_BENCH_ALLOW_LIVE=1` is set.
- Reports include quality, time, cost, recovery, and artifact references.
- Waygent runtime code does not import or call CPE skill code.
- CPE skill code is not modified for the benchmark unless a later plan
  explicitly targets CPE instrumentation.

## 9. Non-Goals

- Declaring a permanent winner from one run.
- Applying benchmark-generated patches to the source checkout.
- Building a hosted dashboard.
- Replacing Waygent scenario tests or CPE evals.
- Adding CPE as a Waygent dependency.
