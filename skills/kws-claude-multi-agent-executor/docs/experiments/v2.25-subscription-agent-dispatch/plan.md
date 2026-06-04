# v2.25 Subscription-pool Agent Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `"agent"` dispatch transport so the Plan Reviewer, Verifier, and Docs Updater roles run in-session via the Agent tool (subscription pool) instead of metered `claude -p` / Messages API, defaulting to subscription for a bare invocation.

**Architecture:** The `"agent"` path is a *prose dispatch pattern* (an inline Agent-tool call the orchestrator makes), not a helper script — a script cannot invoke the Agent tool. It reuses each role's existing `-p` prompt and the result-file seam: the sub-agent writes `{result_json_path}`; downstream reads + schema-validates unchanged. The pattern is defined once in a new cross-cutting reference and referenced by each phase's gate branch. The only code change is flipping the Plan Reviewer default model to Opus.

**Tech Stack:** Markdown skill prose (`SKILL.md`, `references/**`), Python stdlib scripts + `unittest` tests under `scripts/`, `bun run check` / scaffold lints / `evals/run.sh` for regression.

**Spec:** [`README.md`](./README.md) + ADRs [D001](./decisions/D001-agent-gate-subscription-default.md) / [D002](./decisions/D002-detach-conflict-handling.md) / [D003](./decisions/D003-autonomous-error-handling.md).

**Conventions used below:**
- `SKILL_DIR` = `skills/kws-claude-multi-agent-executor` (repo-relative). All paths below are under it unless absolute.
- Commit after each task. Use `chore(v2.25):` for doc/prose, `feat(v2.25):` / `test(v2.25):` for script+test, referencing the ADR (e.g. `(per D001)`).
- Gate set (the seven gates this feature touches): `plan_reviewer`, `verifier_per_task`, `verifier_batch`, `transition_combined`, `docs_updater_phase`, `docs_updater_final`, `final_sweep`.

---

## Task 1: Plan Reviewer default model → Opus (script + test)

The only executable-code change. Flips `DEFAULT_PLAN_REVIEWER_MODEL` from Haiku to Opus so every transport (agent / api / p) selects Opus for the Plan Reviewer by default (per D-note in README §3; user "Opus-everywhere" preference). Canonical Opus id is `claude-opus-4-7` (`scripts/price_table.py:4,34`).

**Files:**
- Modify: `scripts/dispatch_plan_reviewer.py:10` (the `DEFAULT_PLAN_REVIEWER_MODEL` constant + module docstring)
- Test: `scripts/test_dispatch_plan_reviewer.py`

- [ ] **Step 1: Update the failing test first**

In `scripts/test_dispatch_plan_reviewer.py`, change the default-model expectation. Find the test that asserts the default with `dispatch_config = {}` (around line 30) and set its expected value to Opus. Add an explicit name test too:

```python
    def test_default_is_opus(self):
        # v2.25: Plan Reviewer defaults to Opus (Opus-everywhere for this executor)
        state = {"dispatch_config": {}}
        self.assertEqual(select_plan_reviewer_model(state), "claude-opus-4-7")
```

Also update any existing assertion that still expects `"claude-haiku-4-5-20251001"` as the *default* (override tests that pass an explicit `plan_reviewer_model` stay unchanged).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd skills/kws-claude-multi-agent-executor && python3 -m pytest scripts/test_dispatch_plan_reviewer.py -v`
Expected: FAIL — `test_default_is_opus` (and the edited default assertion) expect `claude-opus-4-7` but the code returns `claude-haiku-4-5-20251001`.

- [ ] **Step 3: Change the default constant**

In `scripts/dispatch_plan_reviewer.py` line 10:

```python
DEFAULT_PLAN_REVIEWER_MODEL = "claude-opus-4-7"
```

And update the module docstring (lines 3–6) to reflect the change:

```python
"""Plan Reviewer model selection — pure selection logic, no SDK calls.

The Plan Reviewer (Phase 0 Step 6.5) runs a mechanical rubric. As of v2.25 it
defaults to Opus (claude-opus-4-7): the user's "Opus-everywhere" preference for
this executor's judging roles. Overridable via
``state.dispatch_config.plan_reviewer_model``. The selected model is recorded
into ``state.plan_review.model_used`` for forensics.
"""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd skills/kws-claude-multi-agent-executor && python3 -m pytest scripts/test_dispatch_plan_reviewer.py -v`
Expected: PASS (all tests, including override tests).

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/scripts/dispatch_plan_reviewer.py skills/kws-claude-multi-agent-executor/scripts/test_dispatch_plan_reviewer.py
git commit -m "feat(v2.25): default Plan Reviewer to Opus (Opus-everywhere)"
```

