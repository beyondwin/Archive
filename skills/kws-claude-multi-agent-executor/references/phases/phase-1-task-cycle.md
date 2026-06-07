# Phase 1: Per-Task Cycle

> **Loaded by**: `SKILL.md` Phase 1 entry stub — orchestrator MUST `Read` this
> file when it reaches Phase 1 and follow it for every task.
>
> **Scope**: the standard sequential per-task flow — Step 1 Dispatch Implementer,
> Step 2 Dispatch Combined Reviewer (including the P15 spec-edit branch and the
> standard retry branch), Step 3 Verifier (MID/HIGH only), Step 3.5 learning-log
> candidate scan, and Step 4 Agent Cleanup. For multi-task parallel groups
> (group size ≥ 2) the standard flow defers to the Parallel Sub-Flow in
> `references/phases/phase-1-parallel-subflow.md`.
>
> **Why extracted**: the per-task cycle is the largest single region of the
> skill and is only needed once Phase 0 setup is complete. Extraction is
> v2.21 D005 (extends v2.19 D001).

---

## Phase 1: Per-Task Cycle

Iterate `<active>.execution_plan` (waves outer, parallel groups inner). Within each parallel group:
- **Singleton group** (one task): run the standard sequential per-task flow described below (Steps 1–4).
- **Multi-task group** (size ≥ 2): run the **Parallel Sub-Flow** (described after the standard flow). Combined Reviewer and Verifier still run sequentially after the parallel Implementer merge.

Within a wave, parallel groups run sequentially (not in parallel with each other) — the second parallel group of the same wave starts after the first group's Reviewer + Verifier have completed. This keeps the post-merge state deterministic.

Advance only when the current task (or parallel group) reaches Agent Cleanup successfully.

