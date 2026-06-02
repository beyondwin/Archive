# v2.24 — Data-Driven Cost Tiering (Umbrella)

> Status: DRAFT
> Author: orchestrator collaboration session 2026-06-02
> Targets: Build the run-telemetry aggregator that the deferred backlog has been
> blocked on, then use its data to gate two cost optimizations — a Haiku
> Implementer tier for LOW-risk single-file tasks, and closing the v2.22 cache-TTL
> open question with production-measured evidence.
> Predecessors: v2.22 (dispatch optimization — SHIPPED 2026-05-31),
> v2.23 (implementer adversarial self-check — SKIP 2026-06-02)

---

## 0. Problem Statement

Two structural facts about the current skill state motivate this umbrella:

1. **A real run corpus now exists, but nothing reads it.** `~/.claude/orchestrator/*/state.json`
   holds 20+ real runs with populated `cost_ledger` blocks (e.g. the v2.22 run:
   19 dispatches, $12.35, 657K input tokens). Meanwhile the learning-log under
   `~/.claude/learning/kws-claude-multi-agent-executor/runs/**/events.jsonl` holds
   a single event file dated 2026-05-18. The data the deferred backlog keeps
   waiting for is already on disk — unaggregated.

2. **~5 deferred candidates are frozen on "measure first."** `docs/deferred-candidates.md`
   gates Haiku Implementer tiering, `context_health` active management, the Plan
   Reviewer pre-mortem, and governance flags all on "accumulate 1–2 weeks of
   learning-log data, then revisit." But there is no tool to read or summarize
   that data, so the gate can never clear and the backlog is permanently frozen.

3. **v2.22's cache win is unverified in production.** `evals/baselines/v2.22.0.json`
   reports `cache_hit_ratio_mean=0.66`, but that is an eval-harness figure. The
   run that *implemented* v2.22 executed on the v2.21 skill and recorded
   `cost_ledger.totals.cached_read_tokens=0`. No real orchestrator run has yet
   confirmed the production cache-hit ratio, and v2.22 D006 (cache TTL: ephemeral
   vs 1-hour) was left **pending** with no ADR body.

This umbrella unblocks the backlog with one read-only tool (Phase A), then spends
that tool's output on the two cost levers it makes measurable (Phases B, C). It
deliberately preserves the skill's measure-first / Goodhart-guard discipline:
Phase A always ships; Phases B and C ship **only if** Phase A's data clears an
explicit, pre-registered gate. A failed gate is a documented SKIP, not a forced
ship — same disposition as v2.23.

---

## 1. Goals

**G1**: Provide a read-only CLI that summarizes the existing run corpus
(cost/token/cache, retry distributions, recurring issue signatures, quality-trend
drift) without altering any orchestrator control flow.

**G2**: Use G1's LOW-task `verifier_retry` distribution and P4 QUALITY fail-rate
to decide — on evidence, not guess — whether a Haiku Implementer tier is safe for
LOW-risk single-file tasks, and ship it only if the gate clears.

**G3**: Use G1's production cache-hit data to resolve v2.22 D006 with an ADR
body — either confirming ephemeral TTL is sufficient or adopting a 1-hour
extended TTL for the stable SCAFFOLD prefix.

**G4**: Preserve every existing guardrail in the `SKILL.md` Guardrails table. No
risk-tier, method-audit, retry-budget, or TDD-mandate semantic change. The Haiku
tier (G2) is a model-selection change only; TDD remains mandatory for executable
work regardless of model or task size.

**G5**: Keep the Goodhart guard intact. The Phase A aggregator is **observation-only** —
it MUST NOT introduce threshold-driven control flow into the orchestrator. Its
output informs human/orchestrator decisions at design time, not runtime branching.

**Non-goals**:
- Migrating Implementer / Combined Reviewer off the Agent tool (they keep
  in-session caching + subscription-pool semantics; this is the v2.22 non-goal,
  unchanged).
- `context_health` active management (auto-compaction forcing, dispatch
  throttling, mid-task summary injection) — stays deferred per its own shelf entry.
