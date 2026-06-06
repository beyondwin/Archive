---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation. NOTE — single-session execution is preferable for ≤5-task plans or plans with deep cross-task coupling (multi-agent overhead exceeds the parallelism win).
metadata:
  version: "2.27.0"
  updated_at: "2026-06-06"
---

# KWS Claude Multi-Agent Executor

## Path layout

**All persistent state lives under `~/.claude/`, NOT inside the source repo or repo-sibling directories.** The two key locations are paired by a shared `<plan-slug>-<YYYYMMDD-HHMMSS>` suffix derived once per run:

| Placeholder | Resolved path | Contains |
|-------------|---------------|----------|
| `<worktree>` (a.k.a. `<worktree_path>`, `WORKTREE_ABS`) | `~/.claude/worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>/` | The git worktree — code, working tree, `.git`, `.claude/settings.json` only |
| `<orch_dir>` (a.k.a. `ORCH_DIR`) | `~/.claude/orchestrator/<plan-slug>-<YYYYMMDD-HHMMSS>/` | All orchestrator state — `state.json`, hooks, learning_events, verifier/docs prompts+results, headless logs, DECISIONS.md |

The shared suffix is computed ONCE in Phase 0 Step 2 (or Phase -1 step a when self-spawning) and persisted into `state.worktree` and `state.orchestrator_dir`. Every downstream step reads these fields rather than re-deriving paths. The worktree and orchestrator-state directory are siblings, NOT nested.

