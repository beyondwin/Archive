# Skill History — kws-claude-multi-agent-executor

> **한글 TL;DR**: 이 파일은 영어 원본으로 유지됩니다. 시간 고정 버전 기록 + 실험 인덱스가 본체이며, 재작성하면 사실 왜곡 위험이 있어 그대로 두는 게 안전. **무엇을 찾나요?**
> - 버전 간 변경 (예: v2.8 → v2.9) → §1 "Version timeline"
> - 어떤 영역이 언제 개선됐나 → §2 "Improvement areas"
> - 실험과 그 결과 → §3 "Experiment index"
>
> 한글 설계 배경은 [`docs/design-decisions.md`](./docs/design-decisions.md), 결정 인덱스는 [`docs/decision-log.md`](./docs/decision-log.md).

A two-axis summary of where this skill came from and what changed:

- **§1 Version timeline** — chronological version notes
- **§2 Improvement areas** — grouped by topic, with which versions touched each

Source of truth for skill behavior: `SKILL.md` (current version in frontmatter).
This file is for *humans navigating the history*.

Update protocol: see `AGENTS.md` ("Experiment & history record-keeping").

---

## §1 Version timeline

### v2.15 — Context engineering (2026-05-16)

Three additive features for context efficiency on large plans:

- **C1 — Tiered spec injection (`spec_manifest`):** new `scripts/build_spec_manifest.py` parses markdown spec headings (stdlib only). Phase 0 Step 3.7 builds the manifest at boot; Step 6 computes `task_to_sections` per task (from explicit `**Spec Refs:**` blocks or Files-title heuristic, with `["*"]` full-spec fallback). Phase 1 Step 1 Implementer prompt builder replaces subjective spec curation with deterministic per-task slicing. Plan Reviewer gains 3 new rubric items (`spec_manifest_invalid_ref` BLOCKER, `spec_manifest_fallback_used` WARN, `spec_manifest_unused_section` WARN). Spec-edit branch recomputes manifest. SPEC_BLOCKER fallback re-dispatches with full spec under `manifest_fallback=full_spec_on_blocker`.
- **C2 — Decisions register:** new per-plan `decisions_register` accumulates `key_decision` entries at Phase 1 Step 4 (substep 2.3). Implementer prompt receives `## Project decisions so far` block; Combined Reviewer flags `decision_conflict` as `QUALITY_ISSUE` (not SPEC). Atomic projection to `<worktree>/.orchestrator/DECISIONS.md` at each Phase Transition T3 and at Phase 2 Step 1 (union across plans). Included in F1 archive.
- **C3 — Token-based Resume Chain trigger:** new run-level `state.context_budget` (top-level, defaults `effective_input_budget=170000`, `threshold_ratio=0.60`, `threshold_tokens=102000`). Chain trigger fires when `session_input_tokens (input_tokens − cached_read_tokens) ≥ threshold_tokens` OR legacy floor (`compactions ≥ 2 AND completed ≥ 8`). Additive — never replaces legacy. `chain_trigger_eval` telemetry event emitted at every Phase Transition T3 for trigger-lift analysis. Args: `context_budget=<int>`, `context_threshold=<float>`, `manifest_fallback=<value>`.

Goals: G1 (≤0.50 median Implementer input-token ratio vs v2.14 on ≥10KB specs), G2 (cross-task convention drift to <1/30 tasks), G3 (no quality decline across chain handoffs), G4 (token trigger fires before legacy on 30+ task plans).

A/B measurement template at `docs/experiments/v2.15-context-engineering/findings/v2.14-vs-v2.15-tokens.md`; journal at `docs/experiments/v2.15-context-engineering/JOURNAL.md`.

### v2.14 — Forensics & cost (2026-05-16)

Bundle of four forensic/observability features that all share the same axis: making post-run state inspectable, queryable, and budget-aware. None of them change Orchestrator or sub-agent logic during a run — they all act at run boundaries (close-run, post-task) or as out-of-band read-only tooling.