- Plan Reviewer pre-mortem sub-step, governance flags, user-configurable
  thresholds — stay deferred.
- Reviving the v2.23 implementer adversarial self-check (measured negative; no
  headroom on current Sonnet).
- Adding a learning-log → experiment-scaffold auto-trigger (depends on Phase A,
  but is itself a separate downstream candidate).

---

## 2. Three-Phase Plan

### Phase A — Run/Telemetry Aggregator CLI (always ships; keystone)

**A1. New helper `scripts/aggregate_runs.py`**
- A read-only CLI. It reads existing artifacts and prints/exports a summary. It
  adds **no** field to `state.json`, touches **no** SKILL.md phase prose, and
  introduces **no** runtime branch.
- Data sources, by priority:
  1. **Primary — `state.json` cost ledgers.** Glob `~/.claude/orchestrator/*/state.json`
     (tilde expanded to `$HOME`). Read `cost_ledger.totals` and `cost_ledger.by_task`,
     plus per-task fields: `risk_levels`, `quality_trend` (per-plan via `<active>`
     resolution), `current_verifier_retries`/per-task `verifier_retries`,
     `review_retries`, `method_audit`, `escalation_count`, `timestamps`.
     For multi-plan (`plan_chain`) runs, iterate every `plan_chain[N]`, not just
     top level (same iteration rule the v2.13 method-audit validator uses).
  2. **Secondary — AgentLens `kws-cme.*` events.** When present, enrich with
     per-dispatch `cache_hit_ratio`, `wall_ms`, `dispatch_method`. Treated as
     optional: a run with no events is still fully summarized from its ledger.
- Outputs (`--format md|json`, default `md` to stdout; `--json <path>` to export):
  - **Per-run row**: run id, plan slug, tasks done, dispatches, cost_usd,
    input/output tokens, cache_read/cache_creation tokens, cache_hit_ratio
    (`cache_read / (input + cache_read)`), wall time (from `timestamps`).
  - **Retry distributions**: histogram of `verifier_retry` and `review_retry`
    counts, **split by risk tier**. The LOW-tier `verifier_retry` distribution is
    the explicit Phase B gate input.
  - **Quality**: P4 QUALITY fail-rate (fraction of tasks whose recorded quality
    score < 0.75), quality_trend drift (mean-of-last-5 − mean-of-first-5 per run).
  - **Recurring issue signatures**: ISSUE_KEY (`file:line:category`) exact-match
    counts aggregated across runs (reuses the existing ISSUE_KEY matching rule —
    never fuzzy text).
  - **Observability gaps**: flags runs where `cost_ledger.totals.dispatches==0`,
    `quality_trend==[]`, or `timestamps.*` is null — **reported, never acted on**.
    (Both conditions were observed in the current corpus and are exactly the kind
    of silent regression this tool should surface.)
- Filtering: `--since <date>`, `--plan <slug-glob>`, `--risk <low|mid|high>`.
- Robustness: a malformed or partial `state.json` is skipped with a WARN line, not
  a crash — the corpus contains in-flight and aborted runs.

**A2. Tests**
- `scripts/test_aggregate_runs.py` over synthetic `state.json` fixtures covering:
  single-plan, multi-plan `plan_chain`, a run with empty `quality_trend`, a run
  with `dispatches==0`, a malformed file, and a run with AgentLens events present
  vs absent. Assert the report rows and the gap flags.
- The fixtures double as the "what good/bad telemetry looks like" reference.

**A3. Docs**
- `docs/how-to/` entry: how to run the aggregator and read its output.
- Update `docs/deferred-candidates.md` "학습 로그용 집계자 / 리포팅 CLI" entry:
  mark shipped, point at the script, and note that the data-gated candidates can
  now be evaluated against real distributions.

**Acceptance for Phase A**:
- `aggregate_runs.py` runs clean over the current `~/.claude/orchestrator/*`
  corpus and emits a non-empty per-run table.
