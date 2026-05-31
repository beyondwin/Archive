# v2.22 plan — Dispatch Optimization (Anthropic API Direct + Caching)

Implements `spec.md` Phases A, B, C. Each task block is executor-ready: explicit
Files, Acceptance Criteria with shell commands, risk tier, and method-audit
expectations.

Conventions:
- Risk tiers: LOW = lint/docs/state only; MID = code + tests; HIGH = guardrail
  or contract-changing edits to SKILL.md / cross-cutting references.
- All script tasks include unit-test files. TDD required (RED command in
  Acceptance Criteria).
- File paths are relative to skill root
  `/Users/kws/.claude/skills/kws-claude-multi-agent-executor/`.

Resource keys (per v2.21 Guardrail): tasks that mutate `SKILL.md` share
`**Resource Key:** skill_md` and will be serialized within a wave.

---

## Wave 1 — Phase A (Quick Wins)

### Task 1: Plan Reviewer migrates to Haiku 4.5

**Risk:** LOW
**Resource Key:** plan_reviewer_prompt

**Why:** Mechanical rubric workload (spec §2.A1). Haiku 4.5 is 3× faster, 5×
cheaper, with binary rubric items where judge variance is minimal.

**Files:**
- `references/plan-reviewer-prompt.md` — change model directive to `claude-haiku-4-5-20251001`
- `references/phases/phase-0-setup.md` — Step 6.5 prose: record `state.plan_review.model_used`
- `scripts/dispatch_plan_reviewer.py` (NEW) — encapsulate model-selection logic; reads from `state.dispatch_config.plan_reviewer_model` with default `claude-haiku-4-5-20251001`
- `scripts/test_dispatch_plan_reviewer.py` (NEW) — unit test: default model is haiku; override honored; model_used written to state

**Acceptance Criteria:**
```bash
# RED: test exists and fails before edits land
cd /Users/kws/.claude/skills/kws-claude-multi-agent-executor
python scripts/test_dispatch_plan_reviewer.py  # exits non-zero pre-fix

# GREEN
python scripts/test_dispatch_plan_reviewer.py  # exits 0
grep -q "claude-haiku-4-5" references/plan-reviewer-prompt.md
grep -q "model_used" references/phases/phase-0-setup.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`, RED + GREEN commands logged.

---

### Task 2: Merge Transition T1 + T2 into single combined dispatch

**Risk:** MID
**Resource Key:** transition_prompt

**Why:** Spec §2.A2. Saves ~50% wall time per compaction. Both produce
JSON results consumed sequentially today.

**Files:**
- `references/transition-prompt.md` (NEW) — combined prompt body invoking two tools: `verify_low_batch`, `update_phase_docs`
- `references/_schemas/transition_combined_result.schema.json` (NEW) — `{verify: {...}, docs: {...}}` shape
- `references/phases/phase-transition.md` — collapse T1 + T2 into "T1.2 Combined Transition Dispatch"; T3 unchanged
- `scripts/dispatch_transition_combined.py` (NEW) — orchestrator-facing helper; writes to `<orch_dir>/transition_results/<plan_idx>_<compaction_idx>.json`
- `scripts/test_dispatch_transition_combined.py` (NEW) — unit test with fixture sub-agent output covering both tools

**Acceptance Criteria:**
```bash
# RED
python scripts/test_dispatch_transition_combined.py  # exits non-zero pre-fix

# GREEN
python scripts/test_dispatch_transition_combined.py  # exits 0
jq -e '.tools | length == 2' references/_schemas/transition_combined_result.schema.json
grep -q "T1.2 Combined Transition Dispatch" references/phases/phase-transition.md
# T1 and T2 sections must no longer exist as separate steps
! grep -E '^## T1 |^## T2 ' references/phases/phase-transition.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 3: Cost helper supports combined-role dispatch

**Risk:** LOW
**Resource Key:** accumulate_cost
**Depends on:** Task 2 (transition prompt schema)

**Why:** Spec §2.A3. Combined T1+T2 dispatch needs single ledger row with
`by_task` key `<plan>::transition_<idx>::combined`.

**Files:**
- `scripts/accumulate_cost.py` — add `--combined-roles <comma-list>` flag; tags
  ledger row with `combined_roles: ["verify", "docs"]`
- `scripts/test_accumulate_cost.py` — extend with combined-role test case

**Acceptance Criteria:**
```bash
# RED
python scripts/test_accumulate_cost.py -k combined  # fails pre-fix

# GREEN
python scripts/test_accumulate_cost.py -k combined  # passes
python scripts/accumulate_cost.py --help | grep -q combined-roles
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