---

## Task 2: Create the cross-cutting `agent-dispatch.md` reference (DRY anchor)

Defines the reusable `"agent"` dispatch pattern ONCE so each phase gate-branch is a one-line reference instead of repeating prose. This is the load-bearing doc for Tasks 6–9.

**Files:**
- Create: `references/cross-cutting/agent-dispatch.md`

- [ ] **Step 1: Write the reference file**

Create `references/cross-cutting/agent-dispatch.md` with exactly this content:

````markdown
# Cross-cutting: `"agent"` dispatch transport (v2.25)

A third value for every `state.dispatch_config` role gate, alongside `"p"`
(headless `claude -p`) and `"api"` (`scripts/dispatch_via_api.py`). `"agent"`
dispatches the role **in-session via the Agent tool** — the same transport the
Implementer and Combined Reviewer already use (Phase 1 Steps 1–2) — so the
dispatch bills against the **subscription pool**, not metered API credits.

`"agent"` is the **default** for all role gates (v2.25). See D001.

## Why this is prose, not a script

The `-p`/`api` transports are script-driven. `"agent"` is fundamentally an
**inline Agent-tool call the orchestrator model makes itself** — a script cannot
invoke the Agent tool. There is therefore no `dispatch_via_agent.py`; this file
is the procedure the orchestrator follows directly.

## The dispatch procedure

When a role gate resolves to `"agent"`, dispatch that role as follows. The
caller supplies `ROLE`, `MODEL`, `PROMPT_TEMPLATE`, and `RESULT_PATH`.

1. **Build the prompt** from the SAME template the `-p` path uses for `ROLE`,
   with `{result_json_path}` set to `RESULT_PATH` and all other placeholders
   filled exactly as the `-p` path fills them. Do NOT author a new prompt body.
2. **Dispatch via the Agent tool** with `model: MODEL` and the built prompt as a
   fresh sub-agent. Models by role:
   - Verifier → `sonnet`
   - Docs Updater → `sonnet`
   - Plan Reviewer → `opus` (matches the `dispatch_plan_reviewer.py` default;
     honor `state.dispatch_config.plan_reviewer_model` if set)
3. **The sub-agent writes its structured result JSON to `RESULT_PATH`** (its
   prompt already instructs this) and returns. The caller does NOT parse the
   returned message for the result.
4. **Read + schema-validate `RESULT_PATH`** exactly as the `-p`/`api` path does
   for `ROLE` (`verifier_result.schema.json`, `docs_updater_result.schema.json`,
   or the `report_plan_reviewer` shape). Downstream consumption is unchanged.
