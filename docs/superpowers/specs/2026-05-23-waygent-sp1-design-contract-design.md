# SP-1: Design-Driven Implementation Contract

Sub-project of the Waygent Hardening Roadmap
(`2026-05-23-waygent-hardening-roadmap.md`).

Goal: introduce a single source-of-truth contract between design/plan
documents and worker output, so cross-path invariants, schema-versioned
worker results, prescriptive snippet integrity, and policy acknowledgements
are enforced at dispatch and verification time. Author burden stays low:
canonical scaffold output is parsed deterministically; free-form prose is
normalized by an AI-mediated extractor with cached, audit-logged output.

## 1. Goals and Non-Goals

### 1.1 Goals
- Make design/plan documents the authoritative source for cross-path
  invariants, compatibility constraints, and prescriptive code snippets.
- Normalize design/plan markdown into typed JSON artifacts that every
  downstream pipeline stage consumes — no markdown re-parsing in
  orchestrator code.
- Detect invariant violations before worker dispatch (deterministic shell
  checks against the working tree) and after worker output (envelope
  validation, ack confidence, prescriptive drift).
- Surface every failure through the existing `intake_decision_required`
  channel; do not add new blocker families or new event namespaces.
- Allow authors to write design/plan in any prose style, including Korean
  free-form, without memorizing markdown conventions. AI extractor handles
  arbitrary formats; deterministic parser remains the fast path for
  scaffold-generated documents.

### 1.2 Non-Goals
- Replacing the existing `worker_result.v2` envelope. SP-1 *validates*
  it; the schema itself was added earlier and stays unchanged in shape.
- Building a UI for normalized JSON review. CLI text diff is sufficient.
- A new event family. All operator-visible signals stay under
  `runway.*` / existing run_state.v2 additive fields.
- Verify env / worktree-aware verification (SP-2 owns it).
- Operator explain UX polish (SP-3 owns it).
- Apply/resume granularity (SP-4 owns it).

## 2. Architecture

### 2.1 New Package — `packages/design-contract/`

```
packages/design-contract/
├── src/
│   ├── index.ts              # public exports
│   ├── types.ts              # DesignContract, PlanContract, invariant types
│   ├── parse/
│   │   ├── deterministic.ts  # canonical markdown parser (fast path)
│   │   ├── ai.ts             # provider-mediated extractor
│   │   ├── cache.ts          # hash-keyed artifact cache
│   │   └── index.ts          # parseDesignSource / parsePlanSource
│   ├── invariants.ts         # check runner, paths_bound matcher, ack validator
│   ├── workerEnvelope.ts     # worker_result.v2 validator + drift detector
│   ├── checks/               # built-in check kinds (shell, exists, json-equals)
│   └── lint.ts               # dry-run extraction backend for CLI
├── tests/
│   ├── fixtures/             # canonical/, freeform/, degraded/
│   └── *.test.ts             # unit tests
├── package.json
└── tsconfig.json
```

Consumers:
- `apps/cli` — adds `waygent lint-design`, `waygent lint-plan`.
- `packages/orchestrator` — pre-dispatch invariant checks, post-worker
  envelope/drift validation, normalized JSON storage in `run_state.v2`.

### 2.2 No binary schema mode

There is no `schema: v1 | v2` selector and no mixed-schema error. The
extractor produces a single normalized JSON shape regardless of input
form. The presence/absence of fields (invariants count, prescriptive
markers, ack requirements) is data-driven. Authors may evolve their
documents without declaring a version.

### 2.3 Extraction provider

Defines a new `ExtractorProvider` interface inside design-contract with
claude, codex, and fake implementations. The AI prompt requests
structured JSON output with cited evidence (source line ranges). The
fake provider is used for all unit tests via fixture responses; live
providers are only exercised in the opt-in drift smoke gate. The
interface is intentionally separate from `WorkerProvider` to keep
extraction concerns (one-shot structured output) decoupled from worker
dispatch (streaming, tool use, retries).