## Wave 2 — Phase B (API Direct, core)

### Task 4: `scripts/dispatch_via_api.py` skeleton + Plan Reviewer migration

**Risk:** MID
**Resource Key:** dispatch_via_api

**Why:** Spec §2.B1, B2. Plan Reviewer first because it has the highest cache
hit potential (identical scaffold every run) and lowest blast radius (1 call
per run, non-critical-path).

**Files:**
- `scripts/dispatch_via_api.py` (NEW) — full helper per spec §2.B1 signature
- `scripts/test_dispatch_via_api.py` (NEW) — fixture-driven unit tests covering: scaffold/payload split, `cache_control` injection, `tool_choice` enforcement, retry on 429/5xx, ENV_BLOCKER on hard failure, cost helper invocation, AgentLens emission
- `references/_scaffolds/plan_reviewer-scaffold.md` (NEW) — extracted scaffold per spec §2.B3
- `references/plan-reviewer-prompt.md` — refactor to `SCAFFOLD_BEGIN/END` + `PAYLOAD_BEGIN/END` markers (reassembly = original byte-for-byte)
- `references/_schemas/plan_reviewer_result.schema.json` (NEW)
- `references/phases/phase-0-setup.md` — Step 6.5: dispatch via `scripts/dispatch_via_api.py --role plan_reviewer` when `state.dispatch_config.plan_reviewer == "api"` (default in v2.22)

**Acceptance Criteria:**
```bash
# RED
python scripts/test_dispatch_via_api.py  # exits non-zero pre-fix

# GREEN
python scripts/test_dispatch_via_api.py  # exits 0
python scripts/dispatch_via_api.py --help | grep -q -- "--role"
jq empty references/_schemas/plan_reviewer_result.schema.json
# Reassembly byte-stability:
python scripts/validate_scaffold_split.py references/plan-reviewer-prompt.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 5: Scaffold byte-stability linter

**Risk:** LOW
**Resource Key:** scaffold_lint
**Depends on:** Task 4 (scaffold markers)

**Why:** Spec §2.B3. Drift breaks cache hits silently. Run at Phase 0 Step 7.5.

**Files:**
- `scripts/validate_scaffold_split.py` (NEW) — reads `references/<role>-prompt.md`, verifies `SCAFFOLD_BEGIN/END` + `PAYLOAD_BEGIN/END` markers, reassembles into original, fails if assembled != original
- `scripts/test_validate_scaffold_split.py` (NEW) — tests pass/fail cases with fixtures
- `references/phases/phase-0-setup.md` — Step 7.5 prose: invoke the linter for every role with markers; lint failure halts (ENV_BLOCKER)

**Acceptance Criteria:**
```bash
# RED
python scripts/test_validate_scaffold_split.py  # fails pre-fix

# GREEN
python scripts/test_validate_scaffold_split.py  # passes
python scripts/validate_scaffold_split.py references/plan-reviewer-prompt.md  # exits 0
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 6: Verifier batch (T1) migration to API direct

**Risk:** MID
**Resource Key:** verifier_batch
**Depends on:** Tasks 4, 5

**Why:** Spec §2.B2 priority 2. Shares `test_command` + plan excerpt across LOW
tasks in one batch → high cache hit.

**Files:**
- `references/verifier-prompt.md` — refactor to scaffold/payload markers (split: superpowers bootstrap + JSON schema + invariants → scaffold; task-specific files + commands → payload)
- `references/_scaffolds/verifier-scaffold.md` (NEW)
- `references/_schemas/verifier_result.schema.json` (NEW)
- `references/phases/phase-transition.md` — T1.2 Combined Transition (already merged in Task 2): dispatch via `dispatch_via_api.py --role verifier_batch` when `state.dispatch_config.verifier_batch == "api"`
- `scripts/test_dispatch_via_api.py` — extend with verifier_batch fixture

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_via_api.py -k verifier_batch  # passes
python scripts/validate_scaffold_split.py references/verifier-prompt.md  # exits 0
jq empty references/_schemas/verifier_result.schema.json
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 7: Transition combined dispatch (T1.2) migration to API direct

**Risk:** MID
**Resource Key:** transition_dispatch
**Depends on:** Tasks 2, 6

**Why:** Spec §2.B2 priority 3. Combined T1+T2 over API saves both subprocess
spawns per compaction.

**Files:**
- `references/transition-prompt.md` — refactor to scaffold/payload markers
- `references/_scaffolds/transition-scaffold.md` (NEW)
- `scripts/dispatch_transition_combined.py` — switch to delegating to `dispatch_via_api.py --role transition_combined`
- `scripts/test_dispatch_via_api.py` — add transition_combined fixture

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_via_api.py -k transition_combined  # passes
python scripts/validate_scaffold_split.py references/transition-prompt.md  # exits 0
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 8: Verifier per-task migration to API direct

