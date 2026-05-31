# v2.22 — Dispatch Optimization (Anthropic API Direct + Caching)

> Status: DRAFT
> Author: orchestrator collaboration session 2026-05-31
> Targets: Replace `claude -p --dangerously-skip-permissions` headless dispatches with cheaper, faster, cache-aware Anthropic Messages API calls; merge co-located dispatches; cheapen mechanical reviewers; simplify self-spawn.
> Predecessors: v2.19 (token cost optimization), v2.21 (slimming + enforcement)

---

## 0. Problem Statement

The skill currently uses `claude -p --dangerously-skip-permissions` for five headless roles:

| Role | Site | Frequency |
|------|------|-----------|
| Plan Reviewer | Phase 0 Step 6.5 | 1 per run |
| Verifier (per-task) | Phase 1 Step 3 | 1 per MID/HIGH task |
| Verifier (batch) | Transition T1 | 1 per compaction point |
| Phase Docs Updater | Transition T2 | 1 per compaction point |
| Final Docs Updater | Phase 2 Step 1 | 1 per run |
| Self-Spawn (orchestrator) | Phase -1 | 1 per interactive invocation |

Observed inefficiencies (from `v2.14-forensics-and-cost` ledger data, runs 1–7):

1. **Cold start tax**: Each `claude -p` spawn pays 2–5s wrapper init + model warm-up. Across a 20-task MID run, ~80–150s purely in process startup.
2. **No prompt cache reuse**: Identical scaffolds (superpowers bootstrap, structured-output schema, `test_command`, repo layout) re-tokenize every call. Measured cache hit rate: 0% for `-p` paths vs. 60–80% for in-session Agent tool paths.
3. **Agent SDK credit drain**: Subscription pool exhausts ~3× faster on `-p`-heavy runs than on equivalent in-session runs (run 5 hit pool ceiling at task 14/22).
4. **Result-file fragility**: JSON results land in `<orch_dir>/{verifier,docs}_results/<task>.json`. Missing file → ENV_BLOCKER ESCALATE. Observed 3 false ENV_BLOCKERs in run 4 caused by subprocess writing to wrong path under chained orchestrator inheritance.
5. **Process tracking overhead**: PID, stdout files, polling logic. 60 LOC of bash in Monitor scripts purely for `-p` lifecycle.

This spec eliminates or substantially reduces each.

---

## 1. Goals

**G1**: Cut per-dispatch wall-clock latency by ≥60% on cache-hit, ≥30% on cache-miss.
**G2**: Cut per-dispatch input token cost by ≥80% on cache-hit (caching alone delivers this — claim is verifiable from `cost_ledger`).
**G3**: Eliminate `verifier_results/*.json` and `docs_results/*.json` files as the dispatch return mechanism. Replace with structured tool-use output returned in-band.
**G4**: Preserve every existing guardrail in `Guardrails` table of `SKILL.md`. No risk-tier, no method-audit, no retry-budget semantic changes.
**G5**: Provide a clean rollback path (feature-flagged per role; `dispatch_via=p|api`).