## 3. Data Flow

```
[ source markdown ]
       │
       ├─ cache lookup (hash → normalized JSON) ────► cached
       │
       ▼ miss
[ parseDeterministic ]
       │
       ├─ complete & valid ────────────────────────► normalized JSON
       │
       ▼ incomplete / ambiguous
[ parseAI (ExtractorProvider) ]
       │
       ├─ success (structured output validated) ───► normalized JSON
       │                                            + extraction_log
       │                                              (parser, prompt hash,
       │                                               evidence quotes,
       │                                               confidence)
       │
       └─ failure (transient retry exhausted /
                   malformed / refused)            ► design_extraction_failed
                                                     → intake_decision_required
```

Normalized JSON and extraction log are written to
`artifacts/design-contract/normalized-{design,plan}.json` and
`artifacts/design-contract/extraction-log-{design,plan}.json`.
`run_state.v2.design_contract` carries artifact refs and the parser used
(`deterministic | ai | cached`).

Pre-dispatch:
- Orchestrator loads normalized JSON for spec and plan.
- For each invariant whose `paths_bound` overlaps the upcoming task's
  file claims, runs the invariant check against the working tree.
- Violation → `intake_recovery.status = "decision_required"`,
  `blocker_kind = "invariant_violation_predispatch"`, evidence in
  recovery report.

Post-worker:
- Validate worker_result.v2 envelope (schema, required fields).
- For each invariant requiring ack: verify `policy_ack[invariant_id]`
  exists and confidence ≥ invariant's required confidence.
- For each prescriptive block: hash-check task output against the spec's
  prescriptive snippet. Drift → blocker.
- Missing `stale_test_candidates` array → blocker.

## 4. Error Handling

All failures route through the existing intake-recovery channel.
`blocker_kind` values, severity, and operator response:

| Blocker kind                          | Severity | Operator response                                           |
|---------------------------------------|----------|-------------------------------------------------------------|
| `design_source_missing`               | block    | fix path                                                    |
| `design_extraction_uncertain`         | warn     | review normalized JSON; resume to proceed                   |
| `design_extraction_failed`            | block    | hand-author normalized JSON or rewrite source               |
| `plan_extraction_failed`              | block    | same                                                        |
| `invariant_violation_predispatch`     | block    | fix code or amend invariant                                 |
| `invariant_violation_post_worker`     | block    | task re-run candidate                                       |
| `policy_ack_missing`                  | block    | task re-run with ack                                        |
| `policy_ack_unverified`               | block    | task re-run with stronger evidence                          |
| `stale_test_candidates_missing`       | block    | task re-run; envelope schema is enforced                    |
| `prescriptive_drift`                  | block    | task re-run with prescriptive snippet honored               |
| `cache_corruption`                    | info     | automatic re-extract; no operator action                    |

Escape hatch: `design_extraction_uncertain` is the only warn-only state.
All other failures require operator action (fix source, edit normalized
JSON, or rerun task). No `--force` flag bypasses strong failures.

AI extractor failure modes:
- Provider transient: exponential backoff 3 retries, then
  `design_extraction_failed`.
- Provider returns malformed JSON: 1 retry, then fail.
- Provider returns empty invariants with reasoning indicating "none
  found": acceptable, treated as document genuinely without invariants.
- Provider returns empty without reasoning: treated as uncertain.

## 5. Testing

### 5.1 Unit (`packages/design-contract/tests/`)
- `parseDeterministic.test.ts` — canonical fixtures → exact JSON;
  incomplete inputs return `IncompleteParse`.
- `parseAI.test.ts` — fake provider responses → validated JSON; malformed
  retry; evidence quote presence.
- `cache.test.ts` — hash hit/miss, corruption recovery.
- `parseIndex.test.ts` — fallback chain (cache → deterministic → AI →
  fail).
- `invariants.test.ts` — shell check execution, paths_bound matcher,
  ack confidence enforcement.
- `workerEnvelope.test.ts` — schema validation, drift detection,
  prescriptive hash compare.