**Risk:** MID
**Resource Key:** verifier_per_task

**Why:** Spec §2.B2 priority 4. Same `test_command` shared across tasks of a
plan → moderate cache benefit.

**Files:**
- `references/phases/phase-1-task-cycle.md` — Step 3 prose: dispatch via `dispatch_via_api.py --role verifier_per_task` when `state.dispatch_config.verifier_per_task == "api"`
- `scripts/test_dispatch_via_api.py` — extend with verifier_per_task fixture

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_via_api.py -k verifier_per_task  # passes
grep -q "verifier_per_task" references/phases/phase-1-task-cycle.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 9: Docs Updater (Phase + Final) migration to API direct

**Risk:** MID
**Resource Key:** docs_updater

**Why:** Spec §2.B2 priority 5. Final Docs Updater has low cache benefit
(runs once) but still gains latency from skipping `claude -p` wrapper.

**Files:**
- `references/docs-updater-prompts.md` — refactor both Phase and Final sections to scaffold/payload markers
- `references/_scaffolds/docs_updater_phase-scaffold.md` (NEW)
- `references/_scaffolds/docs_updater_final-scaffold.md` (NEW)
- `references/_schemas/docs_updater_result.schema.json` (NEW)
- `references/phases/phase-transition.md` — T1.2 (Phase Docs section): dispatch via API
- `references/phases/phase-2-finalization.md` — Step 1: dispatch via `dispatch_via_api.py --role docs_updater_final`

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_via_api.py -k docs_updater  # passes
python scripts/validate_scaffold_split.py references/docs-updater-prompts.md  # exits 0
jq empty references/_schemas/docs_updater_result.schema.json
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 10: Cost ledger fields for cache tokens

**Risk:** LOW
**Resource Key:** accumulate_cost

**Why:** Spec §2.B7. Messages API returns `cache_read_input_tokens` and
`cache_creation_input_tokens` separately; ledger needs both.

**Files:**
- `scripts/accumulate_cost.py` — recognize cache token fields; add `cache_read_tokens` and `cache_creation_tokens` to ledger row + `totals`
- `scripts/price_table.py` — verify `claude-haiku-4-5-20251001` rates present; add cache-read (10% of input) + cache-creation (125% of input) pricing rows
- `scripts/test_accumulate_cost.py` — fixture with cache fields; assert ledger row preserves them and totals aggregate correctly
- `references/cross-cutting/state-schema.md` — add `cache_read_tokens`, `cache_creation_tokens` to `cost_ledger.totals` schema

**Acceptance Criteria:**
```bash
python scripts/test_accumulate_cost.py -k cache  # passes
jq -e '.totals.cache_read_tokens' tests/fixtures/cost_ledger_post_v22.json
grep -q "cache_read_tokens" references/cross-cutting/state-schema.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 11: AgentLens dispatch_via_api event

**Risk:** LOW
**Resource Key:** agentlens_events

**Why:** Spec §2.B5. Per-dispatch observability for cache hit rate, wall_ms,
retries.

**Files:**
- `references/cross-cutting/agentlens-emit-sites.md` — register new event `kws-cme.dispatch_via_api` with field schema
- `scripts/dispatch_via_api.py` — emit event after each successful (or failed-after-retry) dispatch with `role`, `model`, `input_tokens`, `cache_read_tokens`, `output_tokens`, `cache_hit_ratio`, `wall_ms`, `retries`
- `scripts/test_dispatch_via_api.py` — assert event emitted with correct fields under fixture

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_via_api.py -k agentlens_emit  # passes
grep -q "kws-cme.dispatch_via_api" references/cross-cutting/agentlens-emit-sites.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 12: SKILL.md guardrail prose (Phase B)

**Risk:** HIGH
**Resource Key:** skill_md
**Depends on:** Tasks 4–11

**Why:** Spec §2.B6. Four new invariants must be visible in the Guardrails
table or they'll silently rot.

**Files:**
- `SKILL.md` — append 4 rows to Guardrails table: API-direct default; scaffold byte-stability; no `-p` fallback on API errors; mandatory `tool_choice`
- `SKILL.md` — add `state.dispatch_config` brief to per-plan-vs-run-level field split (it's run-level)
- `references/cross-cutting/state-schema.md` — full `dispatch_config` shape: `{plan_reviewer, verifier_batch, verifier_per_task, transition_combined, docs_updater_phase, docs_updater_final}` each enum `"p" | "api"`, default `"api"` in v2.22

**Acceptance Criteria:**
```bash
grep -c "API-direct dispatch" SKILL.md  # ≥ 1
grep -c "scaffold byte-stability" SKILL.md  # ≥ 1 (case-insensitive prose ok)
grep -c "tool_choice" SKILL.md  # ≥ 1
jq -e '.properties.dispatch_config' references/cross-cutting/state-schema.md 2>/dev/null || \
  grep -A 20 'dispatch_config' references/cross-cutting/state-schema.md | grep -q plan_reviewer