**Non-goals**:
- Replacing Agent-tool dispatches (Implementer, Combined Reviewer). They already enjoy in-session caching.
- Migrating Self-Spawn off shell-exec (Phase C-2 only *simplifies* the contract, doesn't remove the subprocess).
- Adopting a different model family (Claude 4.x stays). Haiku cheapening is a *model selection* change, not provider change.

---

## 2. Three-Phase Plan

### Phase A — Quick Wins (1–2 days)

**A1. Plan Reviewer → Haiku 4.5**
- Rationale: Plan Reviewer at Phase 0 Step 6.5 is a mechanical rubric check (missing Files blocks, missing AC on MID/HIGH, dep cycles, out-of-repo paths, manifest references). The `Guardrails` rule explicitly states it must NOT make style/architecture judgments. This is the textbook Haiku workload.
- Change: `references/plan-reviewer-prompt.md` model selector → `claude-haiku-4-5-20251001`.
- Expected: ~3× faster, ~5× cheaper input, ~5× cheaper output. No quality regression because rubric items are binary.
- Guardrail addition: `state.plan_review.model_used` records selected model for forensics.
- Rollback: Single line in `references/plan-reviewer-prompt.md`; flip back to sonnet.

**A2. Merge Transition T1 (batch Verifier) + T2 (Phase Docs Updater) into single dispatch**
- Rationale: T1 and T2 run back-to-back at every compaction point. T2 reads T1's output to know which docs need updating. Today: two subprocess spawns, two cache misses, two result-file writes.
- Change: New combined prompt `references/transition-prompt.md` that calls two tools (`verify_low_batch`, `update_phase_docs`) in one dispatch. Sub-agent issues both tool calls in a single turn.
- Result shape: Single JSON `{verify: {...}, docs: {...}}` written to `<orch_dir>/transition_results/<plan_idx>_<compaction_idx>.json`.
- Phase Transition prose updates: T1 + T2 merge into a single "T1.2 Combined Transition Dispatch" step. T3 (state anchor + context drop) unchanged.
- Guardrail addition: If `verify` tool fails (any LOW task FAIL), `docs` tool result is still consumed but `state.transition_blocked=true` is set and Resume Chain skip docs commit until verifier re-dispatch passes.
- Expected: ~50% latency reduction at every compaction point. For a run with 4 compactions, saves 4 × ~30s = 2 min wall time.

**A3. Per-dispatch cost helper consolidation**
- The v2.16 `scripts/accumulate_cost.py` is called *per dispatch*. After A2, the merged T1+T2 dispatch must call it once with combined `by_task` key `<plan>::transition_<idx>::combined`.
- Add helper flag `--combined-roles verify,docs` so split-line forensics queries still work (`by_task` grouping preserves the combined nature).

**Acceptance for Phase A**:
- `bun run check` passes (no skill code changes outside references + prose).
- Plan Reviewer dispatch in `tmp/runs/v2.22-a-eval/` shows `model_used=claude-haiku-4-5-20251001`.
- Transition dispatch count per compaction = 1 (was 2). Verifiable from `cost_ledger.by_task` keys.
- No regression in any v2.21 eval baseline (`evals/baselines/v2.21.0.json` rerun).

---

### Phase B — Anthropic API Direct (1 week, primary value)

**B1. New helper `scripts/dispatch_via_api.py`**
- Single entry point for all headless-role dispatches that used to call `claude -p`.
- Signature:
  ```
  dispatch_via_api.py \
    --role <plan_reviewer|verifier|docs_updater|transition_combined> \
    --task-context <path-to-json> \
    --output <path-to-json> \
    --model <claude-sonnet-4-6|claude-haiku-4-5-20251001> \
    --orch-dir <abs-path>
  ```
- Implementation:
  - Uses `anthropic` Python SDK (already in `scripts/` deps via v2.16 cost helper).
  - Reads role-specific prompt template from `references/<role>-prompt.md`.
  - Splits template into **cached scaffold** (top 80%: superpowers bootstrap, JSON schema, repo invariants) and **task-specific payload** (bottom 20%: this task's spec excerpt, files-changed, etc.).
  - Marks scaffold with `cache_control: {type: "ephemeral"}` (5-min TTL).
  - Forces structured output via `tools=[ROLE_RESULT_SCHEMA]` + `tool_choice={type: "tool", name: "report_<role>"}`.
  - On success: extracts `tool_use.input` as result JSON, writes to `--output`.
  - On API error (rate limit, 5xx): exponential backoff 3 retries, then ENV_BLOCKER ESCALATE with the API error body.
  - Always emits `cost_ledger` line via `scripts/accumulate_cost.py` (per existing mandatory invariant).
  - Always emits AgentLens event `kws-cme.dispatch_via_api` with role + cache_hit_ratio (input_tokens vs cache_read_tokens).

**B2. Role-by-role migration**
Each role gets a feature flag `state.dispatch_config.<role> ∈ {"p", "api"}`. Default in v2.22: all `"api"`. Set to `"p"` to bisect regressions.

Migration order (most cache-friendly first):
1. **Plan Reviewer** (single-shot, identical scaffold every run) — perfect cache target.
2. **Verifier batch (T1)** — same `test_command`, same plan excerpt across LOW tasks in one batch.
3. **Transition combined** (depends on A2 landing first).
4. **Verifier per-task** — moderate cache hit (test_command shared across all tasks of a plan).
5. **Final Docs Updater** — lowest cache benefit (runs once at end) but still gains from the direct API path latency.

**B3. Cache scaffold extraction**
- For each `references/<role>-prompt.md`, identify the static prefix (the part that is byte-identical across every invocation within a run).
- Extract into `references/_scaffolds/<role>-scaffold.md`.
- Mark with HTML comment delimiters so a static linter (`scripts/validate_scaffold_split.py`) can verify the split is consistent:
  ```
  <!-- SCAFFOLD_BEGIN -->
  …cached content…
  <!-- SCAFFOLD_END -->
  <!-- PAYLOAD_BEGIN -->
  …per-invocation content with {placeholders}…
  <!-- PAYLOAD_END -->
  ```
- Lint at Phase 0 Step 7.5 (existing boundary emit step) ensures every role's scaffold + payload reassembles into the original prompt byte-for-byte.

**B4. Structured-output schemas**
Define JSON Schema for each role's result tool. Stored in `references/_schemas/`:
- `verifier_result.schema.json` — outcome (PASS|FAIL|WARN), per-test results, commands_run, findings_count.
- `docs_updater_result.schema.json` — files_changed, sections_updated, escalations.
- `plan_reviewer_result.schema.json` — blocker_issues[], warn_issues[].
- `transition_combined_result.schema.json` — `{verify: <verifier_result>, docs: <docs_updater_result>}`.

Each schema is hand-written, NOT generated, to keep the cache key stable. Adding a property requires a v2.22.x bump.

**B5. AgentLens event extensions**
- New event `kws-cme.dispatch_via_api` (one per call) with fields:
  - `role`, `model`, `input_tokens`, `cache_read_tokens`, `output_tokens`, `cache_hit_ratio`, `wall_ms`, `retries`.
- Existing events (`kws-cme.task_completed`, `kws-cme.compaction`) gain optional `dispatch_method ∈ {p, api}` so per-role bisection can be filtered in queries.

**B6. Guardrail additions to SKILL.md table**:
| Rule | Detail |
|------|--------|
| **API-direct dispatch is the default for headless roles** | `state.dispatch_config` (run-level top-level) sets per-role mode. v2.22+ defaults all roles to `api`. Bisection: set role to `p` to revert. Both paths preserve every other guardrail (retry caps, ESCALATE handling, cost accumulation, AgentLens emission). |
| **Cached scaffold byte-stability** | The static prefix of each role prompt MUST NOT vary across invocations within a single run. Verified by `scripts/validate_scaffold_split.py` at Phase 0 Step 7.5. Drift breaks cache hits and inflates input cost. Hot-fix scaffolds require a v2.22.x bump and re-run of `evals/baselines/`. |
| **API error fallback to `-p` is forbidden** | API failures bubble up as ENV_BLOCKER ESCALATE — the orchestrator does NOT silently retry via `-p`. Mixed-path retry destroys the cache-cost forensics and hides flaky-API signal. User chooses: rerun with `dispatch_config.<role>=p` or wait for API recovery. |
| **`tool_choice` is mandatory for all API-direct dispatches** | Schema-forced output via `{type: "tool", name: "report_<role>"}`. Free-text output is a regression (loses structured-output guarantee, can't validate at boundary). |

**B7. Cost model update**
- `scripts/price_table.py` already supports the relevant models. Confirm `claude-sonnet-4-6` and `claude-haiku-4-5-20251001` are present.
- Add `cache_read_input_tokens` and `cache_creation_input_tokens` line items to `accumulate_cost.py`. The Messages API returns these separately; the helper must distinguish them (cache_read priced ~10% of input, cache_creation priced ~125% of input).
- `cost_ledger.totals` gains: `cache_read_tokens`, `cache_creation_tokens`. Existing v2.15 C3 chain-trigger formula:
  ```
  session_input_tokens = cost_ledger.totals.input_tokens − cached_read_tokens
  ```
  remains correct (cache-read tokens shouldn't count toward chain pressure since they don't re-cost the context window).

**Acceptance for Phase B**:
- All five roles dispatched via API in a clean v2.22 run (verifiable from `cost_ledger.by_task` having no `claude -p` PID records and AgentLens events showing `dispatch_method=api`).
- Mean per-dispatch wall_ms ≤ 40% of v2.21 baseline.
- Mean per-dispatch input_token cost ≤ 20% of v2.21 baseline (cache-driven).
- Zero new ENV_BLOCKER false-positives across `evals/baselines/v2.22.0.json` (10-run regression).
- `verifier_results/` and `docs_results/` directories are not created in API-mode runs (clean stat at end of run).

---

### Phase C — Tail Cleanup (optional, 3–4 days)

**C1. Phase 2 Step 0 LOW-batch sweep via Batch API**
- Rationale: Phase 2 Step 0 sweep is the final accumulated LOW verification. It is non-blocking on the critical path (the only thing waiting is the Final Summary). Can tolerate up to 24h SLA.
- Change: Final sweep submits one Batch API request containing one Message-per-LOW-task. Polls completion before Step 1.
- Cost: 50% off all input + output tokens. For a 30-LOW-task plan, saves ~$2-3 per run at current rates.
- Guardrail: Only applies if `state.dispatch_config.final_sweep == "batch"`. Default in v2.22.1+ after Phase B stabilization. Phase B keeps it as regular API.
- Edge case: If Batch SLA exceeded (rare but real for low-priority queue), orchestrator emits `kws-cme.batch_timeout` and falls back to regular API dispatch with WARN logged. NOT an ENV_BLOCKER (sweep can recover).

**C2. Self-Spawn simplification**
- Current: Phase -1 detaches a `claude -p <<HEADLESS_KWS_ORCHESTRATOR>>` subprocess. Justification: isolate orchestrator context from interactive session. But Resume Chain already provides this isolation; Self-Spawn is largely vestigial post-v2.15.
- Proposal: Keep Self-Spawn ONLY for the case where the user invoked the skill but doesn't want to keep the terminal session attached (the original use case). When `mode=interactive` is implied or explicit, run in-session — no spawn.
- Change: Default behavior of bare `/kws-claude-multi-agent-executor plan=... spec=...` becomes `mode=interactive` unless `detach=true` is passed.
- Guardrail update: `mode` field gains the new value `"interactive_attached"` (was implicit). State machine of `mode` clarified in `references/cross-cutting/state-schema.md`.
- Migration risk: This is a UX change. Users who relied on auto-detach must now type `detach=true`. Communicate via DECISIONS.md and a one-time deprecation warning in Phase -1.0 echo line.
- Rollback: Single flag flip in Phase -1.1 default.

**C3. Verifier per-task → batch dispatch when ≥3 MID/HIGH tasks share files**
- Speculative. Defer to v2.23. Listed here for context only.
- Idea: If wave N has ≥3 MID/HIGH tasks with overlapping file sets, dispatch them as a single Batch API request with one Message each, ~50% cost reduction. But Phase 1 Step 3 is critical-path (blocks next wave), so SLA matters → only valid when wave is itself the last in the plan.
- Not in v2.22 scope.

**Acceptance for Phase C**:
- C1: Phase 2 Step 0 sweep latency for 30-LOW-task plan ≤ 5 min (Batch SLA), cost ≤ 50% of API-direct equivalent.
- C2: Bare invocation runs attached (verifiable by terminal not detaching). `detach=true` runs detached as before. State.json `mode` field reflects choice.

---

## 3. Sequencing & Branching

```
main
 │
 ├── v2.22-A (Phase A)              ← 1-2 days, low risk, ship first
 │     ├── A1: Plan Reviewer Haiku
 │     ├── A2: T1+T2 merge
 │     └── A3: cost helper updates
 │
 ├── v2.22-B (Phase B)              ← depends on A landed; 1 week
 │     ├── B1: dispatch_via_api.py
 │     ├── B2: per-role migration (5 PRs, one per role)
 │     ├── B3: scaffold extraction
 │     ├── B4: schemas
 │     ├── B5: AgentLens extensions
 │     ├── B6: Guardrail prose
 │     └── B7: cost-model update
 │
 └── v2.22-C (Phase C)              ← optional; 3-4 days; merge after B baseline stable for ≥1 week
       ├── C1: Batch API for final sweep
       └── C2: Self-Spawn simplification
```

Each phase ships independently. Phase B is the value driver. Phase A is its prerequisite for the T1+T2 merge but A1 (Haiku) is fully standalone.

---

## 4. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Anthropic API rate limit hit during a long run | M | H | B1 exponential backoff (3 retries) + ENV_BLOCKER ESCALATE. User can rerun with `dispatch_config.<role>=p` to fall back. |
| Haiku 4.5 misses a rubric BLOCKER that Sonnet would catch | L | M | A1 ships with `evals/plan-reviewer-rubric/` 20-plan eval comparing Haiku vs Sonnet verdicts. ≥18/20 agreement required to ship. |
| Cache miss rate higher than expected (scaffold drift) | M | M | B3 byte-stability linter at Phase 0 Step 7.5. Forensics: AgentLens `cache_hit_ratio` field exposes drift in dashboards. |
| Structured-output schema rejected by model (rare) | L | H | B4 schemas hand-written and unit-tested against fixture inputs in `scripts/test_dispatch_schemas.py`. CI runs on every B-phase PR. |
| Batch API SLA blown on C1 | L | L | C1 fallback to regular API with WARN — sweep is recovery-capable, no halt. |
| Self-Spawn UX regression (C2) | M | L | C2 deprecation warning in Phase -1.0 echo line for 2 weeks before flipping default. |

---

## 5. Out of Scope

- Migrating Implementer / Combined Reviewer off Agent tool. They benefit from in-session caching already and depend on Agent-tool semantics (model parameter, automatic SubagentStop hook firing).
- Switching to a non-Anthropic provider.
- Changing prompt content beyond the scaffold/payload split (B3) and the role-merge prompt (A2 → `references/transition-prompt.md`). All other prose stays.
- Restructuring `state.json` schema. New fields (`dispatch_config`, `cache_read_tokens`, `cache_creation_tokens`) are additive; existing readers ignore them.
- Replacing AgentLens with a different observability stack.

---

## 6. Validation

**Forensics queries to run pre/post v2.22**:
```bash
# Per-role mean dispatch latency
agentlens query --event kws-cme.dispatch_via_api \
  --group-by role --agg mean,wall_ms

# Cache hit rate per role
agentlens query --event kws-cme.dispatch_via_api \
  --group-by role --agg mean,cache_hit_ratio

# Cost delta v2.21 → v2.22
scripts/cost_compare.py \
  --baseline tmp/runs/v2.21.0/ \
  --candidate tmp/runs/v2.22.0/
```

**Eval baselines to refresh**:
- `evals/baselines/v2.22.0.json` (10-run regression on representative plan suite)
- `evals/plan-reviewer-rubric/v2.22-haiku-vs-sonnet.json` (A1 gate)
- `evals/transition-merge/v2.22-merge-vs-split.json` (A2 gate)

---

## 7. Open Questions

1. **Q**: Should `dispatch_config` be settable per-plan in a chain? **A (proposed)**: No — run-level only, matching v2.13 `implementer_model` precedent. Per-plan dispatch tuning is a v2.23 question.
2. **Q**: Cache TTL — ephemeral (5 min) or 1-hour beta? **A (proposed)**: Ephemeral for v2.22. 1-hour requires beta flag and risks API contract drift. Revisit after 30 days of v2.22.0 data.
3. **Q**: Self-Spawn (C2) UX — flip default vs. require explicit `attach=true`? **A (proposed)**: Flip default to attached with 2-week deprecation warning. The detach path is the surprising one in 2026 (everyone has tmux / nohup); the original auto-detach was a 2025 workaround.

---

## 8. Decisions Register (to be appended as phases ship)

| ID | Decision | Phase | Status |
|----|----------|-------|--------|
| D001 | Plan Reviewer migrates to Haiku 4.5 | A1 | proposed |
| D002 | T1 + T2 merge into single dispatch | A2 | proposed |
| D003 | `dispatch_via_api.py` is the single helper for all API-direct roles | B1 | proposed |
| D004 | Scaffold/payload split is byte-stability-linted at Phase 0 Step 7.5 | B3 | proposed |
| D005 | API errors do NOT fall back to `-p` (forbidden mixed-path retry) | B6 | proposed |
| D006 | Cache TTL stays ephemeral for v2.22 | open Q2 | pending |
| D007 | Self-Spawn default flips to attached in C2 with deprecation warning | C2 | proposed |

---

## 9. Done When

- All Phase A + B + C acceptance criteria met.
- `evals/baselines/v2.22.0.json` regression run passes (no new failures, ≥80% input-cost reduction confirmed).
- `JOURNAL.md` populated with per-phase ship dates, observed metrics, and any rollback events.
- `references/cross-cutting/state-schema.md` reflects the new `dispatch_config` and cost-ledger fields.
- SKILL.md Guardrails table updated with all new invariants (A1, A2, B6, C1, C2).
- One-page user-facing changelog at `docs/CHANGELOG.md` summarizes user-visible changes (Haiku Plan Reviewer, `dispatch_config` flag, C2 `detach=true` requirement if shipped).
