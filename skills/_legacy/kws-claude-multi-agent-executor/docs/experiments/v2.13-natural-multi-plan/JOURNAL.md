# JOURNAL — v2.13 Natural-language args + multi-plan auto-chain

Chronological log.

---

## 2026-05-16

### Setup — design confirmed by user

User asked for two things and approved the recommended design:

1. Multi-plan should work without a separate `manifest=` arg — just pass `plan, plan2, plan3, ...` pairs.
2. Model selection (and a few other knobs) should be expressible in prose — "오푸스로 해줘" should set `implementer_model=opus`.

Brief design discussion happened in chat. The two features are independent but ship together because they both touch Phase -1's argument parsing layer and would otherwise create two near-identical breaking points in the skill.

### Design — argument parser surface area

The interactive parent at Phase -1 step a is the only place skill args are visible (Phase 0 in the headless child reads from state.json — established in v2.12). So both new features live there.

**Multi-plan detection:**
- Scan all `plan\d*=` keys. `plan=` is index 0; `planN=` is index N-1 (so `plan2=` is index 1 — matches the v2.12 plan2 convention).
- Pair each `planN=` with matching `specN=`. Missing `specN=` for an existing `planN=` halts.
- Gaps in the numeric sequence (e.g., plan and plan3 but no plan2) halt — likely a typo.
- N=1 (only `plan=`, no plan2+): exact v2.12 single-plan behavior. No `plan_chain` field written.
- N≥2: write `state.plan_chain = [{...}, {...}, ...]` with one entry per plan. Drop `plan2_state` (v2.13 replaces it).

**NL keywords:**
- Lexicon starts small (opus, sonnet, 오푸스, 소넷, 순차/sequential, interactive/대화형, low/mid/high risk + 위험도 변형).
- Scan only tokens that aren't recognized as `key=value` and don't contain path-like characters (`/`, `.`, `=`).
- Conflict matrix: explicit always wins. If explicit unset AND NL matches: NL wins. If NL contradicts itself (e.g., both "opus" and "sonnet"): halt with batched question.
- Echo back the resolved set before self-spawning so the user sees the interpretation in one line.

### Schema — minimal disruption