- **F1 — Archive `.orchestrator/` to user-local store after close-run.** When a run finishes (close-run path), the entire `.orchestrator/` directory is copied to `~/.claude-multi-agent-executor/archive/<run-id>/` so that subsequent `git clean` / branch deletion / worktree teardown does not vaporize the audit trail. A `redact_archive.py` helper strips obvious secrets (API keys, tokens, env-style `KEY=value` lines matching well-known patterns) before archival; redaction is best-effort, not a security boundary — see `docs/experiments/v2.14-forensics-and-cost/spec.md §F1` for the exact regex set and the §F1.5 clarification on anchor handling.

- **F2 — Cost ledger + budget cap.** Every sub-agent dispatch records token usage to `cost_ledger` (broken down `by_task`, `by_role`, `by_model`, and `totals`) using `scripts/price_table.py` for $/token conversion. A new run-level `budget_cap_usd` arg + `budget_action` (`warn` | `halt`) lets the Orchestrator stop dispatching new sub-agents once cumulative cost exceeds the cap. Price table is a flat dict keyed by model id; update on Anthropic price changes.

- **F3 — HTML run report.** `scripts/render_html_report.py` runs at Phase 2 Step 3 (post-run docs phase) and produces a single-file `report.html` summarizing tasks, durations, cost, escalations, and per-task verification evidence. Pure templating, no LLM, no external deps beyond stdlib. Designed to be opened from the archive long after the worktree is gone.

- **F4 — Query scripts.** `scripts/query_state.sh` and `scripts/query_run.sh` are no-LLM read-only `jq`-based query helpers. `query_state.sh` queries the live `.orchestrator/state.json` of an in-progress run; `query_run.sh` queries an archived run by `<run-id>` against the user-local archive (F1). Both expose the same query verbs (`tasks`, `cost`, `escalations`, `timeline`) so muscle memory carries across live/archived inspection.

Acceptance signal for the bundle: all 15 tasks (`task_0`…`task_14`) green, plus the spec clarification recorded for `task_6` regex anchor in `docs/experiments/v2.14-forensics-and-cost/spec.md §F1.5`.

### v2.13 — Natural-language args + multi-plan auto-chain (experiment branch, 2026-05-16)

**Status**: Ships on `experiment/v2.13-natural-multi-plan` only — NOT yet merged to main. Awaiting a real multi-plan run + advisor sign-off before promotion.

Two invocation-UX features ship together because both touch Phase -1's argument parsing layer:

1. **Multi-plan auto-chain.** Users can pass `plan=A spec=A.spec plan2=B spec2=B.spec plan3=C spec3=C.spec …planN=…` and the skill auto-chains them in numeric order. No `manifest=` arg required; no separate manifest file. Schema generalizes v2.12's `plan2_state` (single nested object) to `plan_chain[]` (array) when N≥2 plans are provided. Single-plan invocations keep the exact v2.12 schema (no `plan_chain` field, top-level `state.tasks`). Phase 2 Step -1 Cross-Plan Trigger generalizes from "swap to plan2" to "advance active_plan from i to i+1 if next entry exists and current plan finished cleanly".

2. **Natural-language keyword lexicon.** Users can write `오푸스로 순차적으로 진행해줘` (or `use Opus, sequential`) and the skill parses the keywords:
   - `opus` / `오푸스` → `implementer_model=opus`
   - `sonnet` / `소넷` → `implementer_model=sonnet`
   - `순차` / `sequential` / `직렬` / `시리얼` → `parallel=off`
   - `대화형` / `interactive` → `mode=interactive`

   Explicit `key=value` always wins; NL only fills unset keys. Conflicts halt with a batched question — never silent disambiguation. False-positive guard: tokens with `/`, `.`, `=`, or backtick neighbors are excluded from NL scanning, so plan paths containing model names don't trigger.

The lexicon is intentionally small (4 keys) and additive only; future expansions require an ADR under the v2.13 experiment dir.

**Echo line:** Phase -1.0 prints one mandatory summary line to the interactive parent's stdout before any other work, showing the parsed plans count, each setting's resolved value, and the source (`explicit` / `NL '<word>'` / `default`). This is the user's checkpoint before headless self-spawn detaches.