- `scripts/test_aggregate_runs.py` passes; `cd skills/kws-claude-multi-agent-executor && python -m pytest scripts/` green.
- No diff to any `references/phases/*.md`, no new `state.json` field, no new
  runtime branch (verified by grep: the script is never invoked from phase prose).
- The report includes the LOW-tier `verifier_retry` distribution and a production
  `cache_hit_ratio` column — the two inputs Phases B and C consume.

---

### Phase B — Haiku Implementer Tier for LOW-risk Single-File Tasks (gated)

**Gate (evaluated from Phase A output, pre-registered):**
- **B-GATE-1**: LOW-tier `verifier_retry` distribution is narrow — ≥90% of LOW
  tasks completed with 0 verifier retries across the corpus.
- **B-GATE-2**: P4 QUALITY fail-rate on LOW tasks < 5%.
- If either fails: **do not ship.** Record the measured distribution in
  `findings/`, update `docs/deferred-candidates.md` with the new revisit bar, and
  close Phase B as SKIP. This is a legitimate outcome.

**B1. Tier policy in Phase 1 Step 1**
- Extend the Implementer model selection so a task qualifies for the Haiku tier
  iff **all** hold: `risk == LOW` AND the task declares exactly one `Files:` entry
  AND effort `== SMALL` (the existing heuristic estimate, biased upward). Anything
  else stays on the run's `implementer_model` (Sonnet default / Opus override).
- The Combined Reviewer and Verifier are **unaffected** — they remain Sonnet for
  judge consistency (existing invariant).
- TDD remains mandatory: a Haiku-tier task that writes executable code still must
  use `superpowers:test-driven-development` and report RED/GREEN evidence. The
  tier changes who writes the code, not whether tests gate it.

**B2. State + forensics**
- Per-task field `<active>.tasks.<id>.implementer_model_used` records the actual
  model dispatched (Haiku vs the run model), so the aggregator can later compare
  tiered vs untiered quality.
- Run-level: extend the existing `implementer_model` object with
  `tier_policy ∈ {"off", "haiku_low_single"}` (default `"off"` until the gate
  clears and ship lands; then `"haiku_low_single"`).
- Phase 1 Step 1 and Parallel Sub-Flow Step P.2 both honor the tier (the v2.12
  invariant that P.2 must also pass `model` applies here — forgetting it silently
  downgrades parallel-merged tasks).

**B3. A/B eval (ship gate, mirrors v2.22 A1 methodology)**
- `evals/implementer-tier/v2.24-haiku-vs-sonnet.json`: on fixtures 01 and 02
  (LOW-risk, single-file shaped), N reps each arm, score first-pass output against
  each fixture's rubric.
- Ship requires: Haiku first-pass rubric pass-rate ≥ Sonnet − one rubric check
  (i.e. no material quality regression) AND no QUALITY-threshold (0.75) regression.
- Reuse the Haiku-vs-Sonnet agreement harness pattern proven in v2.22's Plan
  Reviewer migration.