5. **Accumulate cost** — extract `usage` from the Agent return envelope
   (`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
   `cache_creation_input_tokens`), normalize per Phase 1 Step 4 substep 1.5, and
   call `scripts/accumulate_cost.py --role ROLE --model MODEL ...`. Subscription
   dispatches still report usage, so the ledger stays populated.

For the **combined transition** (`transition_combined`), a SINGLE Agent
sub-agent runs the `-p` combined prompt and writes the combined
`{verify, docs}` JSON to its result path. Do NOT split into two dispatches.

## Failure ladder (autonomous — never prompt the user). See D003.

1. **Result file missing or fails schema validation → retry once** (re-dispatch
   the same `ROLE` as a fresh Agent sub-agent).
2. **Still failing → auto-fallback to `"api"` for this one dispatch.** Run the
   role's `scripts/dispatch_via_api.py` path, log it, and emit
   `kws-cme.dispatch_fallback` (best-effort, `2>/dev/null || true`). This is the
   ONLY sanctioned automatic transport fallback, and only `agent → api`, only
   after the retry.
3. **`api` also fails** (after its own retry budget → ENV_BLOCKER):
   - **Plan Reviewer (advisory):** log a warning and proceed (existing "absence
     is not a halt" policy).
   - **Verifier / Docs (load-bearing):** write a gap marker into state —
     `<active>.verification_gaps += [{task, reason, ts}]` (Verifier) or
     `<active>.docs_gaps += [{scope, reason, ts}]` (Docs) — emit
     `kws-cme.blocker`, then **continue the run**. The Final Summary Report
     (Phase 2 Step 2) MUST render these gaps in a dedicated row. Never silent,
     never halt, never prompt.

## detach interaction. See D002.

`"agent"` reaches the subscription pool ONLY when the orchestrator runs
attached. Under `detach=true` the orchestrator is a `claude -p` process and its
Agent sub-agents bill against that metered parent. Phase -1 resolves this before
dispatch (see `references/phases/phase-minus-1-args-and-spawn.md`):
- `detach=true` + gate at the agent **default** → that gate falls back to
  `"api"` (one-line warning).
- `detach=true` + gate **explicitly** `"agent"` → warn + proceed.
````

- [ ] **Step 2: Verify the file is well-formed and discoverable**

Run: `cd skills/kws-claude-multi-agent-executor && test -f references/cross-cutting/agent-dispatch.md && grep -c "agent" references/cross-cutting/agent-dispatch.md`
Expected: file exists, non-zero match count.

- [ ] **Step 3: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/cross-cutting/agent-dispatch.md
git commit -m "docs(v2.25): add agent-dispatch cross-cutting reference (per D001/D003)"
```

---

## Task 3: state-schema.md — gate enum, defaults, final_sweep, gap fields

**Files:**
- Modify: `references/cross-cutting/state-schema.md` (the `dispatch_config` JSON block ~line 79–81 and the prose at ~line 181–183)

- [ ] **Step 1: Update the `dispatch_config` example block**

Replace the `dispatch_config` block (currently all `"api"`) with the `"agent"` defaults and the `final_sweep` gate:

```json
  "dispatch_config": {
    "plan_reviewer": "agent", "verifier_batch": "agent", "verifier_per_task": "agent",
    "transition_combined": "agent", "docs_updater_phase": "agent", "docs_updater_final": "agent",
    "final_sweep": "agent"
  },
```

- [ ] **Step 2: Update the `dispatch_config` prose bullet**

Change the bullet (~line 181) to read:

```markdown
- **`dispatch_config`** (v2.22; extended v2.25) is run-level and spans the chain.
  Role gates — `plan_reviewer`, `verifier_batch`, `verifier_per_task`,
  `transition_combined`, `docs_updater_phase`, `docs_updater_final` — each
  `"p" | "api" | "agent"`, default `"agent"` (v2.25). `final_sweep` is
  `"api" | "batch" | "agent"`, default `"agent"`. `"agent"` dispatches the role
  in-session via the Agent tool on the subscription pool; see
  `references/cross-cutting/agent-dispatch.md`. Metered transports (`"api"`,
  `"p"`, `"batch"`) remain selectable per gate.
```

- [ ] **Step 3: Add the per-plan gap fields to the schema**

In the per-plan field list (the section listing `tasks`, `task_summaries`, etc.), add `verification_gaps` and `docs_gaps` as per-plan arrays (default `[]`), documenting them as: "populated by the agent-dispatch failure ladder (D003) when a load-bearing role cannot run after retry+api-fallback; rendered in the Final Summary Report."

- [ ] **Step 4: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n '"agent"' references/cross-cutting/state-schema.md && grep -n "final_sweep" references/cross-cutting/state-schema.md && grep -n "verification_gaps" references/cross-cutting/state-schema.md`
Expected: all three present.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/cross-cutting/state-schema.md
git commit -m "docs(v2.25): state-schema agent gate defaults + gap fields (per D001/D003)"
```

---

## Task 4: SKILL.md guardrail rows

**Files:**
- Modify: `SKILL.md` (the `dispatch_config is run-level` row ~line 272, the `API-direct dispatch is the v2.22 default` row ~line 277, the cross-cutting table)

- [ ] **Step 1: Update the `dispatch_config is run-level` guardrail row**

Replace its detail text so the gate enum reads `"p" | "api" | "agent"`, default `"agent"` (v2.25), and add `final_sweep` to the gate list with its `"api" | "batch" | "agent"` enum.

- [ ] **Step 2: Replace the `API-direct dispatch is the v2.22 default` row**

Retitle/rewrite to a v2.25 row:

```markdown
| **Agent dispatch is the v2.25 default** | Plan Reviewer, Verifier (batch + per-task), Transition (combined), Docs Updater, and the Phase 2 final sweep default to `"agent"` — in-session Agent-tool dispatch on the subscription pool (`references/cross-cutting/agent-dispatch.md`), NOT metered `claude -p` / Messages API. Set a gate to `"api"` or `"p"` (or `"batch"` for `final_sweep`) to opt back into a metered transport. The agent failure ladder auto-falls-back `agent → api` for a single failed dispatch (only sanctioned automatic fallback). |
```

- [ ] **Step 3: Add a cross-cutting table row**

In the "Cross-cutting references" table, add:

```markdown
| `references/cross-cutting/agent-dispatch.md` | The `"agent"` dispatch transport (subscription-pool Agent-tool dispatch), its failure ladder, and detach interaction (v2.25) |
```

- [ ] **Step 4: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n "agent dispatch is the v2.25 default\|Agent dispatch is the v2.25 default" SKILL.md && grep -n "agent-dispatch.md" SKILL.md`
Expected: both present.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/SKILL.md
git commit -m "docs(v2.25): SKILL.md guardrails for agent dispatch default (per D001)"
```

---

## Task 5: Phase -1 — detach conflict evaluation

**Files:**
- Modify: `references/phases/phase-minus-1-args-and-spawn.md` (after mode determination, ~line 98–102)

- [ ] **Step 1: Add the detach-conflict step**

After the mode is determined and before state.json is finalized, insert a "Detach/agent-gate reconciliation (v2.25)" step. It MUST: track, per gate, whether the value is explicit (from args/state) or the agent default; then, when `mode` resolves to a detached headless run (`detach=true`):

```markdown
**Detach/agent-gate reconciliation (v2.25, per D002).** A detached orchestrator
is a `claude -p` process, so its Agent sub-agents bill metered against the
parent — `"agent"` gates save nothing under detach. For each role gate:
- if the gate is at its **agent default** (not explicitly set by the user):
  rewrite it to `"api"` in `state.dispatch_config` and accumulate it into a
  single warning line.
- if the gate was **explicitly** set to `"agent"` by the user: leave it, and
  accumulate it into the warning line as "explicit — proceeding".
Emit ONE warning line to the interactive parent's stdout summarizing the
rewrites/retained gates, e.g.:
`DETACH+AGENT: verifier_per_task,docs_updater_phase fell back to api (agent default has no subscription benefit under detach); plan_reviewer kept (explicit).`
When `mode` is attached, this step is a no-op.
```

Note in the step that gate provenance (explicit vs default) must be captured during arg parsing — extend the existing parse pass to record a `dispatch_config_explicit` set (gate names the user set explicitly) in run state for this evaluation.

- [ ] **Step 2: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n "Detach/agent-gate reconciliation\|DETACH+AGENT" references/phases/phase-minus-1-args-and-spawn.md`
Expected: present.

- [ ] **Step 3: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-minus-1-args-and-spawn.md
git commit -m "docs(v2.25): Phase -1 detach/agent-gate reconciliation (per D002)"
```

---

## Task 6: Phase 0 — Plan Reviewer agent branch + state-init dispatch_config + model

**Files:**
- Modify: `references/phases/phase-0-setup.md` (Plan Reviewer dispatch ~line 385–391; state.json init block ~line 438–509)

- [ ] **Step 1: Add the `"agent"` branch to the Plan Reviewer dispatch**

In the Step 6.5 dispatch-mode block (which currently branches `"api"` default vs `"p"` legacy at lines 385–389), add an `"agent"` branch as the new default:

```markdown
   - `"agent"` (default, v2.25) → dispatch the Plan Reviewer in-session via the
     Agent tool per `references/cross-cutting/agent-dispatch.md` with
     ROLE=plan_reviewer, MODEL=opus (honor `dispatch_config.plan_reviewer_model`),
     PROMPT_TEMPLATE=`references/plan-reviewer-prompt.md`, RESULT_PATH=
     `<orch_dir>/plan_review.json`. Read + validate the result exactly as the
     metered paths do. Plan Reviewer is advisory: a missing/invalid result after
     the failure ladder's retry+api-fallback logs a warning and proceeds (no halt).
```

Update the "default `\"api\"`" annotation on the branch header to "default `\"agent\"` (v2.25)".

- [ ] **Step 2: Set the Plan Reviewer model note to Opus**

In the "Model selection (forensics)" paragraph (~line 391), change "runs on `claude-haiku-4-5-20251001` by default" to "runs on `claude-opus-4-7` by default (v2.25; mechanical rubric but Opus per the executor's Opus-everywhere preference; overridable via `state.dispatch_config.plan_reviewer_model`)".

- [ ] **Step 3: Add `dispatch_config` to the state.json init block**

The Step 7 state.json schema block (lines 438–509) does NOT currently list `dispatch_config` (it is only documented in state-schema.md). Add it to the written schema, run-level, with the v2.25 defaults:

```json
     "dispatch_config": {
       "plan_reviewer": "agent", "verifier_batch": "agent", "verifier_per_task": "agent",
       "transition_combined": "agent", "docs_updater_phase": "agent", "docs_updater_final": "agent",
       "final_sweep": "agent", "plan_reviewer_model": null
     },
     "verification_gaps": [],
     "docs_gaps": [],
```

Add a one-line note that `dispatch_config` is run-level (top of state.json, preserved across plan_chain swap) and that any gate the user passed explicitly, or any detach reconciliation from Phase -1, is applied before this write (do not overwrite a Phase -1 reconciliation). `verification_gaps`/`docs_gaps` are per-plan (move under `plan_chain[active]` for multi-plan runs).

- [ ] **Step 4: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n '"agent"' references/phases/phase-0-setup.md && grep -n "claude-opus-4-7" references/phases/phase-0-setup.md && grep -n "agent-dispatch.md" references/phases/phase-0-setup.md`
Expected: all present.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-0-setup.md
git commit -m "docs(v2.25): Phase 0 plan_reviewer agent branch + state init dispatch_config (per D001)"
```

---

## Task 7: Phase 1 — Verifier per-task agent branch + failure-ladder pointer

**Files:**
- Modify: `references/phases/phase-1-task-cycle.md` (Step 3 Verifier dispatch path ~line 256–271; Step 4 cost substep 1.5 ~line 322–345)

- [ ] **Step 1: Add the `"agent"` branch to the per-task Verifier dispatch**

After the existing per-task Verifier dispatch paths (legacy `-p` at lines 256–270 and the `verifier_per_task == "api"` paragraph at line 271), add:

```markdown
**Per-task Verifier `"agent"` path (v2.25, default).** When
`state.dispatch_config.verifier_per_task == "agent"`, dispatch the per-task
(MID/HIGH) Verifier in-session via the Agent tool per
`references/cross-cutting/agent-dispatch.md` with ROLE=verifier, MODEL=sonnet,
PROMPT_TEMPLATE=`references/verifier-prompt.md`, RESULT_PATH=
`<orch_dir>/verifier_results/task_<N>.json` (same path as the metered paths, so
step 4 parsing is unchanged). Apply the failure ladder: retry once →
auto-fallback to the `verifier_per_task="api"` dispatch for this one task → on
continued failure record `<active>.verification_gaps += [{task: "task_<N>",
reason, ts}]`, emit `kws-cme.blocker`, and proceed (do NOT halt; surface in the
Final Report). The consumed PASS/FAIL/ESCALATE shape is identical either way.
```

- [ ] **Step 2: Confirm the cost substep already covers Agent dispatch**

In Step 4 substep 1.5, the *Agent tool dispatch* usage-extraction bullet (line 328) already handles Implementer/Reviewer. Add Verifier/Docs/Plan-Reviewer to its parenthetical when dispatched via `"agent"`: change "(Implementer / Combined Reviewer)" to "(Implementer / Combined Reviewer / any role dispatched via the `"agent"` transport)". No new mechanism — the same `usage` extraction applies.

- [ ] **Step 3: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n 'verifier_per_task == "agent"' references/phases/phase-1-task-cycle.md && grep -n "verification_gaps" references/phases/phase-1-task-cycle.md`
Expected: both present.

- [ ] **Step 4: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-1-task-cycle.md
git commit -m "docs(v2.25): Phase 1 verifier agent branch + failure ladder (per D001/D003)"
```

---

## Task 8: Phase Transition — verifier_batch / transition_combined / docs_updater_phase agent branches

**Files:**
- Modify: `references/phases/phase-transition.md` (combined dispatch ~line 25–40)

- [ ] **Step 1: Add the `"agent"` branch to the combined transition**

After the existing `verifier_batch`/`docs_updater_phase` api paragraphs (lines 38–40), add:

```markdown
**Transition `"agent"` path (v2.25, default).** When
`state.dispatch_config.transition_combined == "agent"` (or, when the gates are
evaluated independently, `verifier_batch == "agent"` and
`docs_updater_phase == "agent"`), run the combined transition as a SINGLE
in-session Agent sub-agent per `references/cross-cutting/agent-dispatch.md` with
MODEL=sonnet, the existing combined prompt
(`<orch_dir>/transition_prompts/<plan_idx>_<compaction_index>.txt`), and
RESULT_PATH=`<orch_dir>/transition_results/<plan_idx>_<compaction_index>.json`.
The sub-agent writes the combined `{verify, docs}` JSON (do NOT split). Validate
against `transition_combined_result.schema.json`. Failure ladder: retry once →
auto-fallback to the api combined dispatch → on continued failure record the LOW
batch as `verification_gaps` and the phase docs as `docs_gaps`, emit
`kws-cme.blocker`, proceed.
```

- [ ] **Step 2: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n 'transition_combined == "agent"' references/phases/phase-transition.md && grep -n "single\|SINGLE" references/phases/phase-transition.md | grep -i agent`
Expected: branch present; single-sub-agent instruction present.

- [ ] **Step 3: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-transition.md
git commit -m "docs(v2.25): Phase Transition combined agent branch (per D001/D003)"
```

---

## Task 9: Phase 2 — docs_updater_final + final_sweep agent branches

**Files:**
- Modify: `references/phases/phase-2-finalization.md` (final sweep ~line 73; Final Docs Updater ~line 99–101; Final Report template in Step 2)

- [ ] **Step 1: Add the `"agent"` branch to the Final Docs Updater**

After the `docs_updater_final == "api"` paragraph (line 101), add:

```markdown
**Final Docs Updater `"agent"` path (v2.25, default).** When
`state.dispatch_config.docs_updater_final == "agent"`, dispatch in-session via
the Agent tool per `references/cross-cutting/agent-dispatch.md` with
ROLE=docs_updater, MODEL=sonnet, PROMPT_TEMPLATE=`references/docs-updater-prompts.md`
(Final section), RESULT_PATH matching the existing `{result_json_path}`. Failure
ladder: retry → api fallback → record `docs_gaps` + `kws-cme.blocker` + proceed.
```

- [ ] **Step 2: Add the `"agent"` branch to the Phase 2 Step 0 final sweep**

After the `final_sweep == "batch"` paragraph (line 73), add:

```markdown
When `state.dispatch_config.final_sweep == "agent"` (default, v2.25), the Step 0
LOW sweep dispatches each LOW task's Verifier in-session via the Agent tool per
`references/cross-cutting/agent-dispatch.md` (ROLE=verifier, MODEL=sonnet,
RESULT_PATH=`<orch_dir>/verifier_results/<task>.json`). Per-task failure ladder
applies; tasks that cannot be verified after retry+api-fallback are recorded in
`verification_gaps` and surfaced in the Final Report (not halted).
```

- [ ] **Step 3: Render gaps in the Final Summary Report template**

In the Step 2 `## Execution Summary` report template, add a dedicated row/section that lists `verification_gaps` and `docs_gaps` (per-plan, aggregated across the chain) when non-empty, e.g. `**Unverified (agent+api both failed):** task_7 (reason)`. When both arrays are empty across all plans, omit the section.

- [ ] **Step 4: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n 'docs_updater_final == "agent"' references/phases/phase-2-finalization.md && grep -n 'final_sweep == "agent"' references/phases/phase-2-finalization.md && grep -n "verification_gaps\|docs_gaps" references/phases/phase-2-finalization.md`
Expected: all present.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-2-finalization.md
git commit -m "docs(v2.25): Phase 2 final docs + sweep agent branches + gap reporting (per D001/D003)"
```

---

## Task 10: Phase 1 Escalation — AMBIGUITY/SPEC_BLOCKER best-judgment autonomy + halt boundary

**Files:**
- Modify: `references/phases/phase-1-escalation.md`

- [ ] **Step 1: Add the best-judgment autonomy section**

Add a "Autonomous resolution (v2.25, per D003)" section stating that for runtime `AMBIGUITY` and `SPEC_BLOCKER` escalations, the orchestrator MUST adopt the most defensible interpretation rather than marking the task SKIPPED, record the rationale in `state.spec_edits` (with `fault` and a one-sentence reasoning), proceed without SKIP, and surface the interpretation in the Final Report. It MUST NOT prompt the user for these runtime cases.

```markdown
## Autonomous resolution (v2.25, per D003)

For runtime `AMBIGUITY` (spec unclear) and `SPEC_BLOCKER` (spec
contradicts/missing) escalations, do NOT mark the task SKIPPED and report.
Instead:
1. Adopt the most defensible interpretation of the spec/plan for the task.
2. Append to `state.spec_edits` a record: `{task, fault, interpretation: "<one
   sentence>", ts, auto_resolved: true}` (no spec file edit unless the smallest
   clarifying edit is clearly correct, per the existing spec-edit branch).
3. Re-dispatch the Implementer with a `## [AUTO-INTERPRETATION]` note carrying
   the chosen reading. Proceed; do NOT SKIP and do NOT prompt the user.
4. Surface every `auto_resolved` interpretation in the Final Summary Report.
```

- [ ] **Step 2: State the halt boundary explicitly**

Add a "Halt boundary" note: best-judgment autonomy applies to runtime ambiguity only. Hard-halt is retained ONLY for (a) data-integrity failures (state.json write, `git reset`, worktree missing) and (b) Phase 0 pre-flight structural/config errors (out-of-repo paths, missing `Files:` blocks, no task headers) — malformed input where guessing is unsafe.

- [ ] **Step 3: Verify**

Run: `cd skills/kws-claude-multi-agent-executor && grep -n "AUTO-INTERPRETATION\|Autonomous resolution\|Halt boundary" references/phases/phase-1-escalation.md`
Expected: present.

- [ ] **Step 4: Commit**

```bash
git add skills/kws-claude-multi-agent-executor/references/phases/phase-1-escalation.md
git commit -m "docs(v2.25): escalation autonomy + halt boundary (per D003)"
```

---

## Task 11: Regression + consistency verification

**Files:**
- No edits — verification only. May fix inconsistencies surfaced here.

- [ ] **Step 1: Scaffold byte-stability lint (unchanged scaffolds must still pass)**

Run: `cd skills/kws-claude-multi-agent-executor && python3 scripts/validate_scaffold_split.py 2>&1 | tail -5` (path per skill convention; if the entrypoint differs, use the one referenced in Phase 0 Step 6.6).
Expected: PASS / no drift (we did not touch scaffold regions).

- [ ] **Step 2: Python tests green**

Run: `cd skills/kws-claude-multi-agent-executor && python3 -m pytest scripts/ -q`
Expected: PASS (Task 1's test plus all existing).

- [ ] **Step 3: Repo checks**

Run: `bun run check:legacy && git diff --check`
Expected: no failures, no whitespace errors.

- [ ] **Step 4: Gate-value consistency sweep**

Run: `cd skills/kws-claude-multi-agent-executor && grep -rn '"agent"' references/ SKILL.md | grep -c agent` and manually confirm every gate-branch site (Phase 0/1/transition/2) has an `"agent"` branch and references `agent-dispatch.md`.
Expected: branches present at all seven gate sites; no site left `"api"`-only as default.

- [ ] **Step 5: Eval harness smoke (optional but recommended)**

Run: `cd skills/kws-claude-multi-agent-executor && ./evals/run.sh 2>&1 | tail -20`
Expected: no regression vs baseline. (If the eval requires live dispatch/credits, note the result and defer to a manual attached run.)

- [ ] **Step 6: Update experiment status + close-out stub**

Update `docs/experiments/v2.25-subscription-agent-dispatch/README.md` Phase status table (Implementation → DONE) and add a `findings/F01-close-out.md` with the ship decision. Update `docs/experiments/README.md` index and the `../HISTORY.md` §3 table per AGENTS.md close-out protocol.

- [ ] **Step 7: Commit**

```bash
git add -A skills/kws-claude-multi-agent-executor/docs/experiments/v2.25-subscription-agent-dispatch/ skills/kws-claude-multi-agent-executor/docs/experiments/README.md skills/kws-claude-multi-agent-executor/docs/HISTORY.md
git commit -m "docs(v2.25): close-out + history index (per AGENTS.md)"
```

---

## Self-review notes (author)

- **Spec coverage:** README §1 gate value → T2/T3/T4; §2 default flip → T3/T4/T6; §3 dispatch pattern → T2 + per-phase T6–T9; §4 combined transition → T8; §5 detach → T5; §6 failure ladder + escalation autonomy → T2/T7/T8/T9/T10; §7 halt boundary → T10; Plan-Reviewer-Opus → T1/T6; affected-surface table → T3–T10. All covered.
- **No new undefined symbols:** the only code symbol is `DEFAULT_PLAN_REVIEWER_MODEL` (exists). `verification_gaps`/`docs_gaps` defined in T3, used in T7–T9. `agent-dispatch.md` created in T2, referenced T4/T6–T9.
- **Ordering:** T1 (script) and T2 (DRY anchor) precede the phase edits that reference them. T3 defines gap fields before T7–T9 use them.
- **Type consistency:** gate enum `"p" | "api" | "agent"` (final_sweep `"api" | "batch" | "agent"`) used identically across T3/T4/state-schema. Result paths reuse the exact existing `-p` paths so downstream parsing is untouched.