**Schema additions (additive — no migration needed):**
- `state.plan_chain: [...]` — present only when multi-plan; each entry has `{index, plan_path, spec_path, status, blocked_until, baseline, tasks, task_summaries, quality_trend, risk_levels, task_complexity, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review}`.
- `state.active_plan` becomes an integer (0, 1, 2, ...) when `plan_chain` is in use; remains the v2.12 string (`"plan1"` / `"plan2"`) for legacy and single-plan runs.
- Verifier/Docs Updater result files under `.orchestrator/{verifier,docs}_results/` carry a `_p<index>` suffix in multi-plan runs.

**Backward compatibility:** the v2.12 single-plan schema is preserved bit-for-bit. The v2.12 implementer-model benchmark (`docs/experiments/v2.12-implementer-opus-vs-sonnet/bench/`) runs unchanged. Legacy v2.12 two-plan state files (with `plan2_state` field) are still readable via the dedicated "v2.12 legacy path" branch in Phase 2 Step -1; v2.13 never writes new `plan2_state` fields.

Companion experiment artifacts under `docs/experiments/v2.13-natural-multi-plan/`:
- `decisions/D001-nl-lexicon-scope.md` — why the lexicon stays small and additive only
- `decisions/D002-plan-chain-schema.md` — why single-plan keeps v2.12 schema while multi-plan introduces `plan_chain[]`
- `examples/` — sample invocations with their parsed-args echo outputs

### v2.12 — Implementer model selection (experiment branch, 2026-05-16)

**Status**: Ships on `experiment/v2.12-implementer-opus-vs-sonnet` only — NOT yet merged to main. Awaiting findings from the 6-run A/B comparison before promotion.

Adds an optional skill argument `implementer_model=<opus|sonnet>` (default `sonnet`) so the Implementer sub-agent can be dispatched on Opus or Sonnet without modifying the rest of the pipeline. Reviewer and Verifier remain on Sonnet for judge consistency (ADR D001 in `docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/`).

State schema addition: `state.implementer_model = {"used": "<sonnet|opus>", "default": "sonnet"}`. The `default` field records the contemporaneous skill default (always `"sonnet"` in v2.12) for reproducibility — distinct from `used`, which records what actually ran.

Critical propagation detail: the arg is parsed in the **interactive parent** (Phase -1 step b or Phase 0 Step 7 under `mode=interactive`). The headless child `claude -p` only sees the headless prompt text, NOT the original skill args — so it reads `state.implementer_model` from the minimal state.json the parent wrote, never re-parsing. This propagation path is the most likely silent-failure mode if extended in future; the relevant guardrail in SKILL.md spells it out explicitly.

Companion experiment artifacts under `docs/experiments/v2.12-implementer-opus-vs-sonnet/`:
- `bench/spec.md` + `bench/plan.md` — 6-task `flagset` benchmark, deliberately partitioned 2× SMALL / 2× MEDIUM / 2× LARGE so per-bucket Δ is measurable
- `bench/aggregate.py` — stdlib-only multi-run aggregator (per-arm summary, per-complexity breakdown, Δ Opus−Sonnet, optional CSV)
- `bench/repo-skeleton/` — drop-in starting repo for the benchmark
- `RUN.md` — end-to-end procedure for 6 runs + collection

Backward compatible. Old state.json without `implementer_model` is interpreted as `{"used": "sonnet", "default": "sonnet"}` by aggregate.py and the resume protocol.

### v2.11 — Method audit and codex-cross-pollinated hardening (2026-05-14)

Five features, drawn from sibling `kws-codex-plan-executor` learning-log review (commit `1d10f13`) plus an MAE-internal gap analysis:

1. **Phase Method Audit** — `state.tasks.<id>.method_audit = {required, applied, missing, waived}`. Validated at Phase 2 Step 1.5 by `scripts/validate_method_audit.py` before close-run. SubagentStop hook gates Implementer output. Closes the gap between MAE's *required* TDD / review / verification disciplines and actual *validation* of them.
2. **Learning-log outcome coherence** — `scripts/append_learning_event.py close-run` now rewrites the matching `index.jsonl` row's `outcome` atomically. New `resolve-outcome` subcommand returns the authoritative outcome (final.json > meta.json > index.jsonl).
3. **ENV_BLOCKER triage categories** — five named root-cause buckets (`docker_oom`, `gradle_daemon_disappearance`, `gradle_metaspace`, `node_heap_oom`, `service_unreachable`) added to `references/escalation-playbook.md`. Recorded as optional `root_cause_category` on `verification_failure` learning events.
4. **Local-env preflight** — new Phase 0 Step 4.7 detects unfilled `*.example` / `*.template` / `*.dist` counterparts and stale dependency manifests. Records warnings to `state.preflight_warnings`; never halts, never auto-copies.
5. **Resource-key serialization** — plan tasks may declare `**Resource Key:** <slug>`; Phase 0 Step 6 partition forces same-key tasks into different parallel groups within a wave. Plan Reviewer (Step 6.5) emits a WARN on collisions.

Backward compatible. No state-schema breaking changes; new fields are additive.

### v2.10.2 — Mandatory sub-agent superpowers bootstrap + TDD enforcement (2026-05-14)

Prompt-contract hardening after observing Implementer tasks rationalizing away
`superpowers:test-driven-development` under the old SMALL-task loophole.

- Every sub-agent prompt template now starts with
  `Skill("superpowers:using-superpowers")` so fresh Agent-tool and headless
  dispatches do not depend on parent-session skill state.
- Implementer TDD is no longer gated by task size. SMALL/MEDIUM/LARGE now
  affects tool budget and routing only; executable implementation work must
  invoke `Skill("superpowers:test-driven-development")` and report RED/GREEN
  evidence.
- Docs Updater prompts now invoke
  `Skill("superpowers:verification-before-completion")` before reporting DONE
  or committing documentation changes.
- `evals/check_skill_contract.py` rejects missing `using-superpowers`
  bootstraps, size-gated Implementer TDD, and docs updater completion without
  verification skill grounding.

### v2.10.1 — Cross-run isolation + polite-stop invariant (2026-05-14)

Patch release prompted by a deep read of the `oh-my-claudecode` project
(33k stars; Yeachan-Heo). Filtered ~15 candidate patterns down to three
zero-cost, zero-risk additions; all four "fits but needs measurement"
candidates were moved to `docs/deferred-candidates.md` with explicit
revisit triggers.

Three changes, all in `SKILL.md`:

- **Phase 0 Step 1.5 (NEW): Cross-run isolation checks**
  - **(a) Mode exclusivity**: enumerate worktrees of this skill; if any has a
    live `headless.pid` AND no `HEADLESS_DONE.txt` / `HEADLESS_HALTED.txt`,
    halt with a clear message. Concurrent runs on the same source repo can
    race on git fetches, the user-local learning log, and parent-repo branch
    namespace — fail-fast is cheaper than debugging the race.
  - **(b) Orphan-worktree report (advisory, NOT auto-delete)**: list orphan
    worktrees (no state.json AND mtime > 7d) for user inspection. We do
    not auto-delete because such a worktree may hold uncommitted manual
    debugging work; the user must decide.
  - **Phase -1 self-spawn**: Step (a) now runs Phase 0 Steps `1, 1.5, 2, 2.5`.
  - **Headless resume**: `mode == "headless_pending"` skip list extended to
    include Step 1.5 (the freshly-written `.orchestrator/headless.pid`
    would self-block the mode-exclusivity check).

- **Invariants table: "Polite-stop anti-pattern is forbidden"** — names the
  failure mode that the existing `<<HEADLESS_KWS_ORCHESTRATOR>>` mechanism
  guards against. Inspired by `ralph/SKILL.md`'s explicit callout. A
  sub-agent returning PASS is a checkpoint inside the loop, never a
  reporting moment. This is a documentation-level invariant — the mechanism
  already exists; the change makes the failure mode legible so future SKILL.md
  edits cannot silently regress it.

- **Invariants table: "Cross-run isolation is enforced"** — documents the
  Phase 0 Step 1.5 contract for future readers.

Why now: the v2.10.0 ship is a natural point to apply 3 small
documentation/setup hardenings before the v2.10 `context_health` corpus
starts being analyzed. Pure-prose changes, no schema/contract drift, no
new sub-agent prompts.