**B4. Rollback**
- Single flag: `implementer_model.tier_policy = "off"` reverts to all-Sonnet (or
  the run's chosen model). No prompt or phase-prose change to revert.

**Acceptance for Phase B**:
- B-GATE-1 and B-GATE-2 evaluated and recorded in `findings/`.
- If gate clears: A/B eval passes; a run on a LOW-heavy plan shows
  `implementer_model_used == haiku` on qualifying tasks and Sonnet elsewhere,
  with no QUALITY regression vs the v2.22 baseline; Guardrails table gains the
  tier-policy rule.
- If gate fails: SKIP recorded; `deferred-candidates.md` updated with the
  measured bar; no skill behavior change.

---

### Phase C — Cache TTL Resolution + Production Validation (gated; quick)

**C1. Production cache measurement (prerequisite, from Phase A)**
- Use `aggregate_runs.py` `cache_hit_ratio` over post-v2.22 real runs. If no
  post-v2.22 run exists yet, execute one representative plan on v2.22 first to
  generate ledger data with caching active (the implementing run had `cached=0`).
- Output: the real per-role and aggregate cache-hit ratio, and the distribution
  of inter-dispatch gaps (to see whether the 5-min ephemeral TTL is expiring
  between dispatches).

**C2. TTL decision (closes D006)**
- If measured cache-hit ratio is at or above the 0.66 eval figure and inter-dispatch
  gaps rarely exceed 5 min: **confirm ephemeral**, write the D006 ADR body
  ("ephemeral sufficient; measured ratio X, gaps Y"). Done.
- If gaps routinely exceed 5 min and cause measurable misses: A/B the stable
  SCAFFOLD prefix under ephemeral vs 1-hour extended cache TTL on a representative
  run, comparing `cache_hit_ratio` and input cost. Adopt 1-hour **only if** it
  lifts the ratio materially with no API-contract risk; otherwise stay ephemeral.
  Either way, D006 closes with a measured ADR.

**C3. If 1-hour is adopted**
- Change is confined to the `cache_control` parameter in `scripts/dispatch_via_api.py`
  for the SCAFFOLD block. The byte-stability invariant (v2.22 D004,
  `validate_scaffold_split.py`) is unchanged — only the TTL flag differs.
- Guardrails table note updated to reflect the chosen TTL.

**Acceptance for Phase C**:
- Production `cache_hit_ratio` measured and recorded.
- D006 closed with an ADR body (ephemeral confirmed OR 1-hour adopted with A/B
  evidence).
- If 1-hour adopted: a regression run shows cache_hit_ratio ≥ ephemeral baseline
  and no new ENV_BLOCKER.

---

## 3. Sequencing & Branching

```
main
 │
 ├── v2.24-A (Phase A: aggregator CLI)        ← always ships; unblocks B + C
 │     ├── A1: scripts/aggregate_runs.py
 │     ├── A2: scripts/test_aggregate_runs.py
 │     └── A3: how-to doc + deferred-candidates update
 │
 ├── v2.24-B (Phase B: Haiku Implementer tier) ← gated on A's LOW verifier_retry + QUALITY data
 │     ├── B-GATE eval (ship or SKIP)
 │     ├── B1: tier policy in Phase 1 Step 1 / P.2
 │     ├── B2: state + forensics fields
 │     ├── B3: A/B eval
 │     └── B4: rollback flag
 │
 └── v2.24-C (Phase C: cache TTL)              ← gated on A's production cache_hit data
       ├── C1: production cache measurement
       ├── C2: D006 decision + ADR
       └── C3: 1-hour TTL change (only if A/B clears)
```

Phase A is the prerequisite for both B and C. B and C are independent of each
other and may proceed in parallel once A has produced data. Either B or C may
legitimately end in SKIP without affecting the other or Phase A.

---

## 4. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Aggregator silently miscounts multi-plan `plan_chain` runs | M | M | A2 fixtures include a `plan_chain` run; assert per-plan iteration matches the v2.13 method-audit validator rule. |
| Corpus too sparse for a meaningful Phase B gate | M | M | Gate is pre-registered with explicit thresholds; if n is too low, B closes as "insufficient data" SKIP (not a forced ship) and the bar is recorded for a later revisit. |
| Haiku misses a defect Sonnet would catch on a LOW task | L | M | B3 A/B eval gate (≥ Sonnet − one rubric check); Reviewer/Verifier stay Sonnet and still gate every task; tier confined to LOW + single-file + SMALL. |
| Aggregator drifts into runtime control flow (Goodhart violation) | L | H | G5 invariant + Phase A acceptance grep: the script is never invoked from any `references/phases/*.md`. Observation-only by construction. |
| Production cache ratio can't be measured (no post-v2.22 run) | M | L | C1 executes one representative plan first to generate ledger data. |
| 1-hour TTL introduces API-contract risk | L | M | C2 adopts 1-hour only on measured benefit; change is a single `cache_control` flag, trivially reverted; byte-stability lint unchanged. |

---

## 5. Out of Scope

- Implementer / Combined Reviewer migration off the Agent tool (unchanged v2.22 non-goal).
- `context_health` active management, Plan Reviewer pre-mortem, governance flags,
  user-configurable thresholds — remain on the deferred shelf.
- Learning-log → experiment-scaffold auto-trigger (downstream of Phase A; separate candidate).
- Reviving v2.23 implementer adversarial self-check.
- Any new observability stack; AgentLens stays the event system.
- Restructuring `state.json` schema — Phase B's new fields (`implementer_model.tier_policy`,
  per-task `implementer_model_used`) are additive; existing readers ignore them.