```

**Method audit:** `METHOD_AUDIT: tdd waived reason=docs-only-task`.

---

## Wave 3 — Phase C (Tail Cleanup, optional)

### Task 13: Batch API for Phase 2 Step 0 final sweep

**Risk:** MID
**Resource Key:** final_sweep

**Why:** Spec §2.C1. Non-blocking path tolerates 24h SLA; 50% cost cut.

**Files:**
- `scripts/dispatch_final_sweep_batch.py` (NEW) — submits Batch API request with one Message per LOW task; polls completion; on timeout (configurable, default 30 min) WARNs and falls back to per-task API dispatch
- `scripts/test_dispatch_final_sweep_batch.py` (NEW) — fixture-driven; covers submit, poll-success, poll-timeout-fallback paths
- `references/phases/phase-2-finalization.md` — Step 0 prose: dispatch via batch when `state.dispatch_config.final_sweep == "batch"` (default `"api"` in v2.22.0; flip to `"batch"` in v2.22.1)
- `references/cross-cutting/agentlens-emit-sites.md` — register `kws-cme.batch_timeout` event

**Acceptance Criteria:**
```bash
python scripts/test_dispatch_final_sweep_batch.py  # passes
python scripts/dispatch_final_sweep_batch.py --help | grep -q -- "--timeout"
grep -q "kws-cme.batch_timeout" references/cross-cutting/agentlens-emit-sites.md
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 14: Self-Spawn simplification (attached-by-default)

**Risk:** HIGH
**Resource Key:** self_spawn

**Why:** Spec §2.C2. UX change with 2-week deprecation warning before flipping
default.

**Files:**
- `references/phases/phase-minus-1-args-and-spawn.md` — Phase -1.1: bare invocation defaults to in-session run; `detach=true` triggers Self-Spawn; emit deprecation warning if neither passed for 2 weeks (controlled by `state.deprecation_warnings.attach_default`)
- `references/cross-cutting/state-schema.md` — add `"interactive_attached"` to `state.mode` enum
- `SKILL.md` Guardrails — update "Phase -1 self-spawn is the default" rule: now reads "Phase -1 self-spawn is opt-in via `detach=true` from v2.22.0; attached is default"
- `docs/CHANGELOG.md` (NEW or append) — user-visible note

**Acceptance Criteria:**
```bash
grep -q "interactive_attached" references/cross-cutting/state-schema.md
grep -q "detach=true" SKILL.md
test -f docs/CHANGELOG.md
grep -q "v2.22" docs/CHANGELOG.md
```

**Method audit:** `METHOD_AUDIT: tdd waived reason=docs-only-task`.

---

## Wave 4 — Evals & Baseline

### Task 15: Eval — Plan Reviewer Haiku vs Sonnet agreement

**Risk:** MID
**Resource Key:** evals

**Why:** Spec §4 risk row 2: Haiku might miss BLOCKERs Sonnet catches.
Gate: ≥18/20 agreement.

**Files:**
- `evals/plan-reviewer-rubric/v2.22-haiku-vs-sonnet.json` (NEW) — 20 plan fixtures with known BLOCKER/WARN verdicts
- `evals/plan-reviewer-rubric/run.sh` (NEW) — dispatches each fixture to both models, compares verdicts, asserts ≥18/20 match
- `evals/plan-reviewer-rubric/README.md` (NEW)

**Acceptance Criteria:**
```bash
test -f evals/plan-reviewer-rubric/v2.22-haiku-vs-sonnet.json
test -x evals/plan-reviewer-rubric/run.sh
# Dry-run shape check (does not call API in CI):
bash evals/plan-reviewer-rubric/run.sh --dry-run
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 16: Eval — Transition merge vs split parity

**Risk:** MID
**Resource Key:** evals

**Why:** Spec §6: verify combined dispatch produces identical verify+docs
output to split dispatch on 5 fixture compactions.

**Files:**
- `evals/transition-merge/v2.22-merge-vs-split.json` (NEW)
- `evals/transition-merge/run.sh` (NEW)

**Acceptance Criteria:**
```bash
test -f evals/transition-merge/v2.22-merge-vs-split.json
bash evals/transition-merge/run.sh --dry-run
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