Considered but deferred (all four moved to `docs/deferred-candidates.md`):

- **Plan Reviewer pre-mortem sub-step (OMC `critic` agent)** — genuine gap
  at Plan side, but increases Plan Reviewer output length and Orchestrator
  context. v2.10 `context_health` data is the right tool to measure this;
  premature ship would violate our own Goodhart guard.
- **AI slop cleaner post-PASS pass (OMC `ai-slop-cleaner` skill)** —
  catches duplicate logic / dead wrappers that the existing
  `PostToolUse` hook misses, but adds a sub-agent dispatch. Trigger:
  ≥3 `successful_workaround`/`recurring_issue` events naming
  Implementer-introduced dead helpers.
- **Haiku tier for LOW-risk single-file tasks (OMC tiered executor)** —
  cost-attractive but speculation; revisit after v2.10 corpus shows
  LOW tasks have acceptable verifier_retry distributions on Haiku.
- **User-configurable thresholds (OMC `.omc/omc.jsonc`)** — directly
  contradicts our Goodhart guard. SPEC/QUALITY thresholds were calibrated
  against the P6 eval suite; per-run override is not a feature, it is a
  measurement-destroying knob.

Explicit rejects (will not revisit absent fundamental problem-shape change):

- Tournament selection / approach-family taxonomy / plateau circuit-breaker
  (OMC `self-improve`) — different problem shape (N candidates per round
  vs. our straight-line single-plan execution).

### v2.10.0 — `context_health` passive observation (2026-05-14)

Adds an 11th event type `context_health` to the learning log. **Observation-only**:
no thresholds, no actions, no control-flow changes. Counters captured at two
emit points:

- **Phase Transition T3** — after each compaction completes and state is written.
- **Resume Chain handoff** — chained orchestrator emits one snapshot after
  `append-session-id` succeeds, marking the pre/post-handoff boundary.

Required `context` fields: `compaction_index`, `completed_tasks_count`,
`resume_chain_handoffs`. Optional: `risk_distribution`, `verifier_retry_total`,
`review_retry_total`, `quality_trend_mean`, `drift_signals[]`.

Why this exists:

- User-raised observation gap: "the orchestrator does not log how well its own
  context is being managed." Compaction events, chain handoffs, dispatch
  counts are introspectable from state.json but never observed cross-run.
- Goodhart's-law concern dominates: imposing thresholds before we have
  empirical distributions risks miscalibrating early. v2.10 collects data;
  v2.11+ may add behavioral consequences after ≥ 2 weeks of real-run data.

Open questions deferred to follow-on experiment
(`docs/experiments/v2.10-context-health/`):

- Which counter best predicts execution quality degradation across compactions?
- Is `resume_chain_handoffs > N` actually correlated with regression risk, or
  with plan length only (confounder)?
- Should `quality_trend` rolling mean become a `drift_signal` automatically?

The full active-management proposal (forced compaction, dispatch throttling,
mid-task summarization injection) remains in `docs/deferred-candidates.md`.
Re-rank after data is in.

Changes in this version:

- `scripts/append_learning_event.py` — `VALID_EVENT_TYPES` gains `context_health`;
  `SKILL_VERSION` bumped to `2.10.0`.
- `references/learning-log.md` — 11th row in event-type table + dedicated
  "passive observation contract" section.
- `evals/check_skill_contract.py` — `EVENT_TYPES` extended; message updated to
  "all 11 event types".
- `evals/check_learning_log.py` — new check 16 verifies `context_health`
  accepted with `severity=low` and orchestrator role.
- `SKILL.md` — Phase Transition Step T3 gains emit substep; Resume Chain
  chained-orchestrator startup gains snapshot after `append-session-id`;
  invariants table gains Goodhart's-law guard.

### v2.9.0 — Reviewer Spec Coverage Walk (2026-05-14)

Inserts a deterministic "Spec Coverage Walk" pass into
`references/reviewer-prompt.md`, requiring the Combined Reviewer to
emit a `SPEC_COVERAGE_WALK:` block before scoring. The walk has two
ordered sub-steps:

- **Sub-step A** — Enumerate stated spec bullets (happy-path examples,
  explicit error-case bullets, Notes constraints) with a strict row
  template `"<frag>" :: <file>:<line> | NOT FOUND | PARTIAL`.
- **Sub-step B** — Adversarial generation for spec meta-rules. For each
  meta-rule (sentences containing "strict", "reject", "anything else",
  etc.), generate ≥3 adversarial inputs not explicitly listed in the
  spec, drawn from at least these classes: repeated-segment variants,
  ordering/casing/whitespace edges, format combinations the spec
  implicitly excludes.

Why this exists:
- v2.7 F002 documented a Reviewer miss rate ~75% on `parse_duration("30m20m")`
  ValueError. Root cause: Sonnet's regex/grammar instinct read the spec
  as "natural language about non-repeated units" and never explicitly
  tested whether `30m20m` was rejected anywhere in the implementation.
- The pre-write analysis (v2.9 D001 §Question 3) showed enumeration of
  stated bullets alone would not surface `30m20m` — the case is covered
  only by the spec's meta-rule "strict validation of the grammar."
  Adversarial generation from meta-rules is the critical mechanism.

Empirical validation (T5, n=4 reps on fixture 08):
- `30m20m` rejection rate: F002 baseline ~25% → v2.9.0 **100% (4/4 reps)**.
- 8 of 8 Reviewer invocations across the 4 reps emitted `SPEC_COVERAGE_WALK`
  and explicitly included a `30m20m` row.
- SPEC_SCORE mean 0.997 (no false-positive `implementer_omitted` flags).
- v2.8.1 adherence verified: 4/4 reps with markers + run dirs created.

Combined intervention attribution: spec-clarification (fixture 08 yaml
patch — explicit "unit may appear at most once" note) is the biggest
single contributor; the walk makes the consideration deterministic and
reproducible. Without the walk, the spec-clarification result would
still depend on whether the Reviewer happens to scan for the case.

Out of scope (deferred candidates):
- Multi-perspective Reviewer dispatch (omc Team pattern). Single-pass
  enumeration solved the F002 case; multi-perspective is candidate work
  for v2.10+ only if a non-fixture-08 failure surfaces that requires it.
- Walk pattern extension to Verifier (acceptance-criteria coverage walk).
  Deferred — Verifier failure rate not measured at this granularity.

See `docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md`
for the full ship analysis.

### v2.8.1 — Step 7.5 enforcement (MANDATORY framing + adherence marker) (2026-05-13)

Empirical fix for the adherence gap found in v2.8 F001 Smoke B: 47 of 47
Bash invocations in a fixture-08 run skipped the learning-log helper
despite SKILL.md instructing it. Root cause: Step 7.5 under heavier
contextual load (multi-task plans) was read as advisory rather than
mandatory.

Changes:
- SKILL.md Step 7.5 heading promoted to MANDATORY; "DO NOT SKIP" framing
  added. Stronger imperative language reused from worktree-creation
  Phase 0 checkpoints.
- Helper invocation block now emits `LEARNING_LOG_INIT: RUN_ID=<id>` on
  success and `LEARNING_LOG_INIT: SKIPPED (...)` on shell-level failure.
  These markers surface in run.jsonl and enable post-run adherence audit.
- `2>/dev/null` removed from the init-run call — helper stderr now visible
  if the script breaks.
- `evals/run.sh` now greps run.jsonl for the `LEARNING_LOG_INIT:` marker
  after each fixture and reports `learning_log_adherence: yes|no` plus
  marker count. Non-blocking; observability-only.
- `evals/check_skill_contract.py` gains an 18th check (`skill_md_v281_mandatory_framing`)
  asserting the MANDATORY / DO NOT SKIP / LEARNING_LOG_INIT tokens are
  present in SKILL.md.

What this does NOT fix:
- Adherence is still prose-based (no PreToolUse hook). A determined
  skipping is still possible. The marker + eval check make it visible
  rather than silent. Hook-based enforcement is candidate work for v2.10+.