---

## 6. Validation

```bash
cd skills/kws-claude-multi-agent-executor

# Phase A: aggregator over the real corpus + unit tests
python scripts/aggregate_runs.py --since 2026-05-01
python -m pytest scripts/test_aggregate_runs.py

# Phase B gate inputs (LOW verifier_retry distribution + QUALITY fail-rate)
python scripts/aggregate_runs.py --risk low --json /tmp/v2.24-low.json

# Phase B A/B eval (only if gate clears)
# evals/implementer-tier/v2.24-haiku-vs-sonnet.json

# Phase C: production cache-hit ratio
python scripts/aggregate_runs.py --since <first-post-v2.22-run> --format md
```

**Eval baselines to add/refresh**:
- `evals/implementer-tier/v2.24-haiku-vs-sonnet.json` (B3 ship gate; only if B-GATE clears).
- `evals/baselines/v2.24.0.json` if Phase B or C lands a behavior change.

---

## 7. Open Questions

1. **Q**: Should the aggregator also ingest the near-empty learning-log `events.jsonl`,
   or only `state.json` + AgentLens? **A (proposed)**: `state.json` primary,
   AgentLens secondary; learning-log `events.jsonl` is read opportunistically if
   present but is not a required source (it is nearly empty in the current corpus).
2. **Q**: What is the minimum corpus size for a trustworthy Phase B gate?
   **A (proposed)**: Decide from Phase A output — if LOW-task n is too small for a
   stable distribution, B closes as "insufficient data" SKIP rather than shipping
   on noise. Record the n actually observed.
3. **Q**: Should the Haiku tier widen to MID-risk later? **A (proposed)**: No —
   out of scope for v2.24. Revisit only after the LOW tier has its own real-run
   quality data through the aggregator.

---

## 8. Decisions Register (to be appended as phases ship)

| ID | Decision | Phase | Status |
|----|----------|-------|--------|
| D001 | Aggregator is read-only / observation-only (no runtime control flow) | A | proposed |
| D002 | `state.json` cost ledgers are the primary data source; AgentLens secondary | A | proposed |
| D003 | Phase B ships only if LOW verifier_retry + QUALITY gate clears; else SKIP | B | proposed |
| D004 | Haiku tier scope = LOW-risk AND single-file AND SMALL; TDD still mandatory | B | proposed |
| D005 | Reviewer/Verifier stay Sonnet regardless of Implementer tier | B | proposed |
| D006 (v2.22) | Cache TTL resolved with production evidence (ephemeral confirmed or 1-hour adopted) | C | inherited-pending |

---

## 9. Done When

- Phase A acceptance met: `aggregate_runs.py` + tests shipped, runs clean over the
  real corpus, surfaces the LOW verifier_retry distribution and production
  cache_hit_ratio, and is provably never called from phase prose.
- Phase B reaches a recorded decision: either SHIP (gate cleared, A/B passed,
  tier-policy + forensics fields + Guardrails rule landed) or SKIP (gate failed,
  measured bar recorded in `deferred-candidates.md`).
- Phase C reaches a recorded decision: D006 closed with an ADR body, production
  cache ratio measured, 1-hour TTL adopted only on A/B evidence.
- `docs/deferred-candidates.md` updated (aggregator marked shipped; B/C outcomes
  recorded).
- `docs/CHANGELOG.md` + `HISTORY.md` updated with whatever user-visible change
  actually shipped (aggregator CLI always; Haiku tier and TTL change conditionally).
- `JOURNAL.md` populated with per-phase outcomes, observed metrics, and any SKIP
  rationale.