> **Attached-mode hook preflight (v2.27, improvement #3).** Before dispatching the
> very first task, re-assert the worktree hooks are wired (a cheap belt-and-suspenders
> for the case where Step 2.5 was skipped or the settings.json was tampered):
> ```bash
> python3 <skill_dir>/scripts/materialize_worktree_hooks.py --check --worktree <worktree_path>
> ```
> Non-zero exit → hard halt: re-run the Phase 0 Step 2.5 materialize command, then
> retry. This runs once per run, before Task 1 only.

**Before Step 1 of each task:**
- Run `git -C <worktree_path> rev-parse HEAD` and **record the literal SHA** (e.g., `Task 3: pre_sha=abc1234`). Use this literal string in all subsequent revert and diff commands — do not use shell variables, which do not persist between Bash calls.
- **Stamp the pre-sha AND `timing.started` together via `phase_boundary.py task-start` (v2.21 — D002 enforcement):** these two writes were previously two separate prose R-M-W steps, and `timing.started` was the one that silently went null in every v2.11–v2.15 run. The helper bundles both into one atomic, flock-guarded, active-tree-resolved write so neither can be dropped:
  ```bash
  python3 <skill_dir>/scripts/phase_boundary.py task-start \
    --state "$ORCH_DIR/state.json" \
    --task task_<N> \
    --pre-sha <literal-sha-from-rev-parse>
  ```
  This writes run-level `current_pre_task_sha = <sha>` (the crash-recovery baseline — the Resume Protocol at Phase 0 Step 0 reads it to know where to roll back) and `<active>.tasks.task_<N>.timing.started = <now>` (initializing the task entry if absent). A **non-zero exit is a hard halt** — without `current_pre_task_sha` a resume could cherry-pick onto a corrupted HEAD. (The helper makes the timing write hard-fail too, an intentional strengthening of the old "non-fatal warning" policy: bundling it with the mandatory pre-sha removes the regression at its root.)
- **NEVER hand-write any `timing.*` value (v2.28 — D003).** The only sanctioned writers are `phase_boundary.py task-start` / `task-complete`, which stamp atomic UTC. A hand-typed stamp produced the run-3 TZ inversion — a KST wall-clock (`21:00:00Z`) written as if UTC, leaving `started` 9h *after* `completed`. `finalize_run.py` now emits an unconditional `timing_inverted` FAIL for any such impossible ordering, so a hand-typed value will block finalization.
- Update `current_task` in the state file (`state_set.py --field current_task --plan-scope run --value <N>`).

**Per-task counters (reset for each task — all are task-level):**
- `review_retries` — re-dispatches of Implementer due to Combined Reviewer FAIL (max 3)
- `verifier_retries` — re-dispatches due to Verifier FAIL (max 3)
- `escalation_count` — **task-level** counter of ESCALATE signals across all sub-agents this task (max 3 per task)
- `previous_issues` — Combined Reviewer ISSUES from the last retry (starts empty; used for retry-learning)

### Step 1: Dispatch Implementer

Build the implementer prompt from the **Implementer Prompt Template** below. Fill in:
- `{full text of the task}` — copy the entire task section verbatim, using whichever heading level Step 0.5 detected (`### Task N:` for H3 plans, `## Task N:` for H2 plans). Include all of the task's substeps and blocks up to the next header at the same or higher level.
- `{relevant spec excerpt}` — spec section(s) that govern this task. **v2.15 substitution rule (C1):**
  ```
  section_entry = <active>.spec_manifest.task_to_sections["task_<N>"]
  section_ids = section_entry["sections"]
  if "*" in section_ids:
    spec_text       = full spec file contents
    section_label   = "FULL (fallback)"
  else:
    lines = ["## Spec context (sections: " + ", ".join(section_ids) + ")", ""]
    for sid in section_ids (in spec_manifest order):
      section = <active>.spec_manifest.sections[sid]
      slice = spec_file_lines[section.range[0]-1 : section.range[1]]
      lines.extend(slice)
      lines.append("")
    spec_text       = "\n".join(lines)
    section_label   = ", ".join(section_ids)
  Substitute {relevant spec excerpt} → spec_text
  Substitute {spec_section_label} → section_label
  ```
  Implementer prompt template includes `{spec_section_label}` as a new placeholder (introduced in v2.15) — fill it from `section_label`.

  **SPEC_BLOCKER fallback (per spec §C1.4):** if the Implementer returns `ESCALATE` with `type: SPEC_BLOCKER` and `blocker` text matches the regex `(missing context|missing section|ambiguous reference|insufficient spec)` (case-insensitive):
    - If `<active>.spec_manifest.fallback_policy == "full_spec_on_blocker"`: re-dispatch the Implementer with the FULL spec inlined (set `section_ids=["*"]` for this dispatch only). Increment the task's `spec_clarifications` (NOT `review_retries` — per the P15 rule). Return to Step 1.
    - Else (`halt_on_blocker`): apply standard ESCALATE handling — no automatic full-spec retry.
- `{files to touch}` — from the task's **Files:** block
- `{risk level}` — from your Phase 0 assignment
- `{worktree_path}` — the worktree path
- `{deps_for_this_task}` — list of task IDs that this task depends on (from Phase 0 Step 6 dependency graph)
- `{context_slice}` — **v2.19 (T1.2); helper-extracted in v2.29 (I5).** Pre-resolved upstream context block that replaces the old "Read state.json" round-trip. The ~40-line derivation is no longer executed in the orchestrator's context — run the helper and inject its stdout verbatim:
  ```bash
  python3 <skill_dir>/scripts/build_context_slice.py "$ORCH_DIR/state.json" \
    --task task_<N> \
    --deps '<JSON array of upstream task IDs from the Phase 0 dependency graph>' \
    --files '<JSON array of this task's **Files:** block>' \
    [--plan-index <N for multi-plan>]
  Substitute {context_slice} → <helper stdout>
  ```
  `--deps` and `--files` are the small lists the orchestrator already holds (dependency graph + Files block it reads for `{files to touch}`); the helper reads `task_summaries` / `global_constraints.shared_files` / `global_constraints.text` from the active tree and assembles the block (degrading gracefully on the first task → `task_summaries: {} # no upstream deps`). The full derivation logic now lives in the helper's module docstring, not here. Equivalence with the prior in-prose output is locked by `scripts/test_build_context_slice.py`.

  **Detect fallback usage (v2.19):** parse `CONTEXT_SOURCE: <pre-resolved|fallback-read>` from the Implementer's STATUS output. If `fallback-read` appears: increment `state.metrics.context_fallback_count` (atomic R-M-W, non-fatal on failure) AND emit a `kws-cme.orchestrator_bug` learning_event candidate with `subagent.role=orchestrator`, `summary="Implementer fell back to state.json read — slice injection failed"`, severity=medium. Do NOT halt — the run continues, but the next compaction point should surface this for inspection.
- `{task_size}` — SMALL / MEDIUM / LARGE from `<active>.task_complexity.task_N` (P5)
- `{effort_guidance}` — the matching guidance string from Phase 0 Step 6 (P5)
- `{implementer_model}` — value of `state.implementer_model.used` ("sonnet" or "opus"). Used in the prompt header and the learning-log `subagent.model` field.
- `{decisions_register}` — **v2.15 decisions_register substitution (C2)**:
  ```
  register = <active>.decisions_register (list)
  if register is empty: spec_text = ""
  else:
    lines = ["## Project decisions so far (do NOT re-decide; raise objection via Reviewer if any seem wrong):"]
    for entry in register sorted by made_at ascending:
      if entry["supersedes"] is not None:
        prefix = "~~[SUPERSEDED by " + entry["supersedes"] + "]~~ "
      else:
        prefix = ""
      file_list = ", ".join(entry["files"]) if entry.get("files") else "(no files)"
      lines.append("- " + prefix + "[" + entry["task"] + "] " + entry["decision"] + " — " + file_list)
    spec_text = "\n".join(lines) + "\n\n"
  Substitute {decisions_register} → spec_text
  ```
  Empty register → placeholder substitutes to empty string (section omitted entirely). Superseded entries render with strikethrough prefix `~~[SUPERSEDED by task_X]~~`.

Re-dispatch rules (always append `## Fix Required\n{issues}`):
- After **Combined Reviewer FAIL** OR **Verifier FAIL**: include Required Skills bullet 5 (`receiving-code-review`). The skill's discipline (verify each issue is real before patching; push back on false positives like baseline drift or flaky tests) applies to verifier feedback the same as reviewer feedback.
- After cleanup-only re-dispatch (e.g., hook-blocked debug artifact): do NOT include bullet 5.

**Model selection (v2.12):** read `state.implementer_model.used`. Dispatch the Agent tool with `model: "<that value>"`. When the value is `"sonnet"`, you MAY omit the parameter (this is the agent default). When the value is `"opus"`, the `model` parameter MUST be set — omitting it silently downgrades to the agent default and invalidates the comparison. The dispatched sub-agent runs the same Implementer Prompt Template either way; only the model differs.

Fill in `{implementer_model}` in the prompt template with the same value (used downstream by the learning-log emit so `subagent.model` is accurate).

Dispatch as a **fresh sub-agent on the selected model** (default Sonnet; Opus when overridden).

**Result: DONE** → stamp `<active>.tasks.task_<N>.timing.implementer_done = <iso8601 now>` via atomic R-M-W (non-fatal warning on failure, same policy as `timing.started`). Proceed to Step 2.  
**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 2: Dispatch Combined Reviewer

Before dispatching, generate the diff for inline injection:
```bash
git -C <worktree_path> diff <pre_task_sha>..HEAD -- <files_changed>
```

Build the Combined Reviewer prompt from the **Combined Reviewer Prompt Template** below. Fill in:
- `{spec requirement text}` — same spec excerpt used in Step 1
- `{files changed}` — from the implementer's `FILES_CHANGED:` output
- `{inline diff}` — the git diff output captured above
- `{previous_issues}` — if `review_retries > 0`, the ISSUES list from the prior Combined Reviewer output; otherwise omit the section
- `{decisions_register}` — **v2.15 (C2)** — same substitution rule as the Implementer prompt (Phase 1 Step 1). Renders the `## Project decisions so far` block from `<active>.decisions_register`, or empty string if the register is empty. The Combined Reviewer's "Decision consistency" rubric reads from this block to flag `decision_conflict` QUALITY_ISSUES.

Dispatch as a **fresh Sonnet sub-agent**.

**Parse scores first (P4):** the Reviewer emits `SPEC_SCORE` and `QUALITY_SCORE` (0.0–1.0, 1-decimal). Compute the **tier** by combining both axes:

| Tier | Condition |
|------|-----------|
| **PASS** | `SPEC_SCORE >= 0.85` AND `QUALITY_SCORE >= 0.75` |
| **WARN** | (PASS not met) AND `SPEC_SCORE >= 0.70` AND `QUALITY_SCORE >= 0.60` |
| **FAIL** | otherwise (either score below the WARN floor) |

Record per-task into the active task tree at **`<active>.tasks.task_N`** (resolves per the placeholder rule — `state.plan_chain[state.active_plan].tasks.task_N` for multi-plan):
```json
"spec_score": <float>,
"quality_score": <float>,
"review_tier": "PASS | WARN | FAIL"
```

Rolling quality-trend buffer (active-tree-aware): the trend is appended automatically by `phase_boundary.py task-complete` whenever the task result carries `quality_score` — there is exactly one writer (v2.28 D003: max 10, drop oldest, active-tree-aware). Do NOT append it by hand here.
- After the trend is written, if length ≥ 5 AND mean of last 5 < mean of first 5 by > 0.10: surface at the NEXT compaction point (T3 message) — `"Quality trending down: last 5 tasks averaged X.XX vs first 5 at Y.YY. Consider manual review of recent tasks."`. Do NOT halt automatically.

Then branch on tier:

**Tier: PASS** → stamp `<active>.tasks.task_<N>.timing.reviewer_done = <iso8601 now>` via atomic R-M-W (non-fatal warning on failure). Proceed to Step 3.

**Tier: WARN** → stamp `<active>.tasks.task_<N>.timing.reviewer_done = <iso8601 now>` via atomic R-M-W (non-fatal warning on failure). Proceed to Step 3, but ALSO:
1. Record the QUALITY_ISSUES (and any non-blocking SPEC_ISSUES) under `<active>.task_summaries.task_N.warnings = [...]`.
2. Do NOT retry. WARN exists precisely to avoid burning a retry on borderline work that ships.
3. The Final Summary Report (Phase 2 Step 2) lists WARN tasks in a dedicated row so the user sees the pattern.
4. If three consecutive tasks land in WARN: surface at the next compaction point as a quality-trend signal even if the rolling mean rule did not trip.

**Tier: FAIL** — branch on the Reviewer's `SPEC_FAULT` field (added to the Combined Reviewer output schema; see template). The field is one of:

- `spec_contradicts` — spec is internally inconsistent or contradicts the task; Implementer cannot satisfy both.
- `implementer_omitted` — spec is clear; Implementer missed or misimplemented it.
- `unclear` — spec is ambiguous but not contradictory; Implementer guessed.
- `none` — used when `SPEC_STATUS: PASS` (no spec issue).

Decision table:

| SPEC_FAULT | QUALITY_STATUS | Action |
|------------|----------------|--------|
| `spec_contradicts` | any | **Spec-edit branch** (below). Do NOT count against `review_retries`. |
| `unclear` | any | **Spec-edit branch** with plan-clarification only (no spec text change). Do NOT count against `review_retries`. |
| `implementer_omitted` or `none` | PASS or FAIL | **Standard retry branch** (below). Counts against `review_retries`. |

**Spec-edit branch (P15):**
1. **Safety init:** if `state.spec_edits` is missing/null, set it to `[]` before append (handles legacy state.json).
2. Increment `task.spec_clarifications` (NOT `review_retries`). If `spec_clarifications > 3` for this task: halt this task as SKIPPED with reason "exceeded spec-clarification limit"; record in state.json and continue per SKIPPED propagation.
3. Orchestrator re-reads the affected spec section, makes the smallest possible edit, then **re-reads only the edited `spec_manifest.sections[<edited_sids>]` range (+ any directly dependent section) — NOT the full spec (v2.29 — I6)**. If the edit changed section boundaries/numbering (i.e. the manifest structure itself), first re-run `build_spec_manifest.py` (step 6.5 below) and re-read only the changed sections from the regenerated manifest. This keeps the post-edit integrity guarantee while removing the full-spec reload on every clarification.
4. Append to `state.spec_edits`:
   ```json
   {"task": "<id>", "spec_line": <N>, "reason": "<one sentence>", "commit": "<sha>", "ts": "<iso8601>", "fault": "spec_contradicts|unclear"}
   ```
5. Identify incomplete downstream tasks that overlap the edited spec section (compare each task's `Files:` + spec excerpt range against the edited line range stored in your internal task index). For those tasks' next Implementer dispatch: inject a `## [SPEC UPDATED]` section with the changed spec text.
6. Commit spec edit with message: `chore(<plan-slug>): clarify spec line <N> for task <id>`.
6.5. **Recompute spec_manifest (C1):** after the spec edit commit succeeds, re-run `python3 <skill_dir>/scripts/build_spec_manifest.py <spec_path>` and overwrite `<active>.spec_manifest.sections` in place. For each incomplete downstream task whose previous `task_to_sections.sections` overlap the edited line range, re-run the Step 6.3 heuristic for that task and update its `task_to_sections` entry. Append to the latest entry in `state.spec_edits`:
   ```json
   "manifest_recompute": true,
   "manifest_recompute_at": "<iso8601>"
   ```
7. Reset to pre-task SHA, re-dispatch Implementer from clean state. Return to Step 1.

**Standard retry branch:**
- Capture ISSUES (both SPEC_ISSUES and QUALITY_ISSUES) as `current_issues`. Increment `review_retries`.
- If `review_retries` ≤ 3:
  - **Retry-learning:** compare `current_issues` against `previous_issues` by matching ISSUE_KEY (exact match on file:line:category). Mark any issue whose ISSUE_KEY appears in both as `[RECURRING — previous fix did not address this]`.
  - **Record the attempt to `retry_trace` BEFORE overwriting `previous_issues` (v2.29 — I3):** the per-attempt fault/tier/RECURRING signal is the highest-value debugging input and was previously lost to the `previous_issues` overwrite. Append it append-only via the helper (orchestrator single writer; never hand-write the array):
    ```bash
    python3 <skill_dir>/scripts/phase_boundary.py retry-trace \
      --state "$ORCH_DIR/state.json" --task task_<N> --kind review \
      --fault "<SPEC_FAULT class>" --tier "<PASS|WARN|FAIL>" \
      --recurring-json '<JSON array of RECURRING ISSUE_KEYs, or omit>' --attempt <review_retries>
    ```
  - Set `previous_issues = current_issues`.
  - Re-dispatch Implementer with `## Fix Required\n{issues with RECURRING labels}`. Return to Step 1.
- If `review_retries` > 3: **SKIP + continue (v2.29 — I1; aligned with the escalation-cap behavior, NOT a run halt).** The last hard stop inside Phase 1 is removed — an exhausted review retry budget is the same class of bounded-retry exhaustion as the escalation cap (`references/phases/phase-1-escalation.md` lines 41-49), so it self-heals the same way:
  1. Mark the task SKIPPED: `state_set.py --field tasks.task_<N>.status --value '"SKIPPED"'` and `state_set.py --field tasks.task_<N>.skip_reason --value '"review_retries_exhausted"'`.
  2. Record the gap: `state_set.py --field verification_gaps --append-json '{"task":"task_<N>","kind":"review","last_issues":<current previous_issues>,"attempts":<review_retries>,"ts":"<iso8601>"}'`. (`verification_gaps` is the existing D003 gap-marker array — no new machinery, reused per the Step 3 `"agent"` path precedent.)
  3. Emit the blocker (with the I2 local tee): `python3 <skill_dir>/scripts/phase_boundary.py emit --state "$ORCH_DIR/state.json" --run-id "${ORCH_RUN_ID:-}" --type blocker --payload-json '{"task":"task_<N>","reason":"review_retries_exhausted"}'`.
  4. **SKIPPED propagation:** unstarted tasks that depend on this one follow the Phase 0 Step 6 SKIPPED-propagation rule (same as escalation-cap and Verifier-agent gaps).
  5. Proceed to the next task. The run does NOT halt — the gap renders in the Final Report / `run_report.json`.

### Step 3: Verifier (MID/HIGH tasks only)

**If task risk is LOW:** skip this step. Add the task to `low_tasks_pending_verification` in the state file. Proceed to Step 4.

**If task risk is MID or HIGH:** build the Verifier prompt from the **Verifier Prompt Template** below. Fill in:
- `{MID | HIGH}` — the risk level
- `{files changed}` — from implementer output
- `{baseline}` — passing/failing counts from Phase 0
- `{test_command}` — from state.json `test_command`
- `{acceptance_criteria}` — the `## Acceptance Criteria` shell block from the task, or "none provided"
- `{result_json_path}` — `<orch_dir>/verifier_results/task_<N>.json`

**Dispatch as a headless `claude -p` subprocess (not Agent tool):**
1. Write the prompt to `<orch_dir>/verifier_prompts/task_<N>.txt` using the Write tool.
2. Create the results directory:
   ```bash
   mkdir -p <orch_dir>/verifier_results
   ```
3. Run the Verifier:
   ```bash
   claude -p --dangerously-skip-permissions "$(cat <orch_dir>/verifier_prompts/task_<N>.txt)" \
     > <orch_dir>/verifier_results/task_<N>.stdout 2>&1
   ```
4. Read the result file: `<orch_dir>/verifier_results/task_<N>.json`
   - If the file exists and is valid JSON: parse `status` field for PASS/FAIL/ESCALATE.
   - If the file is missing or malformed: treat as ESCALATE with `type: ENV_BLOCKER, blocker: "Verifier subprocess produced no result file — check task_<N>.stdout for diagnostics"`.

**Per-task Verifier dispatch path (v2.22 §2.B1).** When `state.dispatch_config.verifier_per_task == "api"`, dispatch this per-task (MID/HIGH) Verifier through `scripts/dispatch_via_api.py --role verifier` instead of the legacy `claude -p` subprocess above (structured tool `report_verifier`, `tool_choice`-forced; the result is validated against `references/_schemas/verifier_result.schema.json`). Write the result to the SAME path the legacy flow uses — `<orch_dir>/verifier_results/task_<N>.json` — so the PASS/FAIL/ESCALATE parsing in step 4 and the result handling below are unchanged. When `verifier_per_task == "p"` (or absent), use the legacy `claude -p` flow described above. The gate selects only the dispatch transport; the role token is `verifier` (singular) and the consumed result shape is identical either way.

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

**Result: PASS** → stamp `<active>.tasks.task_<N>.timing.verifier_done = <iso8601 now>` via atomic R-M-W (non-fatal warning on failure). Proceed to Step 4.  
**Result: FAIL** →
- Increment `verifier_retries`.
- If `verifier_retries` ≤ 3:
  - Reset to pre-task state: `git -C <worktree_path> reset --hard <pre_task_sha>`
  - **Record the attempt to `retry_trace` (v2.29 — I3):** append-only, before re-dispatch:
    ```bash
    python3 <skill_dir>/scripts/phase_boundary.py retry-trace \
      --state "$ORCH_DIR/state.json" --task task_<N> --kind verify \
      --fault "<verifier category>" --attempt <verifier_retries>
    ```
  - Re-dispatch Implementer with verifier's `issues` from the JSON under `## Fix Required`. Include `receiving-code-review` (per Phase 1 Step 1 re-dispatch rules) — verifier feedback can be wrong (baseline drift, flaky tests), so the skill's "verify before patching" discipline applies. Return to Step 1.
- If `verifier_retries` > 3: **SKIP + continue (v2.29 — I1; same alignment as the review-retry branch above, NOT a run halt).** Before marking SKIPPED, **preserve the reset discipline** so no partial change survives:
  1. `git -C <worktree_path> reset --hard <pre_task_sha>` — return the working tree to the pre-task state (the SKIP guardrail still requires a clean tree; partial verified-but-failing changes must not persist).
  2. Mark the task SKIPPED: `state_set.py --field tasks.task_<N>.status --value '"SKIPPED"'` and `state_set.py --field tasks.task_<N>.skip_reason --value '"verifier_retries_exhausted"'`.
  3. Record the gap: `state_set.py --field verification_gaps --append-json '{"task":"task_<N>","kind":"verify","last_issues":<verifier issues>,"attempts":<verifier_retries>,"ts":"<iso8601>"}'`.
  4. Emit the blocker (with the I2 local tee): `python3 <skill_dir>/scripts/phase_boundary.py emit --state "$ORCH_DIR/state.json" --run-id "${ORCH_RUN_ID:-}" --type blocker --payload-json '{"task":"task_<N>","reason":"verifier_retries_exhausted"}'`.
  5. **SKIPPED propagation** per Phase 0 Step 6, then proceed to the next task. The run does NOT halt.

**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 3.5: Learning-log candidate scan (v2.8)

Once per task cycle, after Step 3 completes (or after Step 2 for LOW tasks
that skip Verifier), check the candidate directory for any event files
written by Implementer / Reviewer / Verifier during this cycle and forward
them in a single batch:

```bash
CANDIDATE_DIR="<orch_dir>/learning_events"
if [ -d "$CANDIDATE_DIR" ]; then
  for cand in "$CANDIDATE_DIR"/task_<N>-*.json; do
    [ -f "$cand" ] || continue
    # Publish to AgentLens. Derive event type from candidate's own event_type field.
    if [ -n "${ORCH_RUN_ID:-}" ]; then
      ETYPE=$(jq -r '.event_type // ""' "$cand" 2>/dev/null)
      if [ -n "$ETYPE" ]; then
        agentlens event append --run "$ORCH_RUN_ID" \
          --type "kws-cme.$ETYPE" \
          --payload-json "@$cand" \
          2>/dev/null || true
      fi
    fi
    mv "$cand" "$cand.appended"  # mark consumed; avoid double-emit
  done
fi
```

Emit failures are silent (`|| true`) — observability must not block execution. Candidate files are renamed `.appended` after consumption to prevent duplicate emission on the next cycle step. Sub-agents writing fresh candidates always overwrite (per-task-per-role one file at a time).

**v2.17 cutover (Task 11):** the legacy `append_learning_event.py append` call was removed from this drain after AgentLens parity was verified. AgentLens emit derives its `--type` from the candidate's `event_type` field (`blocker`, `verification_failure`, `reviewer_warn_or_fail`, `context_health`, etc.) prefixed with `kws-cme.` per the spec §6.2 taxonomy. If `ORCH_RUN_ID` is empty (AgentLens absent), the candidate is still consumed (`.appended`) — it is not retried, and execution continues. Use `scripts/compare_agentlens_events.py` to audit parity on historical runs that still have a legacy `events.jsonl` alongside an AgentLens stream.

### Step 4: Agent Cleanup

You (Orchestrator) perform these checks directly — no sub-agent needed:

1. **Debug artifact scan — REMOVED in v2.5.0.** This check is now runtime-enforced by the `PostToolUse(Edit|Write)` hook at `<orch_dir>/hooks/scan-debug-artifacts.sh` (materialized at Phase 0 Step 2.5). If an Implementer attempted to write `console.log|debugger|TODO|FIXME` outside of allow-listed contexts, the hook already exit-2'd and the Implementer auto-retried before reaching this step. No orchestrator-side grep needed.

   If you suspect the hook was misfired or disabled (e.g., user manually edited settings.json mid-run): re-enable and continue. Do not re-introduce the manual grep — it duplicates the hook and was the silent-bypass risk that motivated P1.

1.5. **Accumulate cost (F2 — v2.16 helper-script enforced):**

   **MANDATORY for every `"api"`/`"p"` (metered) dispatch.** Pre-v2.16 runs left `cost_ledger.totals.dispatches=0` across every observed run because this step was prose-only and got silently skipped. For metered transports, always call `scripts/accumulate_cost.py` — it does the price lookup, R-M-W of state.json under flock, and aggregation for you. The orchestrator's job is reduced to (a) extracting `usage` from the just-completed dispatch, (b) calling the helper.

   **Extract `usage`:**

   - *Agent tool dispatch* (Implementer / Combined Reviewer / any role dispatched via the `"agent"` transport): the Agent tool returns only the sub-agent's final message to this turn — there is **no `usage` object** the orchestrator can read. Per-dispatch cost is therefore **not observable** on the `"agent"` transport; this is why an attached, all-`agent` run sets `cost_tracking_waived` at Phase 0 (D001) and skips this step entirely. Do NOT fabricate a `{0,0}` usage call on the agent path — the auto-waive (Phase 0 Step 7) supersedes it. Only the `"api"` / `"p"` transports surface usage; opt a gate into `"api"`/`"p"` to get cost + budget enforcement.
   - *Headless `claude -p --output-format stream-json` subprocess* (Verifier / Plan Reviewer / Docs Updater on the `"p"` transport, or any `"api"` dispatch): tail the result file `<orch_dir>/{verifier,docs,plan_review}_results/...` OR the matching `.stdout`. The final line of stream-json is `{"type":"result","usage":{...},...}`. Extract `usage`, normalize to the helper's field names: `cached_read_tokens` ← `cache_read_input_tokens`, `cached_write_tokens` ← `cache_creation_input_tokens`.

   **Invoke the helper:**

   ```bash
   python3 <skill_dir>/scripts/accumulate_cost.py \
     --state "<orch_dir>/state.json" \
     --task-id "task_<N>" \
     --role "implementer|reviewer|verifier|plan_reviewer|docs_updater" \
     --model "<state.implementer_model.used for implementer; 'sonnet' for reviewer/verifier/docs/plan_reviewer; 'unknown' if missing>" \
     --usage-json '<JSON string of normalized usage>' \
     >/dev/null 2>&1 || echo "COST_ACCUMULATE: failed (non-fatal; ledger may under-count this dispatch)"
   ```

   The helper's exit code is intentionally NOT enforced (`|| echo`) — accumulation failure is observability degradation, not a correctness issue. The next compaction-point budget check (Phase Transition T3 step 4) reads whatever is in the ledger.

   **by_task key shape:** `<active_plan>::<task_id>::<role>` so implementer + reviewer + verifier each persist under the same task without overwriting each other. Same-role retries overwrite (latest dispatch wins); by_role / by_model / totals always increment so cumulative spend stays correct across retries.

   **Failure modes (metered paths only):**
   - Missing `usage` block on an `"api"`/`"p"` result (transport error, schema drift) → call helper with `{"input_tokens":0,"output_tokens":0}` and `--model unknown`. Cost recorded as 0, dispatch count still increments.
   - `state.json` write failure inside helper → helper exits 1; orchestrator logs and continues (no halt — this is the F2 budget guardrail's downside vs. the state-file write guardrail; budget tracking is best-effort by design).
   - `price_table` import failure → helper exits 1 at startup; same handling.

   **Agent-default runs (v2.28, D001):** when every role gate is `"agent"` and the run is `interactive_attached`, Phase 0 Step 7 already set `cost_tracking_waived=true` / `cost_tracking_waive_reason="agent-dispatch-no-usage"` — there is no ledger to populate here and budget enforcement is intentionally off (see `references/cross-cutting/agent-dispatch.md`). This step is a no-op on the all-agent path.

   **Budget evaluation** (Phase Transition T3 step 4 and Phase 2 Step 0) reads `state.cost_ledger.totals.cost_usd` and compares to `state.budget_cap_usd`. It is meaningful only when at least one gate is metered (`"api"`/`"p"`); on the all-agent default the ledger stays empty and budget enforcement plus the token-based chain-resume trigger are disabled by design (the accepted cost of the subscription-pool default).

2. **Update state file** — write this task's result into the active task tree.

   **Write mechanism (v2.21 — D002 enforcement):** do NOT hand-write the result, the `timing.completed` stamp, the `last_completed_*` pointers, and the `task_completed` emit as four separate prose R-M-W / emit steps (that scatter is exactly what historically dropped one or another). Assemble the full `task_N` result object (schema below, including the `method_audit` and `timing` sub-objects populated by the steps that follow), write it to `<orch_dir>/task_results/task_<N>.json`, then commit it with one call:
   ```bash
   python3 <skill_dir>/scripts/phase_boundary.py task-complete \
     --state "$ORCH_DIR/state.json" \
     --task task_<N> \
     --result-json "$ORCH_DIR/task_results/task_<N>.json" \
     --run-id "${ORCH_RUN_ID:-}"
   ```
   In one atomic, active-tree-resolved, flock-guarded write the helper: (a) writes the result object under `<active>.tasks.task_<N>`, (b) forces `timing.completed = now`, (c) advances `<active>.last_completed_task` / `last_completed_at`, then (d) emits `kws-cme.task_completed` (best-effort; empty `--run-id` → no emit). A non-zero exit means the state write failed — hard halt. **The fields below are the result object you hand the helper, NOT four independent writes.**

   **NEVER hand-write `timing.completed` (or any `timing.*`) into the result object (v2.28 — D003).** The helper stamps it atomically in UTC at (b) above; the `timing` sub-object you assemble must NOT carry a hand-typed `completed` value. A hand-typed stamp produced the run-3 TZ inversion (a KST `21:00:00Z` written as UTC, landing `started` 9h *after* `completed`), which `finalize_run.py` now catches as an unconditional `timing_inverted` FAIL that blocks finalization.

   **Active tree selection (v2.13):** the helper resolves the active tree internally (`state.plan_chain[state.active_plan].tasks.task_N` for multi-plan, `state.tasks.task_N` for single-plan; `state.active_plan` is an **integer** when `plan_chain` is in use). `task_summaries` (step 2.2) and `decisions_register` (step 2.3) are separate writes — use `state_set.py --field` for those, same active-tree rule.

   ```json
   "task_N": {
     "status": "COMPLETE",
     "risk": "<level>",
     "complexity": "<SMALL|MEDIUM|LARGE>",
     "files": ["<file1>", "..."],
     "files_test": ["<test_file1>", "..."],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "spec_clarifications": 0,
     "spec_score": <float 0.0-1.0>,
     "quality_score": <float 0.0-1.0>,
     "review_tier": "PASS | WARN",
     "method_audit": {
       "required": ["test-driven-development", "verification-before-completion", "code-review-pass"],
       "applied": [
         {"skill": "test-driven-development",
          "evidence": {"red": "<cmd>", "green": "<cmd>", "tests": ["<path>"]}},
         {"skill": "verification-before-completion",
          "evidence": {"commands_run": ["<cmd1>", "<cmd2>"]}},
         {"skill": "code-review-pass",
          "evidence": {"findings_count": <N>, "locations": ["<file:line>"]}}
       ],
       "missing": [],
       "waived": []
     },
     "timing": {
       "started": "<iso8601>",
       "implementer_done": "<iso8601>",
       "reviewer_done": "<iso8601>",
       "verifier_done": "<iso8601>",
       "completed": "<iso8601>"
     }
   }
   ```

   **Canonical task keys (v2.28 — D003).** The `tasks{}` key is ALWAYS `task_<N>` (e.g. `task_3`) — never a bare integer (`"3"`) and never a free-form label (`"riskclose"`). Remediation or otherwise-inserted tasks use the suffixed form `task_<N>_<suffix>` (e.g. `task_7_remediation`). The same canonical key is used everywhere the task is referenced: `risk_levels`, `execution_plan`, `task_complexity`, and `task_summaries`. `scripts/validate_state_schema.py` emits a `task_key_noncanonical` WARN (run-1 wrote bare-int + ad-hoc keys). `task_summaries` is a legacy read-mirror (step 2.2) — it is still written for backward compatibility, but no NEW consumer should write to it; the result object under `tasks.task_<N>` is the source of truth.

   `files_test` comes from the Implementer's `FILES_TEST_CHANGED:` output (empty list if none). `complexity` comes from `<active>.task_complexity.task_N` (set in Phase 0 Step 6 per P5). `spec_score` / `quality_score` / `review_tier` come from Phase 1 Step 2 score parsing — PASS or WARN reached this point; FAIL would have looped back to Step 1.

   **`timing.completed` (v2.16):** do NOT stamp this by hand — `phase_boundary.py task-complete` (the write mechanism above) forces `timing.completed = now` as part of the bundled write. The result object you pass carries the *other* timing fields you collected during the cycle — `timing.started` (set at Phase 1 entry by `task-start`), `timing.implementer_done` (set on Implementer DONE), `timing.reviewer_done` (set on Combined Reviewer PASS/WARN), and `timing.verifier_done` (set on Verifier PASS — null for LOW tasks deferred to batch). Together these give the Final Summary Report a complete per-task wall-time breakdown.

   **Latest pointers (P14)** — `last_completed_task` / `last_completed_at` are advanced by the same `task-complete` call (active-tree resolved); do NOT write them separately. They are required for Monitor and any consumer that needs "most recent task". Do NOT rely on JSON insertion order — this skill re-writes state.json many times and key order is unreliable (observed bug: a later spec-edit re-touch of an earlier task moved it to the end of insertion order, breaking `to_entries | last`).

   **v2.11 — Populate `method_audit`:**

   1. Read the Implementer's final output (captured in this turn's Agent tool result). Parse each `METHOD_AUDIT:` line:
      - `<skill> applied <kv pairs>` → append `{"skill": <skill>, "evidence": <parsed kv>}` to `method_audit.applied`.
      - `<skill> waived reason=<text>` → append `{"skill": <skill>, "reason": <text>}` to `method_audit.waived`.
   2. Read the Combined Reviewer's output. Parse the `REVIEW_FINDINGS:` line:
      - `count=<N> locations=<list>` → append `{"skill": "code-review-pass", "evidence": {"findings_count": <N>, "locations": <list>}}` to `method_audit.applied`.
      - `no-findings residual-risk=<text>` → append `{"skill": "code-review-pass", "evidence": {"findings_count": 0, "residual_risk": <text>}}` to `method_audit.applied`.
   3. Read the Verifier result JSON (if dispatched — Phase 1 Step 3 for MID/HIGH; deferred to Phase Transition T1 or Phase 2 Step 0 for LOW). Append `{"skill": "verification-before-completion", "evidence": {"commands_run": <list>}}` to `method_audit.applied`. For LOW tasks awaiting batch verification, write the populator note `pending_batch_verification: true` in `method_audit` and resolve it in T1 / Phase 2 Step 0.
   4. Compute `required` from the docs-only heuristic: `files_test == []` OR (`files_test` missing AND all `files` end with `.md`) → `["verification-before-completion"]`. Else → `["test-driven-development", "verification-before-completion", "code-review-pass"]`.
   5. Compute `missing = required - applied_skills - waived_skills`. (This is informational — Phase 2 Step 1.5 is authoritative.)

   Also write to `task_summaries.task_N` (same active-tree rule):
   ```json
   {
     "files": ["<file1>", "..."],
     "exposed_apis": ["<new function/class/constant names added>"],
     "key_decision": "<≤15 words: the most important choice made>",
     "for_next_tasks": "<≤30 words: what downstream tasks must know — contracts, types, naming>"
   }
   ```

2.3. **Append to decisions_register (C2):**
   After writing `task_summaries.task_N`, read its `key_decision`. If the value is non-empty AND not `"(none)"` AND not `"n/a"` (case-insensitive after stripping): append to `<active>.decisions_register` (creating the list if absent):
   ```json
   {
     "task": "task_<N>",
     "decision": "<key_decision text, verified ≤15 words>",
     "files": ["<files from task_summaries>"],
     "made_at": "<iso8601 now>",
     "supersedes": null
   }
   ```
   Atomic R-M-W of state.json. If the write fails: log a warning, continue (decisions_register is best-effort enrichment, NOT load-bearing). The register accumulates per plan and is projected to `DECISIONS.md` at each Phase Transition T3 and at Phase 2 Step 1 (see Task 9).

2.5. **(Removed — no orchestrator-state commits.)**
   Orchestrator state lives at `<orch_dir>/` (outside the worktree, untracked by git). The Implementer's `feat:` commit from Step 1 is the only commit per task. State persistence is via atomic R-M-W of `<orch_dir>/state.json` with readback. For forensic snapshots see the post-run archive step (Phase 2) which tarballs `<orch_dir>/` to `archive.path`.
   This keeps implementation commits (`feat:`) separate from orchestrator state commits (`chore:`). Reviewers can filter `git log --grep '^feat'` to see only code changes.

2.6. **`kws-cme.task_completed` event (v2.17; emitted by the helper since v2.21):** this is one of the four explicit orchestrator emit sites (alongside `phase_0_started` at Phase 0 Step 7.5, `compaction` at T3, and `phase_2_complete` at Phase 2 Step 2). It is **no longer a separate step** — the `phase_boundary.py task-complete` call in step 2 emits it automatically *after* the state write succeeds, deriving the payload (`task`, `status`, `risk`, `review_tier`, `commit`) from the result object you handed it. Bundling the emit with the write is the whole point: the emit can no longer be silently dropped while the state write happens. Emit is best-effort (empty `--run-id` → no emit; non-zero `agentlens` exit swallowed). `task_completed` is an AgentLens-only transition (no legacy counterpart); the candidate-drain in Step 3.5 covers sub-agent emits and fires regardless.

3. **Check for compaction point:** if this task is a compaction point, go to **Phase Transition** before advancing. Otherwise, advance to the next task.