- v2.9 (Reviewer Spec Coverage Walk) is unaffected by this change. The
  walk's measurement infrastructure can now rely on the learning log
  firing for multi-task plans.

### v2.8 — Learning log + review-side superpowers Skill calls (2026-05-13)

Adds a user-local per-run sharded learning log so notable boundaries
(reviewer WARN/FAIL, verifier FAIL, sub-agent ESCALATE, recurring issues,
parallel dispatch failures, successful workarounds, actionable completion
learnings) can drive future skill improvements. Sibling pattern to
`kws-codex-plan-executor`'s learning log, adapted for the Claude Code
runtime.

Key changes:
- New `scripts/append_learning_event.py` with 4 idempotent subcommands
  (`init-run`, `append`, `close-run`, `append-session-id`).
- New `references/learning-log.md` reference doc.
- New `evals/check_learning_log.py` (16 deterministic checks) and
  `evals/check_skill_contract.py` wired into `evals/run.sh` as preflight.
- SKILL.md Phase 0 Step 7.5 / Phase 1 Step 3.5 / Phase 2 Step 2 / Escalation
  Protocol / Resume Chain instrumented for lifecycle calls.
- Single-writer contract: orchestrator only — sub-agents write candidate
  JSON files under `<worktree>/.orchestrator/learning_events/`.
- Resume Chain handoff preserves `MAE_LEARNING_RUN_ID` via env propagation
  and calls `append-session-id` (NOT `init-run`).
- Review-side superpowers Skill invocations added:
  - Plan Reviewer → `Skill("superpowers:writing-plans")`
  - Reviewer → `Skill("superpowers:requesting-code-review")`
  - Verifier → `Skill("superpowers:verification-before-completion")`
- ARCHITECTURE.md §14 Learning Log Contract added.
- All helper calls wrapped to fail silently — observability never blocks
  plan execution.

Records: `docs/experiments/v2.8-learning-log/`
Branch: `codex/executor-learning-log`

### v2.7 — Quality-mode experiment (2026-05-13)
**Branch only** — not merged to `main`. **Negative result** on quality_plus mode.

Hypothesis: best-of-3 Opus implementers + Opus judge would improve MID-task
output quality. Outcome: balanced v2.6.0 on a realistic-spec MID fixture
hits 0.95 rubric pass_rate with zero variance across 3 reps. Ceiling for
quality_plus is +0.05 max and 3/3 reproducible misses mean best-of-N
wouldn't discriminate.

Infrastructure built during the experiment is worth merging independently
(see §2 Evaluation harness).

Records: `docs/experiments/v2.7-quality-mode/`
Branch: `feature/v2.7-quality-mode-experiment`

### v2.6.0 — Eval-harness stabilization (2026-05-12)
- Eval harness fixes (Fix A, Fix B, isolation)
- Worktree path coverage
- v2.6.0 baseline JSON captured
- P6 eval suite infrastructure
- Commits: `80c0c39`, `c9ab406`, `ffe45fd`, `31308f9`, `b16e7ab`

### v2.5.x — Hooks / preflight / scoring (estimated)
Per `DESIGN-v2.5.md`:
- P1: Native Claude Code hooks for gate enforcement
- P3: Plan Reviewer preflight sub-agent
- P4: Generator-Verifier 0.0–1.0 scoring (replaces binary PASS/FAIL)
- P5: Effort-scaling rules in Implementer prompts (SMALL/MEDIUM/LARGE buckets)

### v2.4.0 — Canonical orchestrator-worker (2026-05-08)
- Anthropic-canonical Opus orchestrator + Sonnet workers
- git worktree isolation
- `state.json` external memory
- Risk-tiered verification (LOW batch, MID/HIGH per-task)
- P2: Wave-parallel sub-worktree dispatch for independent tasks
- Skill added to the executor skill inventory

---

## §2 Improvement areas

### Orchestration topology
Opus Orchestrator + Sonnet workers (Implementer / Reviewer / Verifier / Documenter / Plan Reviewer).