### Task 17: Eval — Baseline regression v2.22.0

**Risk:** MID
**Resource Key:** evals
**Depends on:** Tasks 1–16

**Why:** Spec §9: 10-run regression on representative plan suite; cache hit
≥60%, input cost ≤20% of v2.21.

**Files:**
- `evals/baselines/v2.22.0.json` (NEW) — captures: per-role dispatch wall_ms mean, input_tokens mean, cache_hit_ratio mean, ESCALATE count, output quality scores
- `evals/baselines/README.md` — append v2.22 entry
- `scripts/cost_compare.py` (NEW) — compares two baseline JSONs and reports deltas

**Acceptance Criteria:**
```bash
test -f evals/baselines/v2.22.0.json
python scripts/cost_compare.py --baseline evals/baselines/v2.21.0.json --candidate evals/baselines/v2.22.0.json --check-cache-hit-min 0.60 --check-input-cost-max-ratio 0.20
```

**Method audit:** `METHOD_AUDIT: tdd applied`.

---

## Wave 5 — Documentation & Migration

### Task 18: Update HISTORY.md, decision log, README

**Risk:** LOW
**Resource Key:** skill_md

**Files:**
- `HISTORY.md` — append v2.22 entry summarizing Phase A/B/C deliverables
- `docs/decision-log.md` — index D001–D007 (per spec §8)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D001-haiku-plan-reviewer.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D002-transition-merge.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D003-dispatch-via-api.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D004-scaffold-byte-stability.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D005-no-p-fallback.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/decisions/D007-self-spawn-attached.md` (NEW)
- `docs/experiments/v2.22-dispatch-optimization/JOURNAL.md` — populate per-task ship dates as wave completes
- `docs/experiments/v2.22-dispatch-optimization/README.md` — overview

**Acceptance Criteria:**
```bash
grep -q "v2.22" HISTORY.md
test -f docs/experiments/v2.22-dispatch-optimization/decisions/D001-haiku-plan-reviewer.md
test -f docs/experiments/v2.22-dispatch-optimization/decisions/D005-no-p-fallback.md
test -f docs/experiments/v2.22-dispatch-optimization/README.md
```

**Method audit:** `METHOD_AUDIT: tdd waived reason=docs-only-task`.

---

## Execution Plan (wave / parallel grouping)

```
Wave 1 (Phase A, can be parallel; Task 3 depends on Task 2):
  Group 1.a: [Task 1, Task 2]    # different resource keys
  Group 1.b: [Task 3]             # serial after 2

Wave 2 (Phase B, mostly sequential due to shared resource keys):
  Group 2.a: [Task 4]                          # foundation
  Group 2.b: [Task 5]                          # depends on 4
  Group 2.c: [Task 6, Task 8]                  # different resource keys, can parallel
  Group 2.d: [Task 7]                          # depends on 2 + 6
  Group 2.e: [Task 9]                          # docs_updater isolated
  Group 2.f: [Task 10, Task 11]                # cost + agentlens, parallel
  Group 2.g: [Task 12]                         # HIGH: SKILL.md guardrails, gate

Wave 3 (Phase C):
  Group 3.a: [Task 13]
  Group 3.b: [Task 14]                         # HIGH: SKILL.md + UX

Wave 4 (Evals, mostly parallel):
  Group 4.a: [Task 15, Task 16]                # different resource keys
  Group 4.b: [Task 17]                         # depends on all prior

Wave 5 (Docs):
  Group 5.a: [Task 18]
```

Compaction points: end of Wave 1, end of Wave 2 (after Task 12), end of Wave 3,
end of Wave 4. Wave 5 is the final wave; Phase 2 finalization runs after.

---

## Cross-cutting global constraints (apply to every task)

1. Every new `scripts/*.py` includes a sibling `scripts/test_*.py` invoked
   directly (`python scripts/test_X.py`); use stdlib `unittest` to avoid pytest
   dependency.
2. Every `references/*-prompt.md` edit MUST preserve the `superpowers:using-superpowers`
   bootstrap instruction at the top.
3. Hooks under `<orch_dir>/hooks/` remain absolute-path referenced from
   `<worktree>/.claude/settings.json` (existing invariant; no change in v2.22).
4. AgentLens emit failures are `2>/dev/null || true` (existing invariant).
5. Cost helper invocation is mandatory after every dispatch (existing v2.16
   invariant; reinforced for new API-direct path in Task 4).