Single-plan runs keep the v2.12 schema bit-for-bit. The v2.12 benchmark continues to work without modification. Multi-plan introduces `state.plan_chain[]` and changes `state.active_plan` from a string ("plan1"/"plan2") to an integer index (0, 1, 2, ...) only when chain is in use. Resume protocol detects the chain by presence of `state.plan_chain` and dispatches accordingly. Legacy `state.plan2_state` is read-only for v2.12 state files (no migration; v2.13 doesn't write it).

### Open work this session

- SKILL.md patches (Phase -1 parsing, Phase 0 Step 7 init, Phase 2 Step -1 generalization, guardrails)
- ARCHITECTURE.md §5 schema update
- HISTORY.md v2.13 entry
- example invocations + advisor round

### ADVISOR REVIEW — round 1

Advisor flagged one BLOCKER and two minor issues:

🔴 **BLOCKER — implicit retrofit rule won't survive an LLM orchestrator pass.** Initial draft asked the orchestrator (an LLM following ~1500 lines of prose) to mentally rewrite every `state.tasks` / `state.task_summaries` / `state.quality_trend` / etc. reference under the active-tree rule when multi-plan. There are 30+ such references throughout SKILL.md. The advisor identified three specific large categories that would silently fail: (a) Phase 0 Step 5 baseline derivation, (b) Phase 1 Step 4 Agent Cleanup string-compare vs integer active_plan, (c) Phase Transition T1 docs-only pre-filter + T3 quality_trend append.

**Fix — Path B (advisor's recommended path):** introduced an explicit `<active>` placeholder defined once near the top of SKILL.md (right after Overview, before Phase -1). The placeholder expands to `state.plan_chain[state.active_plan]` for multi-plan, `state.plan2_state` for v2.12 legacy, top-level `state` otherwise. Then mechanically replaced `state.tasks` / `state.quality_trend` / `state.baseline` / `state.global_constraints` / `state.compaction_points` / `state.execution_plan` / `state.task_complexity` / `state.low_tasks_pending_verification` / `state.last_completed_task` / `state.plan_review` throughout the document with `<active>.foo`. Per-plan callsites are now ~30 places that reference `<active>.foo` explicitly; the rule lives at every site instead of asking the LLM to apply it from memory.

Also patched:
- Phase 0 Step 5 baseline → writes to `<active>.baseline`, top-level `state.test_command` stays run-level.
- Phase 1 Step 4 Agent Cleanup → "active_plan is an integer for multi-plan" called out explicitly so string-compare-against-"plan2" doesn't trap.
- Phase 2 Step 0 batch result path → `batch_final_p<active>.json` for multi-plan (consistent with Step -1 v2.13 path check).
- Phase 2 Step 1 Final Docs Updater → two-tier scope (per-plan covered already, chain-level summary added).
- Implementer prompt template → multi-plan-aware `task_summaries` and `shared_files` resolution.
- Monitor watcher script (Phase -1 step e′) → HAS_CHAIN dispatch, picks the right TASKS_FILTER for v2.13 / v2.12 legacy / single-plan.
- `scripts/validate_method_audit.py` → `_collect_task_trees` helper iterates every `plan_chain[*].tasks` for v2.13 runs. Smoke-tested with single-plan and chain JSON: single passes, chain correctly flags missing methods in plan_chain[1].

🟡 **Pass 2 ambiguity — `plan=A plan1=B` collision.** Not yet addressed (minor). Will halt with "Unknown argument: plan1=..." in Pass 1 since `plan1` isn't in the recognized-keys list — acceptable behavior for now; ADR if requested.

🟡 **No empirical validation possible until first real multi-plan run.** Accepted. Will dump state.json mid-run during the first chain execution and verify top-level vs plan_chain partition matches expectations.

### ADVISOR REVIEW — round 2

One BLOCKER + two minor:

🔴 **BLOCKER — Korean lexicon doesn't match the user's own example.** Python 3 `\b` is Unicode-aware; Hangul syllables are `\w`, so `오푸스로` is a single `\w+` token with no word boundary between `오푸스` and `로`. `re.search(r'\b오푸스\b', '오푸스로')` returns None. Every Korean example in `invocations.md` (3, 5, 11) would have silently failed despite being the headline UX demo. ASCII keywords were fine — only Korean was broken.

**Fix — Option C (advisor's recommendation):** introduced a particle-stripping step in Pass 3. The parser now:
1. Tokenizes by whitespace
2. For each non-key=value token, strips the longest matching Korean grammatical particle suffix once (priority list: 적으로, 에서, 으로, 적인, 적, 로, 을, 를, 이, 가, 의, 에)
3. Lowercases (ASCII)
4. Exact-matches against the lexicon

Wrote `bench/nl_parser_reference.py` as the authoritative implementation that the SKILL.md prose interpretation must match, and `bench/test_nl_parser.py` covering all 11 examples from `invocations.md`. Ran the test suite — all 11 PASS (7 happy-path echo matches + 4 expected-halt matches). The Korean headline cases (오푸스로, 순차적으로, 소넷으로, etc.) now resolve correctly. Empirical validation discipline matched v2.12's AC-simulation discipline.

Also added: `plan1=` is now an explicit halt key (disambiguates from `plan=`) so users get a helpful error rather than silent ambiguity.

🟠 **`<task_path_prefix>` substitution rule** in Phase 2 Step 1.5 method-audit FAIL message — only covered plan1/plan2 string cases. **Fix**: added v2.13 multi-plan branch (`state.plan_chain[<N>].tasks` with N being the index that owns the failing task; list each prefix when failures span plans).

🟡 **invocations.md regression coverage** — recommended treating examples as regression fixtures. Done — `test_nl_parser.py` will fail in CI / on demand if anyone changes the lexicon without updating both. Smoke-run integrated into the experiment workflow.

After round 2 the v2.13 surface is ready to ship. No empirical signal possible until a real multi-plan chain runs; the parser correctness is locked down via the test fixtures.

---

## On close-out

(Filled after the v2.13 patch lands on main and a real multi-plan run is executed.)