| Version | Change |
|---------|--------|
| v2.4.0 | Established canonical orchestrator-worker pattern |
| v2.5.x | Added Plan Reviewer preflight (P3) |
| v2.7 (proposed, deferred) | Best-of-N + Opus judge for MID/HIGH tasks (D008 design preserved, not implemented — see v2.7 findings) |

### Risk tiering & effort scaling
LOW/MID/HIGH risk tiers control verifier dispatch, effort bucket, and (proposed) model selection.

| Version | Change |
|---------|--------|
| v2.4.0 | LOW = batch verifier; MID/HIGH = per-task verifier |
| v2.5.x | P5: SMALL/MEDIUM/LARGE effort buckets per task complexity |
| v2.7 (deferred) | quality_alpha proposal: LOW→MID floor; quality_plus: MID also gets best-of-N |

### Quality scoring (Combined Reviewer)
| Version | Change |
|---------|--------|
| pre-2.5 | Binary PASS/FAIL |
| v2.5.x | P4: 0.0–1.0 SPEC_SCORE + QUALITY_SCORE; PASS/WARN/FAIL tier |
| v2.7 (deferred) | Threshold raise (0.92 / 0.85) for quality mode |

### Hooks / safety
| Version | Change |
|---------|--------|
| pre-2.5 | Manual orchestrator-enforced gates |
| v2.5.x | P1: Native PostToolUse + SubagentStop hooks for debug-artifact scan and STATUS sanity |

### Plan validation
| Version | Change |
|---------|--------|
| v2.5.x | P3 Plan Reviewer preflight (mechanical audit before Phase 1) |

### Parallel dispatch
| Version | Change |
|---------|--------|
| v2.4.0 | Sequential per task |
| v2.5.x → v2.6.0 | P2: Wave-parallel sub-worktrees for independent tasks within a wave |

### Evaluation harness
| Version | Change |
|---------|--------|
| v2.5.x | P6: `evals/` directory, fixtures 01–07, judge.md, run.sh, baselines/ |
| v2.6.0 | Harness stabilization: Fix A/B, isolation, worktree-path coverage |
| **v2.7 (recommended to ship even though experiment closed)** | `evals/rubric.py` — deterministic correctness measurement (replaces LLM stochastic estimation for mechanical axes); `evals/judge.md` updated to consume rubric_results; `evals/run.sh` auto-invokes rubric.py; fixture 08 added as regression test for "repeated unit" miss; `evals/calibration/` framework for judge sanity checks before relying on them |

### state.json schema
| Version | Change |
|---------|--------|
| v2 schema | Foundational fields: tasks, baseline, risk_levels, compaction_points, execution_plan, quality_trend, spec_edits |
| v2.5.x | Added P4 quality_trend, P5 task_complexity |
| v2.6.0 | execution_plan with wave/parallel_group structure |
| v2.7 (deferred) | Would have added: mode, per-task bestofn block |

---

## §3 Experiments (closed and open)

Each significant experiment gets its own subdirectory under `docs/experiments/`
with JOURNAL + decisions/ + findings/. Index:

| Experiment | Status | Outcome | Path |
|------------|--------|---------|------|
| v2.7-quality-mode | CLOSED | Negative on quality_plus; positive on rubric infra | `docs/experiments/v2.7-quality-mode/` |
| v2.8-learning-log | In progress | Per-run sharded learning log + review-side Skill calls | `docs/experiments/v2.8-learning-log/` |
| (future) | | | `docs/experiments/v2.X-<name>/` |

See `docs/experiments/README.md` for the experiment template and protocol.

---

## How to read this file vs. other artifacts

- **`SKILL.md` frontmatter `metadata.version`** — current shipped skill version. Single source of truth for "what version is this right now."
- **`ARCHITECTURE.md`** — synthesized current-state view of how the skill works. Update whenever behavior changes (see its §13).
- **`skills/README.md`** — Archive-level index for currently installed
  standalone executor skills.
- **`HISTORY.md` (this file)** — skill-level narrative history. Both timeline and topic axes. Update when shipping a new version.
- **`DESIGN-v<X>.md`** — point-in-time design doc for a specific version's design intent. Frozen artifact.
- **`docs/experiments/<name>/`** — per-experiment record. Created at experiment start, finalized at close-out.