**Worktree contents:** code + `.git` + `<worktree>/.claude/settings.json` (claude code loads project-local settings from cwd; the file's `command` strings reference absolute paths under `<orch_dir>/hooks/...`). Nothing else added by this skill. Sub-worktrees in the Parallel Sub-Flow get the same settings.json byte-identical — no path rewrite needed because hook scripts live outside every worktree.

**Tilde expansion:** `~/.claude/` MUST be expanded to `$HOME/.claude/` (or the absolute equivalent) before being written into state.json or passed to sub-agents. Sub-agents and headless subprocesses cannot reliably expand `~` themselves. Bash command examples in this document write the literal `~/.claude/...` for readability; the orchestrator MUST substitute the absolute path before execution.

## Overview

You are the **Orchestrator** running on Opus. Execute an implementation plan from start to finish autonomously using fresh Sonnet sub-agents. Do not ask the user for approval between tasks.

**At invocation, the user provides:**
- **Plan path** — `plan=<path>` (required). For multi-plan sequential runs (v2.13), add `plan2=<path>`, `plan3=<path>`, … `planN=<path>` and matching `specN=<path>` pairs; the skill auto-chains them in numeric order with `manifest=` NOT required.
- **Spec path** — `spec=<path>` (required for the primary plan). For multi-plan runs add `spec2=`, `spec3=`, … paired with each `planN=`.
- Optionally: `risk=<low|mid|high>` to override risk level for all tasks (run-level — shared across all plans in a chain).
- Optionally: `docs_scope=<file1,file2>` to override which docs are updated.
- Optionally: `implementer_model=<opus|sonnet>` — override the Implementer sub-agent's model. Default is `sonnet`. The Reviewer and Verifier always run on Sonnet regardless (judge consistency). See `docs/experiments/v2.12-implementer-opus-vs-sonnet/` for the rationale.
- Optionally: `parallel=off` to force sequential task dispatch (default is parallel where possible).
- Optionally: `mode=interactive` for single-session execution (no headless self-spawn — uses subscription pool instead of Agent SDK credits).

**Natural-language args (v2.13):** instead of writing `implementer_model=opus parallel=off`, you may include the words `opus` (or `오푸스`) and `순차` (or `sequential`) anywhere in the args text. The skill scans free-text tokens and applies them. Explicit `key=value` always wins; contradictions halt. See Phase -1.0 for the full lexicon and conflict rules.

---

## Active-tree resolution (v2.13)

Throughout the rest of this document, the placeholder **`<active>`** refers to the JSON path of the currently-active plan's per-plan state. It expands at runtime as follows:

| State.json shape | `<active>` expands to |
|------------------|------------------------|
| `state.plan_chain` present (multi-plan) | `state.plan_chain[state.active_plan]` |
| Otherwise (single-plan) | `state` (top-level) |

`state.active_plan` is an **integer** index (0, 1, 2, …) whenever `plan_chain` is present. A legacy v2.12 `plan2_state`-shaped state.json is rewritten into this `plan_chain` shape by the one-time migration shim at Phase 0 Step 0 (`scripts/migrate_legacy_state.py`) **before** any `<active>` logic runs, so no live state.json reaching Phase 1 carries `plan2_state`.

**Per-plan fields** (live under `<active>`, NOT directly under `state` in multi-plan runs):
`tasks`, `task_summaries`, `quality_trend`, `baseline`, `low_tasks_pending_verification`, `global_constraints`, `compaction_points`, `execution_plan`, `risk_levels`, `task_complexity`, `last_compaction_after_task`, `last_completed_task`, `last_completed_at`, `plan_review`.

**Run-level fields** (always at top-level `state.*`, shared across all plans in a chain):
`active_plan`, `plan_chain`, `implementer_model`, `spec_edits`, `test_command`, `mode`, `branch`, `worktree`, `timestamps`, `chain_resume`, `plan`, `spec` (legacy mirrors of plan_chain[0]).

Every read or write to a per-plan field MUST go through `<active>` resolution. Hard-coding `state.tasks` or `state.quality_trend` for a multi-plan run silently corrupts the chain: plan 0's data writes to top-level while plan 1's writes to `plan_chain[1]`, and the two trees diverge. The placeholder is **not optional** — wherever you see `<active>.foo` below, substitute the correct path before reading or writing.

In bash/jq fragments throughout the skill (e.g., Monitor scripts), the same rule applies via the `active_plan` dispatch:

```bash
if jq -e '.plan_chain' state.json >/dev/null 2>&1; then
  ACTIVE='.plan_chain[.active_plan]'
else
  ACTIVE='.'
fi
```

Use `$ACTIVE.tasks`, `$ACTIVE.quality_trend`, etc. in jq queries downstream.

---

## Phase -1: Mode Selection (Autonomy Gate)

> **Procedure extracted (v2.19 T1.1)**: argument parsing, mode detection,
> self-spawn, and Resume Chain procedures live in
> `references/phases/phase-minus-1-args-and-spawn.md`.
>
> **Required action at the start of every invocation**: before doing anything
> else, `Read` `references/phases/phase-minus-1-args-and-spawn.md` and follow
> its instructions to completion. That file specifies:
>
> 1. **Phase -1.0** — three-pass argument parser (key=value, multi-plan auto-detection, NL keyword lexicon) with the echo line and conflict halt rules.
> 2. **Phase -1.1** — mode detection (`mode=interactive` skip, `<<HEADLESS_KWS_ORCHESTRATOR>>` skip, otherwise Self-Spawn).
> 3. **Self-Spawn Procedure** — interactive Phase 0 Steps 1, 1.5, 2, 2.5; minimal state.json write with AgentLens `run-open`; headless prompt file; detached subprocess spawn with subshell-`cd` cwd enforcement; Monitor real-time progress notifications.
> 4. **Resume Chain** — token-aware + legacy-floor trigger; UUID resume session; PID atomic swap; `kws-cme.context_health` boundary emit; `AGENTLENS_PARENT_RUN_ID` propagation.
>
> All values resolved in Phase -1 (parsed args, `ORCH_RUN_ID`, plan_chain list,
> branch/worktree paths) persist into `state.json` so downstream phases read
> them from state rather than re-parsing. See the reference file for the
> authoritative JSON shapes.

---

## Phase 0: Setup

> **Procedure extracted (v2.21 D005)**: the full Phase 0 setup procedure —
> resume protocol + legacy `plan2_state` migration, plan/spec validation gates,
> clean-tree + cross-run isolation checks, worktree + safety-hook creation,
> document reading, ambiguity gate, spec manifest, risk assignment, local-env
> preflight, baseline test, dependency graph / compaction points / execution
> plan, Plan Reviewer preflight, state.json initialization, and the mandatory
> `kws-cme.phase_0_started` boundary emit — lives in
> `references/phases/phase-0-setup.md`.
>
> **Required action when you reach Phase 0**: `Read`
> `references/phases/phase-0-setup.md` and follow it to completion before
> entering Phase 1. It defines Steps 0 through 7.5; on the `headless_pending`
> resume path it specifies which Steps (1, 1.5, 2, 2.5) to skip. Every value it
> resolves (baseline, risk_levels, execution_plan, the full state.json) persists
> into `state.json` so downstream phases read from state rather than re-deriving.

---

## Phase 1: Per-Task Cycle

> **Procedure extracted (v2.21 D005)**: the per-task execution cycle — Step 1
> Dispatch Implementer, Step 2 Combined Reviewer (incl. the P15 spec-edit branch
> and the standard retry branch), Step 3 Verifier (MID/HIGH only), Step 3.5
> learning-log candidate scan, and Step 4 Agent Cleanup — lives in
> `references/phases/phase-1-task-cycle.md`. The multi-task Parallel Sub-Flow (P2)
> lives in `references/phases/phase-1-parallel-subflow.md`.
>
> **Required action when you reach Phase 1**: `Read`
> `references/phases/phase-1-task-cycle.md` and follow it for every task in
> `<active>.execution_plan` (waves outer, parallel groups inner). For a parallel
> group of size ≥ 2 it directs you to the Parallel Sub-Flow reference. Advance
> only when the current task or group reaches Agent Cleanup successfully.

---

## Phase Transition

> **Procedure extracted (v2.21 D005)**: the compaction-point procedure — Step T1
> batch Verifier for accumulated LOW tasks, Step T2 Phase Docs Updater, and Step
> T3 state anchor + context drop (token-health evaluation + Resume Chain trigger)
> — lives in `references/phases/phase-transition.md`.
>
> **Required action at each compaction point**: `Read`
> `references/phases/phase-transition.md` and follow T1 → T2 → T3 after Agent
> Cleanup of the boundary task, before starting the next task.

---

## Escalation Protocol

> **Procedure extracted (v2.21 D005)**: the orchestrator's full response to any
> sub-agent `STATUS: ESCALATE` (AMBIGUITY, SPEC_BLOCKER, ENV_BLOCKER, escalation
> cap) plus the ENV_BLOCKER triage pointer — lives in
> `references/phases/phase-1-escalation.md`.
>
> **Required action when a sub-agent escalates**: `Read`
> `references/phases/phase-1-escalation.md` and follow it. The ESCALATE type enum
> is summarized in the Safety Gates section below; the response procedure (and
> the rule that the orchestrator — never a sub-agent — updates spec/plan
> documents) lives in the reference.
---

## Phase 2: Final Phase

> **Procedure extracted (v2.21 D005)**: the finalization procedure — Step -1
> Cross-Plan Trigger (multi-plan `plan_chain` advance), Step 0 LOW batch
> Verifier sweep, Step 1 Final Docs Updater, Step 1.5
> Method Audit Validation, and Step 2 Generate Final Summary Report (including the
> `## Execution Summary` report template the orchestrator emits) plus the final
> `agentlens run-close` — lives in `references/phases/phase-2-finalization.md`.
>
> **Required action when all tasks are processed (COMPLETE or SKIPPED)**: `Read`
> `references/phases/phase-2-finalization.md` and follow it to completion. It
> defines the exact Final Summary Report layout and the success/blocked/aborted
> run-close outcomes.

---

## Cross-cutting references

Topics that span multiple phases live in `references/cross-cutting/`. The phase
files link to them; read the relevant one when you need the full detail behind a
guardrail or schema field:

| File | Covers |
|------|--------|
| `references/cross-cutting/state-schema.md` | Full `state.json` schema (single-plan + `plan_chain`); run-level vs per-plan field split |
| `references/cross-cutting/multi-plan-chain.md` | `<active>` resolution mechanics, multi-plan detection, the Cross-Plan Trigger |
| `references/cross-cutting/agentlens-emit-sites.md` | AgentLens emit-site catalog, candidate drain, `ORCH_RUN_ID` lifecycle, health probe |
| `references/cross-cutting/safety-hooks.md` | The three worktree hooks (PreToolUse / PostToolUse / SubagentStop) and the path invariant |
| `references/cross-cutting/decisions-register.md` | Per-plan `decisions_register` append + `DECISIONS.md` projection (v2.15 C2) |
| `references/cross-cutting/agent-dispatch.md` | The `"agent"` dispatch transport (subscription-pool Agent-tool dispatch), its failure ladder, and detach interaction (v2.25) |

The `<active>` resolution table above and the Guardrails table below are the
load-bearing summaries kept in this entrypoint; the cross-cutting files hold the
expanded detail, not a duplicate of the invariants.

---

## Guardrails

These rules are absolute. No exceptions.

| Rule | Detail |
|------|--------|
| **Path layout — `<worktree>` and `<orch_dir>` are siblings under `~/.claude/`** | `<worktree>` = `$HOME/.claude/worktrees/<RUN_ID>/`. `<orch_dir>` = `$HOME/.claude/orchestrator/<RUN_ID>/`. Same `<RUN_ID>` suffix (`<plan-slug>-<YYYYMMDD-HHMMSS>`) pairs them. Orchestrator state is NOT inside the worktree. `<worktree>/.claude/settings.json` is the only file this skill writes inside the worktree; its hook commands reference absolute paths under `<orch_dir>/hooks/`. |
| **No dirty worktree start** | Run `git status` first. Uncommitted changes → abort with clear message. |
| **Orchestrator never writes code** | All implementation goes through sub-agents. You read, plan, dispatch, and decide. |
| **Sub-agents never self-resolve blockers** | Guessing around a blocker instead of escalating → output is invalid; re-dispatch. |
| **Max 3 review retries per task** | Combined Reviewer retries (single counter). Hitting the limit halts that task. |
| **Max 3 verifier retries per task** | Hitting the limit halts that task. |
| **Max 3 escalations per task** | Combined across all sub-agents **for that task**. Exceeding halts **that task and reports to user** — does not halt the entire run. |
| **Reset before verifier re-dispatch** | Always `git reset --hard <pre_task_sha>` before retrying after Verifier FAIL. |
| **Risk level set by Orchestrator** | Verifier receives explicit LOW / MID / HIGH. It does not self-assign. |
| **Document updates are Orchestrator-only** | Never delegate spec or plan updates to a sub-agent. |
| **Re-read docs after every update** | After modifying spec or plan, re-read the full document before dispatching next sub-agent. |
| **Store summaries, not raw output** | Do not accumulate raw sub-agent output in context. Write structured results to state file and work from those. |
| **Never auto-delete the worktree** | Report its location. The user decides when to merge or delete. |
| **LOW tasks must reach batch verification** | LOW tasks skip per-task Verifier but MUST be covered by batch sweep at every compaction point and at Phase 2 Step 0. |
| **State file is authoritative** | After each compaction, the state file is the source of truth. Drop raw task details from active context. |
| **LOW task file-conflict upgrade** | See Phase 0 Step 4. Never allow two LOW tasks with shared files to batch together. |
| **ISSUE_KEY matching for RECURRING** | RECURRING labels are determined by ISSUE_KEY exact match (file:line:category), never by fuzzy text comparison. |
| **test_command is cached** | Derived once in Phase 0 Step 5; stored in state.json. Verifiers receive it pre-filled — do not re-derive. |
| **State file write must be verified** | After every Write to state.json, immediately verify it is readable. If write fails: hard halt. |
| **Headless subprocess dispatch** | Verifier and Docs Updaters run via `claude -p --dangerously-skip-permissions` (never Agent tool). Results in `<orch_dir>/{verifier,docs}_results/`. Missing result JSON → ENV_BLOCKER ESCALATE; check `.stdout` for diagnostics. |
| **Two-phase commits** | See Phase 1 Step 2.5. `chore:` orchestrator state and `feat:` code are always separate commits. |
| **PreToolUse hooks in worktree** | Phase 0 Step 2.5 writes `.claude/settings.json` blocking `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA`. |
| **PostToolUse hook is the only debug-artifact gate** | `<orch_dir>/hooks/scan-debug-artifacts.sh` (materialized at Phase 0 Step 2.5) is runtime-enforced. The orchestrator does NOT run a parallel manual grep — that duplication was removed in v2.5.0 because prose discipline silently bypassed. If the hook is disabled or missing, fix it; do not re-introduce the manual scan. |
| **SubagentStop hook validates Implementer output structure** | `<orch_dir>/hooks/check-implementer-output.sh` exits 2 if STATUS / SUMMARY / FILES_CHANGED / FILES_TEST_CHANGED (or COMMIT on DONE, ESCALATE fields on ESCALATE) are missing. Sub-agent auto-retries; no orchestrator action needed. |
| **Stop hook forces finalization (v2.26)** | `<orch_dir>/hooks/finalization-stop-gate.sh <orch_dir>/state.json <skill_dir>/scripts` (wired at Phase 0 Step 2.5). A cheap `jq` short-circuit exits 0 while any task is non-terminal; only once **every** task is terminal AND a real end-signal fired does it run `finalize_run.py --check` + `validate_state_schema.py`, exiting 2 to block the stop if the run is done-but-unfinalized or non-canonical. Resolves the two Phase-2-only gate gaps — skipped-Phase-2 bypass and attached-mode schema improvisation (D001). Fail-open on hook-internal error, fail-closed on detected inconsistency. Advisory-blocking like the rest of the worktree hook suite. |
| **Worktree settings.json is script-materialized + merged (v2.27)** | Phase 0 Step 2.5 runs `scripts/materialize_worktree_hooks.py` (never a hand-written JSON). It deep-merges the four hook events into any pre-existing repo `.claude/settings.json`, preserving `permissions`/`$schema`/other hook events, and self-asserts `Stop` → `finalization-stop-gate.sh`. Non-zero exit = hard halt. `--check` mode re-asserts without writing and runs as the Task-1 preflight. Resolves the run-2 hook-wiring loss (v2.27 D001). |
| **Cost/timing drift is a blocking finalize FAIL (v2.27)** | `finalize_run.py` treats `cost_ledger.totals.dispatches == 0` (unless `cost_tracking_waived`) and all-terminal-tasks-`timing.started`-null (unless `timing_tracking_waived`) as FAIL, not WARN. The Stop gate then blocks a drifted attached run from finishing silently green. Partial timing misses stay per-task WARN. Blocking forces fix-or-explicit-waive; it does not recover lost data (v2.27 D002). |
| **Finalize asserts worktree hooks are wired (v2.27)** | `finalize_run.py` raises blocking `hooks_not_wired` FAIL (unless `hooks_wiring_waived`) when `<worktree>/.claude/settings.json` is present+parseable but missing the four hooks / Stop gate (reuses `materialize_worktree_hooks.check_problems`). Skips silently when the `worktree` key is absent or the file is missing/unparseable, so replays/cleaned worktrees never false-positive. Finalize-time backstop for a run that skipped Step 2.5 (wired no Stop gate); rides the Phase 2 Step 2 `--fix` site, a distinct skip from Step 2.5 (v2.27 D003). |
| **Plan Reviewer is mechanical, not subjective** | Phase 0 Step 6.5 audits the plan/spec against a fixed rubric (missing Files, missing AC on MID/HIGH, contract mismatch, dep cycles, out-of-repo paths). Style/architecture suggestions are out of scope and MUST be ignored if the sub-agent returns them. BLOCKER issues halt with a batched user question; WARN issues are recorded and bypass. Skip the entire step via `preflight=off`. |
| **Effort scaling is heuristic and biased upward** | Phase 0 Step 6 assigns SMALL/MEDIUM/LARGE per task for tool budget and review/verification routing only. Task size is not a TDD skip condition: any Implementer task that writes or modifies executable code or behavior must use `superpowers:test-driven-development` and report RED evidence before implementation, whether SMALL, MEDIUM, or LARGE. Docs-only, config-only, or generated-only tasks may report TDD as not applicable. Mis-estimation is acceptable as mild over-engineering; never silently under-instruct a HIGH-risk task (risk_mult forces LARGE). |
| **Quality scoring thresholds are not user-configurable** | SPEC threshold 0.85, QUALITY threshold 0.75, WARN floors 0.70/0.60 (P4). Calibrated against the P6 eval suite. Re-tune only when re-calibrating against a new Claude version, not per-run. |
| **WARN tier does not retry** | A WARN-tier review proceeds to Verifier with warnings recorded in `task_summaries.task_N.warnings`. WARN exists to prevent burning the 3-retry budget on borderline work. Three consecutive WARN tasks → surface at next compaction (signal, not halt). |
| **`quality_trend` is rolling, max 10** | Phase 1 Step 2 appends `quality_score` to `<active>.quality_trend` (drop oldest at length 10). Each plan in a v2.13 chain has its own buffer at `state.plan_chain[N].quality_trend`. Mean-of-last-5 < mean-of-first-5 by > 0.10 → surface at next compaction. |
| **Parallel Implementer outputs must respect declared Files: blocks** | Step P.4 verifies each sub-worktree's `FILES_CHANGED` is a subset of its task's declared `Files:` block AND that no two sub-worktrees in the same group touched the same file. Violation halts the group, removes sub-worktrees, and re-dispatches the offender sequentially. Never silently merge an out-of-scope parallel edit. |
| **Sub-worktrees inherit `.claude/settings.json` byte-identical** | Step P.1 copies ONLY `<worktree>/.claude/settings.json` into every sub-worktree. Hook scripts live in `<orch_dir>/hooks/` (outside any worktree), referenced by absolute path inside settings.json — so every sub-worktree hits the same hook binaries with no path rewrite. Rewriting paths is a bug (sub-worktrees would point at non-existent paths). |
| **External-resource contention in parallel waves is the user's responsibility** | If two parallel tasks contend for the same DB port, file lock, or external service, mark one of them `serial: true` in the plan. The Phase 0 Step 6 partition respects `serial` and keeps such tasks in singleton groups. The skill cannot detect arbitrary external contention. |
| **Disable parallel dispatch via `parallel=off`** | Writes a degenerate `execution_plan` where every parallel group is singleton. Use when sub-worktree creation is constrained (shallow clones, low disk, fsmonitor races). |
| **Acceptance Criteria shell is primary PASS condition** | If a task has an `## Acceptance Criteria` block with executable shell, the Verifier runs those commands first. All must exit 0. Risk-tiered test instructions are the fallback when no AC block is present. |
| **Plan structural validation is mandatory** | Step 0.5 runs before worktree creation. A plan must have either `### Task N:` (H3, canonical) OR `## Task N:` (H2) task headers — neither present halts immediately. Detected level is persisted as `<active>.task_header_prefix` and used consistently in all downstream parsing, Plan Reviewer prompts, and sub-agent task excerpts. A plan with missing Files blocks halts with a user question. Never skip this gate. |
| **Ambiguity gate clears before risk assignment** | Step 3.5 must complete with zero unresolved ambiguities before Step 4 begins. Unclear task descriptions answered downstream cost one full sub-agent dispatch + reset cycle. |
| **Out-of-repo paths halt execution** | Files blocks referencing paths outside repo root halt at Phase 0 Step 3.5. Never infer a correction — always ask the user. |
| **Phase -1 self-spawn is opt-in (v2.22.0)** | Self-Spawn (detached headless `claude -p`) triggers only when `detach=true` is passed (explicit or NL); a bare invocation now runs ATTACHED in-session by default (`state.mode = "interactive_attached"`). `mode=interactive` still forces legacy single-session; the `<<HEADLESS_KWS_ORCHESTRATOR>>` sentinel still marks a spawned instance. A 2-week deprecation warning (controlled by `state.deprecation_warnings.attach_default`) fires on bare invocations so users notice the changed default. Self-spawn (when opted in) stays gated by Phase 0 Steps 1, 2, 2.5 — failures abort the spawn and surface to the user. |
| **`mode` field is always a string** | `state.mode ∈ {interactive_session, interactive_attached, headless_pending, headless_running, headless_chained, plan_chain_running, plan2_running}`. Never null. `interactive_attached` is the v2.22.0 attached-by-default in-session mode (Task 14) written when a bare invocation runs ATTACHED rather than self-spawning headless. `plan_chain_running` is written by the Phase 2 Step -1 Cross-Plan Trigger when it advances `active_plan`; `plan2_running` is the legacy v2.12 equivalent, preserved (not rewritten) by the migration shim. Resume protocol (Phase 0 Step 0) dispatches on this value — null breaks the headless_pending branch. |
| **`active_plan` pointer is authoritative for plan selection** | All Phase 1 / Phase Transition / Phase 2 / Monitor code dereferences `<active>` per the resolution table near the top of this document. Multi-plan: integer index into `state.plan_chain[]`. Single-plan: the string `"plan1"` with per-plan fields at top level. (The legacy v2.12 `"plan2"` string is migrated to `plan_chain` at Phase 0 Step 0 and never reaches live `<active>` logic.) Never assume top-level `state.tasks` is the active tree without checking — hard-coding it for a multi-plan run silently corrupts the chain. |
| **`last_completed_task` is the only authoritative "most recent" field** | Phase 1 Step 4 Agent Cleanup writes it. Monitor and any post-hoc query MUST use it — never `to_entries \| last` over `tasks` (key insertion order is mutated by re-writes; this caused a real observed bug). |
| **Spec-edit branch uses `spec_clarifications`, not `review_retries`** | When `SPEC_FAULT ∈ {spec_contradicts, unclear}`, increment `spec_clarifications` (max 3 per task). Implementer retry budget stays intact for actual implementer mistakes. |
| **Resume Chain trigger is deterministic** (v2.15) | Chain when EITHER token threshold OR legacy floor fires (additive). Token threshold: `session_input_tokens (= cost_ledger.totals.input_tokens − cached_read_tokens) ≥ state.context_budget.threshold_tokens`. Legacy floor: `compaction_points reached ≥ 2` AND `completed tasks ≥ 8` (always evaluated). `budget_action == "off"` disables the token trigger, leaving the legacy floor as the sole criterion. Chain procedure MUST update `headless.pid` atomically so Monitor sees `CHAIN_HANDOFF`, not `PROCESS_DIED`. |
| **`files_test` discrimination for batch verifier** | Implementer outputs `FILES_TEST_CHANGED` separately from `FILES_CHANGED`. T1 batch pre-filter uses it (or `.md`-only heuristic for legacy state) to route docs-only tasks to lint instead of test runs. |
| **Next plan re-takes baseline** | When Phase 2 Step -1 swaps `active_plan` to the next integer index (i+1), run Phase 0 Step 5 fresh against current HEAD (plan i's changes are now plan i+1's starting point) and write to `plan_chain[i+1].baseline`. Never reuse a prior plan's baseline as the next plan's regression reference. |
| **AgentLens event lifecycle (v2.17 cutover)** | Phase -1 step b opens an AgentLens run and captures `ORCH_RUN_ID`. Phase 0 Step 7.5 emits `kws-cme.phase_0_started`. Phase 1 Step 3.5 scans `<orch_dir>/learning_events/` for sub-agent candidate JSON and publishes each as `kws-cme.<event_type>`. Phase 1 Step 2.6 emits `kws-cme.task_completed`. Phase Transition T3 emits `kws-cme.compaction` plus drains `context_health` candidates. Phase 2 Step 2 emits `kws-cme.phase_2_complete` then `agentlens run-close --outcome success`. Hard-halt paths (escalation exhaustion, budget pause, T3 state-write failure) emit `kws-cme.blocker` and call `agentlens run-close --outcome aborted\|blocked`. Resume Chain propagates `AGENTLENS_PARENT_RUN_ID` (= parent `ORCH_RUN_ID`) into the chained child's env so the child re-exports it as `ORCH_RUN_ID` and continues publishing to the same run. **Every `agentlens` invocation is `2>/dev/null \|\| true`** — observability failure must never block plan execution. The legacy `append_learning_event.py` helper was removed in Task 11 after parity verification (`scripts/compare_agentlens_events.py`). See `references/learning-log.md`. |
| **`state.timestamps.completed_at` is stamped at Phase 2 Step 2** (v2.16) | The first action of Step 2 is an atomic R-M-W of state.json setting `timestamps.completed_at = <iso8601 now>`. This is the canonical wall-clock end-marker; the Final Summary Report's "Total wall time" row depends on it. Pre-v2.16 runs left this field null even on `outcome=success` because nothing in the prose explicitly wrote it. State-file write failure here is a hard halt (existing guardrail). |
| **`timing.started` is stamped before Step 1 dispatch** (v2.16) | The "Before Step 1 of each task" block writes `<active>.tasks.task_<N>.timing.started = <iso8601 now>` via atomic R-M-W. Without this field the per-task duration column cannot be computed (observed: `jq strptime` errors across all v2.11–v2.15 runs because the field stayed null). Failure to write is a non-fatal warning, not a halt. |
| **Single-writer for learning events** | Only the orchestrator invokes the helper. Sub-agents write event candidates as JSON files under `<orch_dir>/learning_events/<task_id>-<role>.json`; the orchestrator reads and forwards them. Never let a sub-agent prompt instruct direct helper invocation. |
| **`context_health` is observation-only (v2.10)** | Emitted at Phase Transition T3 and Resume Chain chained-orchestrator startup. Counts compaction index, completed tasks, chain handoffs. **MUST NOT alter orchestrator control flow** — Goodhart's-law guard. Behavior changes require a follow-on experiment under `docs/experiments/v2.10-context-health/` after ≥ 2 weeks of real-run data. See `references/learning-log.md`. |
| **Polite-stop anti-pattern is forbidden (v2.10.1)** | A sub-agent returning PASS / APPROVED is a checkpoint inside the autonomous loop, never a reporting moment. The orchestrator MUST proceed immediately to the next phase step in the same turn. The only legitimate reporting moments are: Phase 2 success completion, ESCALATE that exceeds `escalation_count > 3`, headless `HEADLESS_HALTED.txt`, or hook denial. Any prompt edit that introduces "summarize and wait for user acknowledgment" between PASS and the next step IS the regression this invariant exists to prevent. |
| **Cross-run isolation is repo-scoped (v2.10.1, narrowed v2.20)** | Phase 0 Step 1.5(a) refuses to start only when another live headless run targets the **same source repo** (key: canonical `git rev-parse --git-common-dir`, stored as `state.source_repo`). Runs against *different* repos are allowed to run concurrently — disjoint `.git` object stores and branch namespaces cannot race, and each run owns a distinct `agentlens_orchestration_run` id. **Conservative block:** if either side's `source_repo` is empty/unknown (pre-v2.20 state.json, or not in a git repo), block rather than guess. Mode exclusivity is concurrent-safe by halt, not by lock — for same-repo collisions the user chooses which run continues. Orphan worktrees with no state.json + >7d mtime are reported but never auto-deleted (may hold uncommitted manual debugging). |
| **Method audit fields are populated at Agent Cleanup (v2.11)** | Method audit fields are populated at Phase 1 Step 4 from structured sub-agent output. |
| **Method audit must pass before Phase 2 close-run** | Phase 2 Step 1.5 runs `scripts/validate_method_audit.py`. A task is `applied` only when it has evidence references (RED command, GREEN command, commands_run, findings_count). FAIL halts before close-run; user re-dispatches or edits `<active>.tasks.<id>.method_audit.waived` with a reason. v2.13: the validator must iterate every `state.plan_chain[N].tasks` for chain runs, not just top-level. |
| **Finalization gate is mandatory before close-run (v2.26)** | Phase 2 Step 1.5 runs `scripts/validate_state_schema.py` (canonical-shape: non-empty `tasks{}` when tasks are declared, `execution_plan` not `execution_order`, risk ∈ low/mid/high, run-level `dispatch_config`/`cost_ledger` present) and Step 2 runs `scripts/finalize_run.py --fix` (completed_at stamped, no task left `PENDING_BATCH`, terminal task statuses). A schema violation or an unfixable finalize FAIL HALTS before `agentlens run-close --outcome success` — the run is never declared COMPLETE with a non-canonical or unfinalized state.json. `finalize_run --fix` only stamps `completed_at`; it never clears `PENDING_BATCH` (that needs a real LOW batch sweep). As of v2.27, `cost_ledger.dispatches==0` (unless `cost_tracking_waived`), all-terminal-`timing.started`-null (unless `timing_tracking_waived`), and an unwired worktree settings.json (unless `hooks_wiring_waived`) are blocking FAIL, not WARN (D002/D003). |
| **Method audit fields populated at Phase 1 Step 4** | Orchestrator parses `METHOD_AUDIT:` from Implementer, `REVIEW_FINDINGS:` from Combined Reviewer, `commands_run` from Verifier result JSON. Written under `<active>.tasks` per the resolution table. |
| **TDD waive reasons are restricted** | `METHOD_AUDIT: tdd waived` accepts only `reason=docs-only-task`, `config-only-task`, or `generated-only-task`. Other reasons fail validation. |
| **Resource-key collisions force serialization in same wave** | Phase 0 Step 6 resource_key partition rule: tasks in the same wave that share a `**Resource Key:** <slug>` annotation are placed in singleton groups (never merged). The `serialization_reason: "resource_key=<key>"` field is written to each affected `<active>.execution_plan` group. WARN is emitted by the Plan Reviewer; correctness is automatic. |
| **`implementer_model` records both used and default** (v2.12) | Arg is parsed in the **interactive parent** (Phase -1 step b OR Phase 0 Step 7 when mode=interactive) and written into state.json. The headless child reads it FROM state.json — it cannot re-parse skill args since `claude -p` only sees the headless prompt text. Phase 0 Step 7 in the child preserves the field as-is. `state.implementer_model = {"used": <effective>, "default": "sonnet"}`. `default` is the contemporaneous skill default, NOT the parsed arg. Phase 1 Step 1 reads `used` and passes it as the Agent tool `model` parameter — `sonnet` may omit the parameter, `opus` MUST set it explicitly (omitting silently falls back to the agent default and invalidates A/B comparisons). **Parallel Sub-Flow Step P.2 dispatches MUST also pass `model`** under the same rule — forgetting it there silently downgrades parallel-merged tasks to Sonnet regardless of the run's selection. Reviewer and Verifier are unaffected — they always run on Sonnet for judge consistency. Plan 2 inherits Plan 1's selection. |
| **Multi-plan auto-chain detection** (v2.13) | Phase -1.0 Pass 2 scans `plan\d*=` keys. `plan=` is index 0, `plan2=` is index 1, etc. Gaps halt. Missing `specN=` for present `planN=` halts. Length 1 → v2.12 single-plan schema. Length ≥ 2 → `plan_chain[]` schema with `active_plan` as integer index. `manifest=` is mutually exclusive (reserved; halt if combined). |
| **NL keyword lexicon is fixed and conservative** (v2.13) | Phase -1.0 Pass 3 scans free-text tokens (excluding tokens with `/`, `.`, `=`, backticks) for the closed lexicon: opus/오푸스, sonnet/소넷, 순차/sequential/직렬/시리얼, 대화형/interactive. Explicit `key=value` always wins; NL fills unset keys only. Conflicts halt with batched question — never silently disambiguate. Lexicon additions require an ADR (see `docs/experiments/v2.13-natural-multi-plan/decisions/D001`). |
| **Phase -1 echo line is mandatory** (v2.13) | Before any other work, Phase -1.0 prints ONE line summarizing parsed args (plan count, implementer_model, parallel, mode, risk) with the source of each value (explicit / NL / default). This is the user's one chance to spot mis-interpretation before the headless subprocess detaches. The line goes to stdout of the interactive parent — visible even before the spawn. Never skip. |
| **`plan_chain[]` is authoritative when present** (v2.13) | When `state.plan_chain` exists in state.json, code MUST dereference `state.plan_chain[state.active_plan].*` for tasks, task_summaries, quality_trend, risk_levels, task_complexity, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review. Top-level `state.tasks` etc. are NOT written for multi-plan runs. `state.plan` and `state.spec` mirror `plan_chain[active].plan_path / .spec_path` for legacy reader convenience but are NOT the source of truth. `state.active_plan` is an integer (not a string) when chain is in use. |
| **Per-plan result file suffix** (v2.13) | Verifier/Docs Updater output JSON files under `<orch_dir>/{verifier,docs}_results/` get a `_p<index>` suffix in multi-plan runs to avoid collision across plans (`batch_p0_2.json`, `phase_p1_4.json`, `final_p2.json`). Single-plan and legacy v2.12 two-plan runs keep their un-suffixed paths for compatibility. Aggregators that scan these directories must accept both shapes. |
| **Run-level args propagate across all chain plans** (v2.13) | `implementer_model`, `parallel`, `risk`, `docs_scope` are written to state.json top-level (NOT into each plan_chain entry). The Cross-Plan Trigger does NOT reset them at swap. Every plan in the chain inherits the same model selection, parallel toggle, etc. Plan-specific overrides are deliberately NOT supported — if a user wants different models for different plans, they invoke the skill once per plan, not as a chain. |
| **Cost ledger frozen pricing** | `scripts/price_table.py` hardcodes rates at commit time. Historical runs reflect contemporaneous rates — re-running with a later price_table does NOT retroactively recompute past runs. Update price_table when Anthropic adjusts rates; do NOT auto-fetch. |
| **Cost-accumulate helper is mandatory per dispatch** (v2.16) | Every sub-agent dispatch (Implementer / Reviewer / Verifier / Plan Reviewer / Docs Updater) ends with a `scripts/accumulate_cost.py` invocation in Phase 1 Step 4 substep 1.5. Pre-v2.16 prose ("extract usage from Agent result, update by_task atomically") was silently skipped in every observed run — `cost_ledger.totals.dispatches=0` across runs 1/2/3 confirmed the regression. The helper is single-call, flock-protected, and handles unknown-model and missing-usage gracefully. Skipping the helper call means budget cap (`budget_cap_usd`) and `chain_trigger_eval` token threshold cannot fire correctly. by_task key is `<plan>::<task>::<role>` so same-task multi-role dispatches don't overwrite. |
| **`budget_action=pause` halts at compaction boundaries only** | Budget is evaluated at Phase Transition T3 and Phase 2 Step 0 — never mid-task. Cost overruns within a single task complete the task, then the next compaction triggers halt. This is intentional: aborting mid-task wastes the in-flight dispatch. |
| **Cost ledger is run-level** | `cost_ledger`, `budget_cap_usd`, `budget_action` live at top-level state.json (never inside `plan_chain[N]`). Cross-plan chains accumulate one unified ledger. Per-plan totals derivable via `by_task` key prefix `<plan_index>::`. |
| **`dispatch_config` is run-level** (v2.22; extended v2.25) | `state.dispatch_config` lives at top-level state.json (never inside `plan_chain[N]`) and selects the dispatch path per role gate: `{plan_reviewer, verifier_batch, verifier_per_task, transition_combined, docs_updater_phase, docs_updater_final}`, each `"p" \| "api" \| "agent"`, default `"agent"` (v2.25). `final_sweep` is a separate gate, `"api" \| "batch" \| "agent"`, default `"agent"`. The same selection applies to every plan in a chain. |
| **Spec manifest is per-plan** (v2.15 C1) | `spec_manifest` lives under `<active>` per the v2.13 resolution rule. Each plan in a chain has its own manifest (sections + task_to_sections + fallback_policy). `task_to_sections` references are validated by the Plan Reviewer at Phase 0 Step 6.5 — unknown section IDs are BLOCKER. Manifest is rebuilt at the spec-edit branch (Phase 1 Step 2 sub-step 6.5). |
| **Decisions register is per-plan, append-only** (v2.15 C2) | `decisions_register` lives under `<active>`. Entries are never deleted — supersession is recorded via the `supersedes` field (still rendered, with strikethrough prefix). Empty `key_decision` from `task_summaries` is ignored (not appended). Append failure logs a warning and continues (best-effort). |
| **decision_conflict is a QUALITY issue, not SPEC** (v2.15 C2) | Combined Reviewer flags `decision_conflict` under `QUALITY_ISSUES`. Does NOT downgrade `SPEC_SCORE`. Standard `review_retries` budget applies — no spec-edit branch. Use it to nudge sub-agents toward consistency, not to halt. Intentional supersession (diff includes `supersedes <task_id>` comment) emits an ADVISORY note instead of an ISSUE. |
| **Token-based chain trigger is additive** (v2.15 C3) | C3's `session_input_tokens >= threshold_tokens` trigger fires *in addition to* the legacy `compactions ≥ 2 AND completed ≥ 8` floor. Never replaces. `budget_action=off` disables the token trigger (legacy is then the sole criterion). `session_input_tokens = cost_ledger.totals.input_tokens − cached_read_tokens`. One `chain_trigger_eval` event per Phase Transition T3 regardless of decision (telemetry for trigger lift). |
| **Agent dispatch is the v2.25 default** | Plan Reviewer, Verifier (batch + per-task), Transition (combined), Docs Updater, and the Phase 2 final sweep default to `"agent"` — in-session Agent-tool dispatch on the subscription pool (`references/cross-cutting/agent-dispatch.md`), NOT metered `claude -p` / Messages API. Set a gate to `"api"` or `"p"` (or `"batch"` for `final_sweep`) to opt back into a metered transport. The agent failure ladder auto-falls-back `agent → api` for a single failed dispatch (only sanctioned automatic fallback). |
| **Scaffold byte-stability is enforced** | Every API role prompt carries a SCAFFOLD/PAYLOAD split (four HTML-comment markers). The SCAFFOLD region is the `cache_control: ephemeral` cache prefix and MUST stay byte-for-byte identical to its sibling `references/_scaffolds/<role>-scaffold.md`; `scripts/validate_scaffold_split.py` lints this scaffold byte-stability invariant. Drift silently misses the cache on every dispatch. The SCAFFOLD region MUST be brace-free — literal `{` and `{placeholder}` content lives only in PAYLOAD. |
| **No `-p` fallback on API errors** | A transient Messages API failure retries in-band (up to the dispatcher's retry budget) and then ESCALATEs as `ENV_BLOCKER` — it does NOT silently fall back to `claude -p`. The subprocess path is selected only by an explicit `state.dispatch_config.<gate> = "p"`, never as automatic error recovery. |
| **API dispatch forces `tool_choice`** | Single-role API dispatches set `tool_choice={"type":"tool","name":"report_<role>"}` so the model MUST emit the structured `report_<role>` tool call; the combined Transition uses `tool_choice={"type":"any"}` across its two tools (`verify_low_batch` + `update_phase_docs`). Never dispatch an API role without a forced `tool_choice` — free-form text output breaks result parsing. |

---

## Sub-agent Prompt Templates

The Implementer, Combined Reviewer, Verifier, and Docs Updater prompt templates live in `references/`. Read the relevant file via the Read tool **at the moment of dispatch** — do NOT preload them.

| Step | Template file | Dispatch mode |
|------|---------------|---------------|
| Phase 0 Step 6.5 — Plan Reviewer | `references/plan-reviewer-prompt.md` | Headless `claude -p` |
| Phase 1 Step 1 — Implementer | `references/implementer-prompt.md` | Agent tool (fresh Sonnet) |
| Phase 1 Step 2 — Combined Reviewer | `references/reviewer-prompt.md` | Agent tool (fresh Sonnet) |
| Phase 1 Step 3 / Transition T1 — Verifier | `references/verifier-prompt.md` | Headless `claude -p` |
| Transition T2 — Phase Docs Updater | `references/docs-updater-prompts.md` (Phase section) | Headless `claude -p` |
| Phase 2 Step 1 — Final Docs Updater | `references/docs-updater-prompts.md` (Final section) | Headless `claude -p` |

Each file is a self-contained prompt body with `{placeholders}` to fill from the current task context. The dispatch mechanics (Agent vs. headless), result-file paths, and ESCALATE handling are defined in the SKILL.md phases above — the reference files do not repeat that logic.

All sub-agent prompt templates must bootstrap `Skill("superpowers:using-superpowers")` as their first action. Implementers must additionally invoke `Skill("superpowers:test-driven-development")` for executable implementation work before writing implementation code, independent of task size, and must report RED/GREEN evidence in their structured output.