- `lint.test.ts` — dry-run report formatting.

All unit tests use the fake provider with fixture responses. No live
network calls.

### 5.2 Fixtures
- `canonical/` — scaffold-shaped markdown + expected normalized JSON.
- `freeform/` — Korean prose, mixed-language, heading-less markdown +
  fixture AI responses.
- `degraded/` — extraction-uncertain, AI-malformed-then-recover,
  AI-totally-failed cases.
- Snapshot tests pin extraction output for the same input.

### 5.3 Integration (`apps/cli/tests/cli.test.ts`)
- Canonical design+plan → dispatch succeeds, design_contract artifact
  refs present in run_state.
- Freeform design → AI fallback, both normalized JSON and extraction-log
  refs recorded.
- Invariant violation → `intake_decision_required` with correct
  `blocker_kind`.
- Missing stale_test_candidates → blocker.
- Prescriptive drift → blocker with expected/actual snippet.
- Extraction uncertain → warn-only path; dispatch proceeds.
- Regression: existing intake-recovery tests still pass.

### 5.4 Fixture-lab
`bun run waygent:fixture-lab` gains canonical + freeform + degraded
replays alongside existing intake recovery fixtures.

### 5.5 Live drift smoke (opt-in)
`bun run waygent:design-contract-live-smoke` with
`WAYGENT_LIVE_PROVIDER=claude|codex` runs each fixture through a live
provider once and compares semantic equivalence (same invariant ids,
same paths_bound sets) to fixture responses. Not in default CI.

## 6. Scope and Sequencing

SP-1 is delivered in seven phases. Each phase lands independently with
its own verify gate; no phase merges if its gate fails. Sizes are
relative ranges, not commitments.

| Phase | Scope                                          | Verify gate                                                |
|------:|------------------------------------------------|------------------------------------------------------------|
| P0    | Package skeleton, workspace wiring             | `bun install`, `bun run check`                             |
| P1    | Types, deterministic parser, cache             | `bun run --cwd packages/design-contract test`, `check`     |
| P2    | AI extractor + fallback chain (fake provider)  | package tests with snapshots                               |
| P3    | Invariant runner, worker envelope validator    | package tests                                              |
| P4    | `waygent lint-design` / `waygent lint-plan`    | `bun run check`, apps/cli tests, manual lint smoke         |
| P5    | Orchestrator wiring (pre-dispatch + post-worker), run_state field | `check`, `platform:demo`, `waygent:scenarios`, `waygent:fixture-lab`, no 463-test regression |
| P6    | Fixture-lab extension, docs, skill contract    | `waygent:fixture-lab`, `check_skill_contract.py`, `git diff --check` |
| P7    | Live drift smoke (opt-in)                      | manual                                                     |

Largest risk concentrated in P5 (orchestrator wiring). P1–P4 build all
prerequisites in isolation so P5 is a thin integration layer.

## 7. Boundaries with Other Sub-Projects

- **SP-2 (verify env worktree-awareness)**: design-contract code runs in
  the CLI process, not inside worker worktrees, so it is unaffected by
  the `inherit_node_modules` isolation defect. P5 verify uses CLI-scope
  execution.
- **SP-3 (operator hygiene)**: SP-1 exposes `blocker_kind` and recovery
  report content; SP-3 will polish the explain rendering.
- **SP-4 (apply/resume granularity)**: independent. SP-1 blockers fire
  before dispatch and are orthogonal to apply checkpoints.

## 8. Open Questions

- Final canonical markdown schema for scaffold output: precise heading
  hierarchy, bullet format, paths_bound expression syntax. Resolved in
  P1 fixture authoring.
- Default invariant ack confidence requirement (`verified` vs
  `best_effort`): resolve per-invariant in spec authoring; SP-1 just
  enforces what the spec declares.
- AI extractor prompt versioning strategy. SP-1 ships v1 prompt;
  future prompt changes invalidate cache via the cache key including
  `extractor_version`.
