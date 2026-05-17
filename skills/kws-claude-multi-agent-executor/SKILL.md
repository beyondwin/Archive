---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation. NOTE — single-session execution is preferable for ≤5-task plans or plans with deep cross-task coupling (multi-agent overhead exceeds the parallelism win).
metadata:
  version: "2.15.0"
  updated_at: "2026-05-16"
---

# KWS Claude Multi-Agent Executor

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
| `state.plan_chain` present (v2.13 multi-plan) | `state.plan_chain[state.active_plan]` |
| `state.plan_chain` absent + `state.active_plan == "plan2"` (v2.12 legacy two-plan) | `state.plan2_state` |
| Otherwise (single-plan, or `state.active_plan == "plan1"`) | `state` (top-level) |

**Per-plan fields** (live under `<active>`, NOT directly under `state` in multi-plan runs):
`tasks`, `task_summaries`, `quality_trend`, `baseline`, `low_tasks_pending_verification`, `global_constraints`, `compaction_points`, `execution_plan`, `risk_levels`, `task_complexity`, `last_compaction_after_task`, `last_completed_task`, `last_completed_at`, `plan_review`.

**Run-level fields** (always at top-level `state.*`, shared across all plans in a chain):
`active_plan`, `plan_chain`, `implementer_model`, `spec_edits`, `test_command`, `mode`, `branch`, `worktree`, `timestamps`, `chain_resume`, `plan`, `spec` (legacy mirrors of plan_chain[0]).

Every read or write to a per-plan field MUST go through `<active>` resolution. Hard-coding `state.tasks` or `state.quality_trend` for a multi-plan run silently corrupts the chain: plan 0's data writes to top-level while plan 1's writes to `plan_chain[1]`, and the two trees diverge. The placeholder is **not optional** — wherever you see `<active>.foo` below, substitute the correct path before reading or writing.

In bash/jq fragments throughout the skill (e.g., Monitor scripts), the same rule applies via the `active_plan` dispatch:

```bash
if jq -e '.plan_chain' state.json >/dev/null 2>&1; then
  ACTIVE='.plan_chain[.active_plan]'
elif [ "$(jq -r '.active_plan' state.json)" = "plan2" ]; then
  ACTIVE='.plan2_state'
else
  ACTIVE='.'
fi
```

Use `$ACTIVE.tasks`, `$ACTIVE.quality_trend`, etc. in jq queries downstream.

---

## Phase -1: Mode Selection (Autonomy Gate)

At invocation, before any other work:

### Phase -1.0: Argument Parser (v2.13)

Args are a mix of explicit `key=value` pairs and free-text natural-language hints, separated by whitespace. Order doesn't matter. Parse in three deterministic passes:

**Pass 1 — collect `key=value` pairs.**

Recognized keys: `plan`, `plan2`, `plan3`, …, `planN`, `spec`, `spec2`, `spec3`, …, `specN` (matching plan numbers), `implementer_model`, `parallel`, `risk`, `docs_scope`, `mode`, `manifest`, `budget`, `budget_action`, `context_budget`, `context_threshold`, `manifest_fallback`. Each appears as `key=value` with no surrounding spaces around `=`. Unknown keys → halt: `"Unknown argument: <key>=<value>"`.

`budget=<USD>` is a positive float or zero. Negative → halt with `Invalid budget=<value>; must be ≥ 0.`
`budget_action=<value>` must be one of `pause`, `warn`, `off`. Else halt with `Unknown budget_action=<value>. Allowed: pause, warn, off.`
`context_budget=<int>` (v2.15 — C3) is a positive integer > 10000. Else halt: `Invalid context_budget=<value>; must be int > 10000.` Default `170000`.
`context_threshold=<float>` (v2.15 — C3) is a float in `[0.05, 0.95]`. Else halt: `Invalid context_threshold=<value>; must be float in [0.05, 0.95].` Default `0.60`.
`manifest_fallback=<value>` (v2.15 — C1) must be one of `full_spec_on_blocker`, `halt_on_blocker`. Else halt: `Unknown manifest_fallback=<value>. Allowed: full_spec_on_blocker, halt_on_blocker.` Default `full_spec_on_blocker`.
NL lexicon: no entries added for budget or context — explicit-only by design.

**Pass 2 — multi-plan auto-detection.**

- Collect every key matching `^plan(\d*)$`. Treat `plan=` as index 0, `planN=` as index N−1 (so `plan2=` is index 1, matching the v2.12 convention). This yields a set of plan indices.
- Required: index 0 (`plan=`) is always present. Halt if missing: `"Missing required arg: plan=<path>"`.
- Gaps in the numeric sequence halt: e.g. `plan=A plan3=C` (missing `plan2=`) → `"Plan index gap: expected plan2= but only plan, plan3 provided. Renumber consecutively or fill the gap."`
- For each present `planN=`, the matching `specN=` must also be present (with the same suffix). Missing pair → halt: `"plan<N>= present but spec<N>= missing"`.
- If `manifest=` is also present → halt: `"manifest= is mutually exclusive with planN=/specN= args."` (manifest support is reserved; the auto-detection covers the use case.)
- Result: an ordered list `[(plan_path_0, spec_path_0), (plan_path_1, spec_path_1), ...]`. Length 1 → single-plan run (v2.12 schema). Length ≥ 2 → multi-plan run (v2.13 `plan_chain[]` schema; see Phase 0 Step 7).

**Pass 3 — natural-language keyword lexicon (v2.13).**

Tokenize the args by whitespace and process every token NOT consumed by Pass 1 (i.e., free text not matching `key=value`).

For each token:

1. **Skip exclusion guards.** If the token contains any of `/`, `.`, `=`, or backtick → skip (paths or code-like; never match).
2. **Strip Korean particles.** Korean grammatical particles attach without word boundaries, so Python `\b` regex doesn't catch them (e.g., `오푸스로` is one `\w+` token). Strip the **longest matching trailing particle** from the token once. Particle suffixes in priority order (longest first):
   - `적으로`, `에서`, `으로`, `적인`, `적`, `로`, `을`, `를`, `이`, `가`, `의`, `에`
   
   Examples: `오푸스로` → `오푸스`; `순차적으로` → `순차`; `대화형으로` → `대화형`; `직렬로` → `직렬`; `시리얼로` → `시리얼`; `소넷이` → `소넷`. If no particle matches, keep the token as-is. ASCII tokens are unaffected by this step (no Korean particles to strip).
3. **Lowercase the stripped token** (case-insensitive match for ASCII; Korean has no case).
4. **Exact-match against the lexicon.**

Lexicon (exact match on the stripped+lowercased token; word-boundary regex `\b` works only after particle stripping):

| Stripped token | Maps to |
|----------------|---------|
| `opus`, `오푸스` | `implementer_model=opus` |
| `sonnet`, `소넷` | `implementer_model=sonnet` |
| `순차`, `sequential`, `직렬`, `시리얼` | `parallel=off` |
| `대화형`, `interactive` | `mode=interactive` |

The reference implementation lives at `docs/experiments/v2.13-natural-multi-plan/bench/nl_parser_reference.py` — the orchestrator's prose interpretation MUST produce the same parse result as that script. Test fixtures at `bench/test_nl_parser.py` validate the script against every example in `examples/invocations.md`.

Application rule (explicit always wins):
- If the corresponding key was already set in Pass 1 AND the NL match agrees → no-op (record `"NL keyword '<word>' agrees with explicit <key>=<value>"` in the echo).
- If the corresponding key was already set in Pass 1 AND the NL match contradicts → halt with: `"Argument conflict: explicit <key>=<val_explicit> contradicts natural-language '<word>' (→ <val_nl>). Remove one or align them."`
- If the corresponding key was unset → set it from the NL match.
- If two NL matches map to the same key with different values (e.g., args contain both "opus" and "sonnet" as free text) → halt with: `"Natural-language conflict: '<word1>' (→ <val1>) and '<word2>' (→ <val2>) both target <key>. Disambiguate explicitly."`

**Echo line (v2.13 — required output before self-spawn or Phase 0).**

After Pass 3, output ONE line to the user summarizing the resolved interpretation, before doing any other work:

```
Parsed: <N> plan(s) [<index 0 slug>→<index 1 slug>→...], implementer_model=<value> [from <source>], parallel=<value> [from <source>], mode=<value> [from <source>], risk=<value or "per-task">, budget=<value or "off"> [from <source>].
```

The `budget=<value or "off">` field in the echo line shows the parsed `budget=<USD>` value (e.g. `budget=5.00`) or the literal string `off` when no `budget=` arg was provided. This lets the user see the cost cap before detach.

`<source>` is one of: `explicit` (Pass 1 set it), `NL '<word>'` (Pass 3 set it from a keyword), or `default` (not set; using built-in default). The slug is derived from the plan filename per Phase 0 Step 2 rule.

The user sees this single line and can interrupt if interpretation is wrong. In headless mode (`mode=interactive` not set), the line still prints to the interactive parent's stdout before self-spawn.

### Phase -1.1: Mode detection

After Phase -1.0 parsing:

1. If parsed args contain `mode=interactive` (any source — explicit or NL): legacy single-session mode — skip Phase -1, proceed to Phase 0.
2. If invocation prompt contains literal `<<HEADLESS_KWS_ORCHESTRATOR>>` anywhere: this is the headless instance — skip Phase -1, proceed to Phase 0.
3. Otherwise: execute Self-Spawn Procedure below, then exit.

### Self-Spawn Procedure

**a. Run Phase 0 Steps 1, 1.5, 2, 2.5 in interactive context.**

Execute Phase 0 Step 1 (working tree clean check), Step 1.5 (cross-run isolation checks — mode exclusivity + orphan-worktree report; v2.10.1), Step 2 (worktree creation), and Step 2.5 (safety hooks) now, in the interactive session. These steps are quick (~2 min) and must complete before the subprocess starts — the subprocess requires an existing worktree to operate in. If any of these steps fail, abort the spawn and surface the failure to the user. Do NOT proceed to step b.

**b. Initialize a minimal `.orchestrator/state.json` in the worktree.**

All arg-derived values come from Phase -1.0's three-pass parser (`implementer_model`, plan/spec pairs, `parallel`, `mode`, etc.). The headless subprocess will NOT re-parse args — only the headless prompt text reaches it, NOT the original args. The interactive parent persists everything needed into state.json here.

Validate `implementer_model` value: must be `opus` or `sonnet` (case-insensitive). Unknown value → halt: `"Unknown implementer_model=<value>. Allowed: opus, sonnet."` Unset → use `"sonnet"`.

**Multi-plan vs single-plan write rules (v2.13):**

If the parsed plan list has length 1: write the minimal state.json in v2.12 shape (no `plan_chain` field):

```json
{
  "schema_version": "2",
  "mode": "headless_pending",
  "interactive_setup_complete": true,
  "plan": "<plan_path_0>",
  "spec": "<spec_path_0>",
  "branch": "<branch name>",
  "worktree": "<worktree path>",
  "implementer_model": {"used": "<parsed value or sonnet>", "default": "sonnet"},
  "timestamps": {
    "interactive_setup_at": "<iso8601 now>",
    "headless_started_at": null,
    "completed_at": null
  }
}
```

If the parsed plan list has length ≥ 2: write the v2.13 multi-plan minimal state.json. `state.plan` / `state.spec` mirror index 0 for legacy reader compatibility; the authoritative source is `plan_chain[]`:

```json
{
  "schema_version": "2",
  "mode": "headless_pending",
  "interactive_setup_complete": true,
  "plan": "<plan_path_0>",
  "spec": "<spec_path_0>",
  "branch": "<branch name>",
  "worktree": "<worktree path>",
  "implementer_model": {"used": "<parsed value or sonnet>", "default": "sonnet"},
  "plan_chain": [
    {"index": 0, "plan_path": "<plan_path_0>", "spec_path": "<spec_path_0>", "status": "running",
     "blocked_until": null, "baseline": null,
     "tasks": {}, "task_summaries": {}, "quality_trend": [],
     "risk_levels": {}, "task_complexity": {}, "compaction_points": [],
     "execution_plan": [], "global_constraints": {"shared_files": {}},
     "low_tasks_pending_verification": [], "last_compaction_after_task": -1,
     "last_completed_task": null, "last_completed_at": null,
     "plan_review": {"status": "SKIPPED", "warnings": []}},
    {"index": 1, "plan_path": "<plan_path_1>", "spec_path": "<spec_path_1>", "status": "queued",
     "blocked_until": "plan_chain[0].all_tasks_complete_or_skipped",
     "baseline": null, "tasks": {}, "task_summaries": {}, "quality_trend": [],
     "risk_levels": {}, "task_complexity": {}, "compaction_points": [],
     "execution_plan": [], "global_constraints": {"shared_files": {}},
     "low_tasks_pending_verification": [], "last_compaction_after_task": -1,
     "last_completed_task": null, "last_completed_at": null,
     "plan_review": {"status": "SKIPPED", "warnings": []}},
    {"index": 2, "...same as index 1 with own paths...": "..."}
  ],
  "active_plan": 0,
  "timestamps": {
    "interactive_setup_at": "<iso8601 now>",
    "headless_started_at": null,
    "completed_at": null
  }
}
```

Fill in actual values. Each `plan_chain[i].blocked_until` references the previous index (`plan_chain[i-1].all_tasks_complete_or_skipped`) for i≥1; index 0 has `blocked_until: null`.

Full state.json fields (baselines, risk_levels for each plan, etc.) will be populated by the headless instance — once for each plan_chain entry as its turn comes up.

**Why everything is set HERE (v2.13 propagation rule):** Phase -1 step c writes `headless_prompt.txt` with no arg propagation, and `claude -p` in step d sees only that prompt — not the original skill args. If parsing were deferred to the child, both the model override and the multi-plan list would be lost. The child reads `implementer_model`, `plan_chain` (if multi-plan), and `plan/spec` (single-plan) from state.json in its resume path; it does NOT re-parse skill args. See Phase 0 Step 7 "field rule" below.

**c. Write the headless prompt at `<worktree_path>/.orchestrator/headless_prompt.txt`:**

```
<<HEADLESS_KWS_ORCHESTRATOR>>
You are the kws-claude-multi-agent-executor running HEADLESSLY. No user available.
Working directory: <abs worktree path>
Plan: <plan path>
Spec: <spec path>

Resume protocol applies — read .orchestrator/state.json. If state shows mode=headless_pending, proceed with full Phase 0 (analysis, baseline, dependency graph, state population). Otherwise resume from current_task.

Run Phase 0 → Phase 1 → Phase 2 to completion. NEVER ask for user input.
Halt only on: per-task escalation_count > 3 (record SKIPPED, continue) OR all tasks COMPLETE/SKIPPED.
On completion, write .orchestrator/HEADLESS_DONE.txt with summary.
On critical failure, write .orchestrator/HEADLESS_HALTED.txt with diagnostics.

Begin.
```

Fill in `<abs worktree path>`, `<plan path>`, `<spec path>` with the actual resolved paths before writing.

**d. Spawn detached background process:**

```bash
WORKTREE_ABS="$(cd <worktree> && pwd -P)"
nohup claude -p --dangerously-skip-permissions \
  --output-format stream-json \
  "$(cat "$WORKTREE_ABS/.orchestrator/headless_prompt.txt")" \
  > "$WORKTREE_ABS/.orchestrator/headless.jsonl" 2>&1 &
echo $! > "$WORKTREE_ABS/.orchestrator/headless.pid"
disown
```

**d.5. Verify spawn lived past startup**:
   ```bash
   sleep 3
   if ! kill -0 $(cat "$WORKTREE_ABS/.orchestrator/headless.pid") 2>/dev/null; then
     echo "FATAL: headless subprocess died within 3 seconds. Check $WORKTREE_ABS/.orchestrator/headless.jsonl for diagnostic." >&2
     # Read first 50 lines of headless.jsonl and surface to user; do NOT proceed to step e (no Monitor)
     exit 1
   fi
   ```
   If spawn died: report failure to user with diagnostic; do NOT continue.

**e. Report to user (final message before exit):**

```
Orchestrator running headless.
Worktree: <abs path>
PID: $(cat .orchestrator/headless.pid)

Monitor live (stream-json events):
  tail -f <worktree>/.orchestrator/headless.jsonl | jq -c 'select(.type=="text" or .type=="tool_use")'

Status snapshot:
  jq 'def active: if .plan_chain then .plan_chain[.active_plan] elif .active_plan=="plan2" then .plan2_state else . end; {current_task, mode, completed: (active.tasks | to_entries | map(select(.value.status=="COMPLETE")) | length)}' <worktree>/.orchestrator/state.json

Completion check:
  test -f <worktree>/.orchestrator/HEADLESS_DONE.txt && cat <worktree>/.orchestrator/HEADLESS_DONE.txt

Quick queries (no LLM, ~10ms each):
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> progress
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> cost
  <skill_dir>/scripts/query_state.sh --worktree <abs_path> warn

Post-run, archived analysis:
  <skill_dir>/scripts/query_run.sh list-runs
  <skill_dir>/scripts/query_run.sh last cost
```

Fill in `<abs path>` and `<worktree>` with the actual worktree path before outputting.

**e′. Real-time progress notifications via Monitor**

After confirming the spawn lived (step d.5), set up live progress notifications:

1. Load the Monitor tool if not already available: `ToolSearch("select:Monitor")`
2. Invoke Monitor with `persistent: true` and the following watcher script:

```bash
WT="$WORKTREE_ABS"
prev_c=0; prev_s=0

while true; do
  # Re-read PID each loop — Resume Chain (see below) may have replaced it.
  HEADLESS_PID=$(cat $WT/.orchestrator/headless.pid 2>/dev/null || echo "")
  if [ -f $WT/.orchestrator/state.json ]; then
    # Resolve active task tree (v2.13 plan_chain[N] > v2.12 plan2_state > top-level).
    HAS_CHAIN=$(jq -r '.plan_chain != null' $WT/.orchestrator/state.json 2>/dev/null)
    AP=$(jq -r '.active_plan // "plan1"' $WT/.orchestrator/state.json 2>/dev/null)
    if [ "$HAS_CHAIN" = "true" ]; then
      TASKS_FILTER=".plan_chain[$AP].tasks"
      LATEST_FILTER=".plan_chain[$AP].tasks"
      LABEL="plan_chain[$AP]"
    elif [ "$AP" = "plan2" ]; then
      TASKS_FILTER='.plan2_state.tasks'
      LATEST_FILTER='.plan2_state.tasks'
      LABEL="plan2"
    else
      TASKS_FILTER='.tasks'
      LATEST_FILTER='.tasks'
      LABEL="plan1"
    fi
    cur_c=$(jq -r "[$TASKS_FILTER[]|select(.status==\"COMPLETE\")]|length" $WT/.orchestrator/state.json 2>/dev/null || echo 0)
    cur_s=$(jq -r "[$TASKS_FILTER[]|select(.status==\"SKIPPED\")]|length" $WT/.orchestrator/state.json 2>/dev/null || echo 0)
    if [ "$cur_c" != "$prev_c" ] || [ "$cur_s" != "$prev_s" ]; then
      # P14: read explicit last_completed_task field (NOT JSON insertion order).
      # last_completed_task lives under <active> for multi-plan; resolve same way.
      LCT_PATH=$(jq -r "if .plan_chain then .plan_chain[.active_plan].last_completed_task elif .active_plan==\"plan2\" then .plan2_state.last_completed_task else .last_completed_task end" $WT/.orchestrator/state.json 2>/dev/null)
      if [ "$LCT_PATH" != "null" ] && [ -n "$LCT_PATH" ]; then
        latest=$(jq -r "$LATEST_FILTER[\"$LCT_PATH\"] | \"$LCT_PATH \\(.status) risk=\\(.risk) review_retries=\\(.review_retries // 0)\"" $WT/.orchestrator/state.json 2>/dev/null)
      else
        latest="(no task recorded yet)"
      fi
      echo "[$(date +%H:%M:%S)] [$LABEL] $latest | totals: ${cur_c}C ${cur_s}S"
      prev_c=$cur_c; prev_s=$cur_s
    fi
  fi
  test -f $WT/.orchestrator/HEADLESS_DONE.txt && echo "[$(date +%H:%M:%S)] DONE: $(head -1 $WT/.orchestrator/HEADLESS_DONE.txt)" && exit 0
  test -f $WT/.orchestrator/HEADLESS_HALTED.txt && echo "[$(date +%H:%M:%S)] HALTED: $(head -1 $WT/.orchestrator/HEADLESS_HALTED.txt)" && exit 1
  if [ -n "$HEADLESS_PID" ] && ! kill -0 $HEADLESS_PID 2>/dev/null; then
    # Grace period for Resume Chain handoff — .pid is rewritten by the child.
    sleep 2
    NEW_PID=$(cat $WT/.orchestrator/headless.pid 2>/dev/null || echo "")
    if [ "$NEW_PID" != "$HEADLESS_PID" ] && [ -n "$NEW_PID" ] && kill -0 $NEW_PID 2>/dev/null; then
      echo "[$(date +%H:%M:%S)] CHAIN_HANDOFF: PID $HEADLESS_PID → $NEW_PID"
    else
      echo "[$(date +%H:%M:%S)] PROCESS_DIED unexpectedly (PID $HEADLESS_PID gone, no DONE/HALTED file)"
      exit 2
    fi
  fi
  sleep 30
done
```

This emits one notification per task transition + final DONE/HALTED/DIED. Polling 30s; 다수-시간 실행에 persistent 필수. User sees task-level progress in chat without manual polling.

**f. Exit cleanly.** Do NOT attempt to monitor the subprocess in the interactive context.

### Resume Chain (for plans that exceed single subprocess context)

**Trigger (v2.15 — token-aware, deterministic, introspectable):**

Chain when ANY of the following holds at Phase Transition T3 (or at end of Phase 1 Step 4 if `current_task` is in `<active>.compaction_points`):

1. **Token threshold (NEW, primary):**
   - Requires `state.budget_action != "off"` AND `state.cost_ledger` present.
   - Compute: `session_input_tokens = state.cost_ledger.totals.input_tokens - state.cost_ledger.totals.cached_read_tokens`.
   - Threshold: `state.context_budget.threshold_tokens` (default `102000` = 60% of `170000`; see Task 11).
   - Fire if `session_input_tokens >= threshold_tokens`.

2. **Legacy floor (PRESERVED, fallback):**
   - `<active>.compaction_points_reached >= 2` AND count of `COMPLETE` tasks `>= 8`.
   - Always evaluated regardless of `budget_action`.

If both evaluate true, record `trigger_reason = "token_threshold"` (first-observed wins). If only the legacy floor fires, record `trigger_reason = "legacy_floor"`. If neither fires, no chain.

`budget_action == "off"` disables the token trigger (legacy floor becomes sole criterion). Cache-read tokens are excluded from `session_input_tokens` so retry sessions don't double-count.

Procedure:

1. Pre-generate a UUID for the resume session: `RESUME_UUID=$(uuidgen)`. Store in state.json `chain_resume.session_id`.
2. Flush state: set `mode: "headless_chained"`, write `chain_resume: {session_id: $RESUME_UUID, from_task: <N>, parent_pid: <current PID>, chained_at: "<iso8601>"}`. Verify state.json is readable after write (per existing State-file write guardrail). If write fails: hard halt — do NOT spawn child.
3. Write the chain prompt file:
   ```bash
   cat > "$WORKTREE_ABS/.orchestrator/headless_chain_<N>_prompt.txt" <<EOF
   <<HEADLESS_KWS_ORCHESTRATOR>>
   Continue from state.json. Worktree: $WORKTREE_ABS.
   EOF
   ```
   (Note: use unquoted heredoc so `$WORKTREE_ABS` interpolates.)
4. Spawn child AND atomically swap the PID file so the Monitor watcher (step e′) picks up the new process. **Pass `MAE_LEARNING_RUN_ID` explicitly** so the chained orchestrator continues writing to the same learning-log run (v2.8):
   ```bash
   env MAE_LEARNING_RUN_ID="${MAE_LEARNING_RUN_ID:-}" \
     nohup claude -p --session-id "$RESUME_UUID" --dangerously-skip-permissions \
     --output-format stream-json \
     "$(cat "$WORKTREE_ABS/.orchestrator/headless_chain_<N>_prompt.txt")" \
     > "$WORKTREE_ABS/.orchestrator/headless_chain_<N>.jsonl" 2>&1 &
   CHILD_PID=$!
   disown
   # Atomic-ish swap: write-then-rename
   echo $CHILD_PID > "$WORKTREE_ABS/.orchestrator/headless.pid.new"
   mv "$WORKTREE_ABS/.orchestrator/headless.pid.new" "$WORKTREE_ABS/.orchestrator/headless.pid"
   sleep 3
   kill -0 $CHILD_PID 2>/dev/null || { echo "FATAL: chain child died within 3s" >&2; exit 1; }
   ```
5. Parent exits **without calling `close-run`** — the run is still alive in the child. Child takes over. The Monitor watcher re-reads `headless.pid` each loop (see step e′) so the handoff is observed as `CHAIN_HANDOFF`, not `PROCESS_DIED`.

6. **Chained child startup (v2.8 learning log):** at Phase 0 Step 0 (Resume Protocol), after detecting `state.mode == "headless_chained"`, the chained orchestrator runs:
   ```bash
   if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
     python3 <skill_dir>/scripts/append_learning_event.py append-session-id \
       --run-id "$MAE_LEARNING_RUN_ID" \
       --session-id "${CLAUDE_SESSION_ID:-$RESUME_UUID}" >/dev/null 2>&1 || true
   fi
   ```
   It does NOT call `init-run` — that would fragment the run record. If `MAE_LEARNING_RUN_ID` is unset (env not propagated, helper missing), it proceeds without learning-log support rather than starting a new run.

   **After `append-session-id` succeeds, emit a `context_health` snapshot (v2.10):** the chained orchestrator writes a candidate JSON to `<worktree>/.orchestrator/learning_events/chain_handoff-orchestrator.json` and `append`s it. Use `phase: "phase_0"`, `execution.task_id: "chain_handoff"`, `execution.issue_key: "context_health_snapshot"`, `context.compaction_index: -1`, `context.completed_tasks_count: <count of COMPLETE tasks from state>`, `context.resume_chain_handoffs: <new len(session_ids) - 1>`. This marks the boundary in the event stream so downstream analysis can attribute pre/post-handoff metrics. Append failure is silent.

This is a fallback — the primary expectation is that one headless subprocess completes a typical 10-25 task plan within its own context budget.

---

## Phase 0: Setup

0. **Check for existing state file (Resume Protocol):**
   Check if `<worktree_path>/.orchestrator/state.json` exists by attempting to read it.
   - If it does NOT exist: proceed normally to Step 1.
   - If it EXISTS and is valid JSON with `schema_version: "2"`:
     - If `"mode": "headless_pending"`: freshly-spawned headless instance — Phase -1 already ran Steps 1, 1.5, 2, 2.5 in interactive context and wrote minimal state. **MUST skip Phase 0 Steps 1, 1.5, 2, 2.5** (clean check, cross-run isolation, worktree creation, safety hooks — re-running breaks: `git status` flags pre-written `.orchestrator/` and `.claude/settings.json` as dirty; `git worktree add` errors on the existing branch; Step 1.5 mode-exclusivity check would self-block on the freshly-created `.orchestrator/headless.pid`). PROCEED with Phase 0 Step 0.5 onward (`0.5 → 3 → 3.5 → 4 → 5 → 6 → 7`) to populate baseline, risk_levels, compaction_points, full task data. After Step 7, update `state.json.mode` from `"headless_pending"` to `"headless_running"` and write. **Preserve `state.implementer_model` exactly as the parent wrote it (v2.12)** — the parent already parsed the skill arg; do NOT overwrite. If the field is absent (legacy state.json), default to `{"used": "sonnet", "default": "sonnet"}`. **Preserve `state.plan_chain` exactly as the parent wrote it (v2.13)** — the parent already parsed the plan/plan2/.../planN args and constructed the chain. The child reads plan paths from `state.plan_chain[state.active_plan].plan_path` for multi-plan runs; do NOT re-parse skill args. If `plan_chain` is absent → this is a single-plan run, read from top-level `state.plan` and `state.spec`.
     - If `"mode": "headless_running"`, `"headless_chained"`, `"plan2_running"`, `"interactive_session"`, or no mode field: Standard resume path — load all fields. Do NOT overwrite. Verify git branch and worktree match `state.branch` / `state.worktree`. Set internal tracking from state.json: `current_task`, `current_step_within_task`, `current_pre_task_sha`, per-task counters. Output: "Resuming from state file: Task <N>, Step <M> (mode=<value or null>)." Skip Phase 0 Steps 1–7 (setup already done). Go directly to Phase 1 at the recorded task/step.
     - **Legacy state.json defaults (v2.14 — RUN-LEVEL fields):** before continuing the resume, backfill the four v2.14 run-level fields if missing (pre-v2.14 state.json will not have them). Apply each as a `setdefault` (write-only-if-absent) at the TOP level of `state` (NOT inside `plan_chain[i]`):
       - `state.setdefault('cost_ledger', {"by_task": {}, "by_role": {}, "by_model": {}, "totals": {"input_tokens": 0, "output_tokens": 0, "cached_read_tokens": 0, "cached_write_tokens": 0, "cost_usd": 0.0, "dispatches": 0}})`
       - `state.setdefault('budget_cap_usd', None)`
       - `state.setdefault('budget_action', 'warn')`
       - `state.setdefault('archive', None)`
       If `state.cost_ledger` is already present (v2.14+ state.json), preserve it as-is and continue accumulating. Same for `budget_cap_usd` and `budget_action`. These fields span the whole chain, so the resume MUST NOT reset them on plan2 swap or chain handoff.
   - If it EXISTS but is invalid (empty, malformed JSON):
     - Warn user: "State file exists but is corrupted at <path>. Recommend manual inspection before proceeding."
     - Do NOT overwrite. Halt.

0.5. **Validate plan file (pre-flight):**
   Read the plan file. Before proceeding:
   - If the file is unreadable or missing: halt. "Plan file not found or unreadable at <path>."
   - **Detect task header level (v2.17):** scan for both `### Task N:` (H3) and `## Task N:` (H2) section headers via case-sensitive line-anchored regex `^(##|###)\s+Task\s+\d+:`. Resolve which level the plan uses:
     - If `### Task N:` matches exist: use H3 (`### `). This is the canonical format; H2 occurrences (if any) are treated as Phase headers per Step 3.
     - Else if `## Task N:` matches exist: use H2 (`## `). The plan's internal `### N. <step>` substeps under each task are then *substeps*, NOT tasks — the detected level is what scoping uses for "the task block".
     - Else: halt. "Plan has no `## Task N:` or `### Task N:` sections. Cannot execute."
   - Hold the detected prefix in your internal notes as `task_header_prefix` (literal string `"### "` or `"## "`). It is persisted into `<active>.task_header_prefix` at Step 7. Every later mention in this SKILL.md of `### Task N:` (Steps 3, 3.5, 6, prompt placeholders) refers to "Task N: at the detected level"; substitute `task_header_prefix` when constructing regex or instructions for sub-agents.
   
   This gate runs before worktree creation — structural failures cost zero infrastructure.

1. **Check working tree is clean:**
   ```bash
   git status
   ```
   If there are uncommitted changes, stop immediately. Tell the user: "Working tree is dirty. Please commit or stash changes before running multi-agent-executor." Do not proceed.

1.5. **Cross-run isolation checks (v2.10.1):**
   These run in the **outer repo** (not in any worktree) and catch state that prior crashed runs left behind. Two independent checks:

   **(a) Mode exclusivity** — refuse to start if another run is alive. Enumerate all worktrees matching this skill's pattern via `git worktree list --porcelain | awk '/^worktree /{print $2}'`. For each candidate path:
   ```bash
   pid_file="$path/.orchestrator/headless.pid"
   done_file="$path/.orchestrator/HEADLESS_DONE.txt"
   halted_file="$path/.orchestrator/HEADLESS_HALTED.txt"
   if [ -f "$pid_file" ] && [ ! -f "$done_file" ] && [ ! -f "$halted_file" ]; then
     pid=$(cat "$pid_file")
     if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
       echo "BLOCKED: active run at $path (PID $pid). Halt with 'kill $pid' or wait for HEADLESS_DONE.txt. To force-clear after confirming the process is dead, remove $pid_file." >&2
       exit 1
     fi
   fi
   ```
   On detection: halt with the message above. Do NOT silently proceed — concurrent runs on the same source repo can race on git fetches, the user-local learning log, and the parent-repo branch namespace.

   **(b) Stale-worktree report (advisory, NOT auto-delete)** — for any worktree path matching this skill's pattern with **no `.orchestrator/state.json`** AND mtime > 7 days, list it to the user once:
   > "Orphan worktrees detected (no state.json, last modified >7d ago):
   >   - `<path1>` (<age> days)
   >   - `<path2>` (<age> days)
   > These appear to be from interrupted runs. Inspect manually with `ls <path>/.orchestrator/` and remove with `git worktree remove <path> --force && git worktree prune` if no in-progress work. Continuing with this run."

   **Do NOT auto-delete.** A worktree with no state.json may still hold uncommitted manual debugging work; the user must decide. The report is one-shot per invocation; it does not halt.

   **Headless skip:** when the resume protocol detects `mode == "headless_pending"`, this step is part of the "MUST skip" set (already covered by Phase -1's interactive run).

2. **Create worktree:**
   - First invoke `Skill("superpowers:using-git-worktrees")` and follow its guidance.
   - Capture the timestamp once now (e.g., `20260508-143022`) — use the **same value** for both the branch name and the worktree path.
   - Before executing: run `git branch --list "<plan-slug>-*"` to check for an existing branch with the same slug prefix. If a match is found and no state.json exists at the expected worktree path (i.e., this is not a resume): ask the user — "Branch <name> already exists with no state file. Rename with a new timestamp suffix, or halt?" Do not silently overwrite.
   - Execute:
   ```bash
   git worktree add -b <plan-slug>-<YYYYMMDD-HHMMSS> ../worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>
   ```
   Derive `plan-slug` from the plan filename: lowercase, replace spaces and underscores with hyphens, strip the date prefix (e.g., `2026-05-08-my-feature.md` → `my-feature`).

2.5. **Write worktree safety hooks + gate hooks (P1):**
   Create `.claude/settings.json` and the helper-script directory inside the worktree:
   ```bash
   mkdir -p <worktree_path>/.claude
   mkdir -p <worktree_path>/.orchestrator/hooks
   ```

   **Materialize hook scripts** by copying the templates from this skill's `references/hooks/` into the worktree, stripping the `.template` suffix and making them executable:
   ```bash
   cp <skill_dir>/references/hooks/scan-debug-artifacts.sh.template \
      <worktree_path>/.orchestrator/hooks/scan-debug-artifacts.sh
   cp <skill_dir>/references/hooks/check-implementer-output.sh.template \
      <worktree_path>/.orchestrator/hooks/check-implementer-output.sh
   chmod +x <worktree_path>/.orchestrator/hooks/*.sh
   ```
   `<skill_dir>` is the directory containing this SKILL.md. Resolve via `dirname` of the skill path or the absolute path captured when the skill was invoked.

   **Write `<worktree_path>/.claude/settings.json`**:
   ```json
   {
     "hooks": {
       "PreToolUse": [{
         "matcher": "Bash",
         "hooks": [{
           "type": "command",
           "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -qE 'rm\\s+-rf\\s+/|git\\s+push\\s+--force\\s+(origin\\s+)?(main|master|trunk)|DROP\\s+(TABLE|DATABASE|SCHEMA)\\s'; then echo 'BLOCKED: dangerous command detected' >&2; exit 1; fi"
         }]
       }],
       "PostToolUse": [{
         "matcher": "Edit|Write",
         "hooks": [{
           "type": "command",
           "command": "<worktree_path>/.orchestrator/hooks/scan-debug-artifacts.sh"
         }]
       }],
       "SubagentStop": [{
         "hooks": [{
           "type": "command",
           "command": "<worktree_path>/.orchestrator/hooks/check-implementer-output.sh"
         }]
       }]
     }
   }
   ```
   Substitute `<worktree_path>` with the actual absolute worktree path before writing.

   **What each hook does:**
   - `PreToolUse` (Bash) blocks `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA` in sub-agent Bash calls. Does NOT block `git reset --hard` — the orchestrator uses it for verifier-fail recovery.
   - `PostToolUse` (Edit|Write) — `scan-debug-artifacts.sh` — runtime-enforced debug-artifact gate. On detection of `console.log|debugger|TODO|FIXME` in added content (outside string literals and `*.md` paths), exits 2; Claude Code surfaces the failure to the sub-agent which retries the edit. Replaces the prose-only Phase 1 Step 4.1 grep (now removed) — discipline lives in the runtime, not in the loop.
   - `SubagentStop` — `check-implementer-output.sh` — STATUS sanity check on Implementer output. Verifies presence of `STATUS:`, `SUMMARY:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:` (and `COMMIT:` when STATUS=DONE; ESCALATE fields when STATUS=ESCALATE). Missing field → exit 2 → orchestrator receives failure and re-dispatches.

   **Why this layering matters (P1):** prior versions kept these checks in prose (Orchestrator-driven), so a context drift or malformed reply could silently skip the gate. With hooks they cannot be bypassed.

3. **Read both documents fully:**
   - Read the plan document. Extract the ordered task list: every section whose header matches the detected `task_header_prefix` from Step 0.5 followed by `Task N:` (so either `### Task N:` for H3 plans or `## Task N:` for H2 plans). Capture each task's full text from its header up to the next header at the same or higher level. Note any explicit phase groupings:
     - For H3 plans: `## Phase 1`, `## Phase 2` define phase boundaries.
     - For H2 plans: phases come from `# Phase 1` (H1) or any non-`Task` H2 header (e.g., `## Phase 1: Foundation`). Do NOT treat substep headers (`### 1. <step>`) inside an H2 task as task or phase boundaries — they are scoped to their parent task.
   - Read the spec document. Keep relevant sections in context for prompt construction.

3.5. **Validate document content (Ambiguity Gate):**
   After reading both documents, before assigning risk levels:

   1. **Missing Files blocks:** List every task section (header at the detected `task_header_prefix` from Step 0.5) that has no `**Files:**` block. If any found: ask the user one short question — "Tasks N, M have no Files block. Should I infer from task descriptions, or halt for you to add them?" Halt until answered.

   2. **Ambiguity scan:** Check each task description for:
      - Verbs without referents: "fix the bug", "optimize the query", "update the config" — which one?
      - Missing acceptance thresholds: "improve performance" with no metric, "reduce errors" with no target
      - Named contracts (function/type/API names) in the task that contradict the spec — same entity, different name or signature
      
      For each ambiguity found: ask one targeted question. Halt until all are resolved. Do not proceed to risk assignment until all ambiguities are cleared.

   3. **Out-of-repo paths:** Verify all paths in `**Files:**` blocks resolve within the repo root. Any path that escapes (e.g., `../../other-repo/file.py`): halt. "Task N references path outside repo root: <path>. Resolve before proceeding."

   **Why this gate exists:** Every ambiguity caught here saves one Implementer dispatch + SPEC_BLOCKER escalation + git reset cycle downstream.

3.7. **Build spec manifest (C1):**
   Call: `python3 <skill_dir>/scripts/build_spec_manifest.py <spec_path>`
   Capture stdout JSON. If parse fails: halt with `"spec_manifest build failed: <stderr>"`.

   Write to `<active>.spec_manifest`:
   ```json
   {
     "spec_path": "<spec_path>",
     "spec_total_chars": <int from stdout sum>,
     "sections": <parsed JSON>,
     "task_to_sections": {},  
     "fallback_policy": "<state.manifest_fallback arg-set; default 'full_spec_on_blocker'>"
   }
   ```

   `task_to_sections` starts empty here; it is populated at Step 6 (Compute task_to_sections — C1, added by Task 2). The Plan Reviewer (Step 6.5) validates downstream references.

4. **Assign risk levels** to each task:
   - `low` — isolated change, single file or module, no shared state, no API surface change
   - `mid` — touches 2+ modules, shared state, moderate coupling, or config changes
   - `high` — cross-cutting change, database/schema/API surface, or explicitly marked high-risk in plan

   Record: `Task 0: low | Task 1: mid | ...` in your internal notes.

   After initial assignment: if a LOW task touches any file already touched by an earlier LOW task in the same plan, upgrade the LATER task to MID. Record the upgrade reason. This prevents batch Verifier from accumulating file-level conflicts.

   If the user provided `risk=<level>` override: apply it to all tasks. However, if any task's description in the plan contains the words 'high-risk', 'schema migration', 'database', 'API surface', or 'breaking change', log a warning: 'risk override applied but task N description suggests HIGH risk — proceeding with override as instructed.' Do not silently downgrade dangerous tasks.

### Step 4.7: Local-env preflight (v2.11)

After risk assignment, before baseline test. Detection-only — never halts, never auto-copies.

1. **Unfilled local-config counterpart scan:**
   ```bash
   cd <worktree_path>
   for tmpl in $(find . -maxdepth 3 -type f \( -name '*.example' -o -name '*.template' -o -name '*.dist' \) 2>/dev/null); do
     real="${tmpl%.example}"
     real="${real%.template}"
     real="${real%.dist}"
     if [ ! -e "$real" ] && git check-ignore -q "$real" 2>/dev/null; then
       echo "MISSING_LOCAL_CONFIG: counterpart=$real template=$tmpl"
     fi
   done
   ```
   Each `MISSING_LOCAL_CONFIG:` line becomes a warning entry:
   ```json
   {"kind": "missing_local_config", "file": "<counterpart>", "template": "<template>",
    "suggestion": "Copy <template> to <counterpart> and fill in the local values",
    "detected_at": "<iso8601>"}
   ```

2. **Stale-dependency detection** — check each manifest/lockfile pair against its install marker:
   | Manifest | Lockfile | Install marker |
   |----------|----------|----------------|
   | `package.json` | `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` | `node_modules/.package-lock.json` |
   | `pyproject.toml` | `poetry.lock` / `uv.lock` | `.venv/pyvenv.cfg` or `venv/pyvenv.cfg` |
   | `Cargo.toml` | `Cargo.lock` | `target/.rustc_info.json` |
   | `build.gradle` / `build.gradle.kts` | `gradle/wrapper/gradle-wrapper.properties` | `.gradle/<version>/` or `build/` |

   For each pair: if lockfile mtime > install-marker mtime + 1s OR install-marker missing while lockfile exists → warning entry:
   ```json
   {"kind": "dependencies_likely_stale", "manifest": "<manifest>", "lockfile": "<lockfile>",
    "suggestion": "Run install before baseline (e.g., `npm install`, `poetry install`, `cargo fetch`).",
    "detected_at": "<iso8601>"}
   ```

3. **Record into state.json:**
   ```json
   "preflight_warnings": [<warning entries>]
   ```
   Always present; empty list when clean.

4. **One-line summary to user:**
   - clean → `Preflight: clean`
   - warnings → `Preflight: <N> warnings (see state.preflight_warnings)` followed by the bulleted list with `kind` + `file` + `suggestion`.

5. Never halt on preflight. ENV_BLOCKER triage (`references/escalation-playbook.md`) cross-references `state.preflight_warnings` when baseline or task tests fail — a `dependencies_likely_stale` warning matches a `module not found` symptom and short-circuits dependency-install triage.

5. **Take baseline test snapshot:**
   Before running: derive the test command from `Makefile`, `package.json`, `pyproject.toml`, or `Cargo.toml`. Record this exact command in **run-level** `state.test_command` (top-level — shared across all plans in a chain). Use this same command everywhere in the skill (Verifier prompts, Phase Transition batch Verifier). Verifiers do NOT need to re-derive the test command.

   Run the full test suite in the worktree before any changes:
   ```bash
   cd <worktree_path> && <test_command>
   ```
   Record `baseline: <N> passing, <M> failing` into **`<active>.baseline`** (resolves to `state.plan_chain[state.active_plan].baseline` for v2.13 multi-plan, top-level `state.baseline` otherwise). This is the regression reference for the CURRENT plan — multi-plan chains re-measure baseline at every Cross-Plan Trigger (Phase 2 Step -1) because each plan's starting state is the post-completion HEAD of its predecessor.

6. **Build dependency graph and identify compaction points:**
   For each task, note which prior tasks it depends on (by shared files or logical data flow). Record:
   ```
   Task 0: deps=[]
   Task 1: deps=[Task 0]
   Task 2: deps=[]          ← independent of Task 1
   Task 3: deps=[Task 1, Task 2]
   ```
   Mark **compaction points** — tasks after which no later task depends on any earlier task's raw details. At each compaction point you will: (a) run a batch Verifier for accumulated LOW tasks, (b) dispatch a Phase Docs Updater, and (c) write a state anchor and drop prior context. Explicit plan phase boundaries are always compaction points.

   - **When in doubt, be conservative:** If dependency analysis is unreliable for any segment, treat tasks as DEPENDENT and restrict compaction points to explicit plan phase boundaries. `compaction_points` must always include the index of the final task (or the final task before Phase 2). Fewer compaction points are safer than wrong ones.
   - **SKIPPED propagation:** If task X is SKIPPED, automatically mark all tasks with X in their deps as SKIPPED as well. Record each propagated SKIPPED with reason 'dependency task_X was SKIPPED'.
   - **Compute task_to_sections (C1):** For each task in the plan, populate `<active>.spec_manifest.task_to_sections[task_id]`:

     a. Parse task body for `**Spec Refs:**` block (comma-separated section IDs, e.g. `**Spec Refs:** S1.2, S3.1`). If present: use those IDs verbatim. Validate each in `spec_manifest.sections` — any unknown ID is recorded as a Plan Reviewer **BLOCKER** input (consumed at Step 6.5).

     b. Else (heuristic from **Files:** block): for each file in the task's Files block, compare path components against each `spec_manifest.sections[*].title` (case-insensitive substring match). Collect and dedupe matches across all files.

     c. If step b yields no matches: set the entry to `{"sections": ["*"], "fallback_used": true}` — the Implementer will receive the full spec for this task. Otherwise: `{"sections": [<ids>], "fallback_used": false}`.

     Write final values into `<active>.spec_manifest.task_to_sections`. Unknown-ID rows from step (a) are still written (with the unknown IDs intact) so the Plan Reviewer in Step 6.5 can see and BLOCKER them.

   - **Compute `global_constraints.shared_files`:** Build a map of file → list of task IDs that touch it (from each task's `**Files:**` block). Keep only files referenced by ≥ 2 tasks. Write this to **`<active>.global_constraints.shared_files`** in Step 7 (top-level `state.global_constraints.shared_files` for single-plan; `state.plan_chain[state.active_plan].global_constraints.shared_files` for v2.13 multi-plan; `state.plan2_state.global_constraints.shared_files` for v2.12 legacy plan2). The Implementer template's *Shared files alert* reads from the same resolved path.

   - **Compute `task_complexity` (P5 — effort scaling):** For each task, derive a complexity bucket SMALL / MEDIUM / LARGE used to scale the Implementer prompt at Phase 1 Step 1.

     Inputs per task:
     - `file_count` = number of paths in **Files:** block
     - `spec_chars` = character count of the relevant spec excerpt assigned to this task (rough LOC proxy)
     - `new_decls` = count of new functions, types, constants, or APIs the spec/task names as outputs of this task (parse for "introduce", "add function", "new type", `\bnew\b` headers, function-arrow definitions in spec code blocks)
     - `risk_mult` = 1 (LOW), 2 (MID), 3 (HIGH)

     Bucket rule (apply in order — first match wins):
     | Condition | Bucket |
     |-----------|--------|
     | `file_count == 1` AND `spec_chars < 1200` AND `new_decls <= 1` AND `risk_mult == 1` | SMALL |
     | `file_count >= 4` OR `risk_mult == 3` OR `new_decls >= 4` | LARGE |
     | (else) | MEDIUM |

     Heuristic biases upward — under-instructing is worse than mild over-engineering. Record per-task: `<active>.task_complexity.task_N = "SMALL" | "MEDIUM" | "LARGE"`.

     Effort-guidance strings (the Implementer prompt at Phase 1 Step 1 injects one of these into `{effort_guidance}`):
     - SMALL: `aim for ≤8 tool calls; TDD is still required for executable code or behavior; docs/config/generated-only tasks may mark TDD not applicable; do not add abstractions, helpers, or refactors`
     - MEDIUM: `aim for 10–25 tool calls; use TDD for executable code or behavior; refactor only what the task touches`
     - LARGE: `aim for 25–60 tool calls; use TDD for executable code or behavior; if you exceed 60 tool calls without DONE, ESCALATE with AMBIGUITY rather than continue`

   - **Compute `execution_plan` — waves + parallel groups (P2 — parallel dispatch):**

     After the dependency graph is built, compute waves greedily:
     - Wave 0 = all tasks with `deps == []`
     - Wave N = all tasks whose deps are all in waves 0..N-1
     - Tasks within a wave have no inter-dependency by construction.

     Within each wave, partition tasks into **parallel groups** by file-disjointness:
     1. Start with each task as its own singleton group.
     2. Greedily merge two groups iff the UNION of their declared `Files:` sets has no overlap AND no task in either group has a `serial: true` annotation in the plan.
     3. Tasks whose Files: blocks overlap any other in the same wave MUST stay in their own singleton group (run sequentially within the wave).

     **v2.11 — `resource_key` partition rule:**

     A task may declare `**Resource Key:** <slug>` in its task body (similar to `**Files:**`). Slug is lowercased and whitespace-stripped. Examples: `gradle-test-output`, `db-port-5432`, `playwright-browser`.

     After file-disjointness merging, before finalizing the wave's parallel groups:

     1. Build a `resource_key → [task_ids]` map for tasks in this wave.
     2. For each key with ≥ 2 task IDs in the same wave:
        - Move each affected task to its own singleton group within the wave. If a multi-task group contained two collision-tagged tasks, split into singletons.
        - Annotate each resulting singleton group in `<active>.execution_plan` with `"serialization_reason": "resource_key=<key>"`.

     The wave still respects the file-disjointness invariant (groups within a wave never share files). Splits only widen serialization — they never merge file-overlapping tasks.

     Tasks with no `Resource Key:` block are unaffected. The annotation is opt-in.

     Write to `<active>.execution_plan`:
     ```json
     [
       {"wave": 0, "parallel_groups": [["task_0", "task_2"], ["task_1"]]},
       {"wave": 1, "parallel_groups": [["task_3"], ["task_4"]]}
     ]
     ```

     Each inner list is one parallel group: a single-element list means standard sequential execution; a multi-element list triggers the Parallel Sub-Flow in Phase 1.

     **Disable parallel dispatch via** skill argument `parallel=off` — write a degenerate `execution_plan` where every task is its own singleton group preserving plan order. Use this as a fallback when sub-worktree creation is constrained (e.g., shallow clones).

6.5. **Plan Reviewer preflight (P3 — mechanical plan audit):**

   Skip this step if the user passed `preflight=off` in skill arguments (regression runs of already-validated plans).

   Build the Plan Reviewer prompt from `references/plan-reviewer-prompt.md`. Fill in:
   - `{plan_path}`, `{plan_full_text}` — the plan document
   - `{spec_manifest_json}` — the rendered JSON of `<active>.spec_manifest` (sections + task_to_sections; built in Steps 3.7 and 6) for the spec_manifest rubric items (C1)
   - `{spec_path}`, `{spec_full_text}` — the spec document
   - `{risk_levels_yaml}` — from Step 4 (YAML-formatted `task_N: <risk>`)
   - `{result_json_path}` — `<worktree_path>/.orchestrator/plan_review.json`

   **Dispatch headless** via `claude -p --dangerously-skip-permissions` (same pattern as Verifier — Phase 1 Step 3). Prompt path: `<worktree_path>/.orchestrator/plan_review_prompt.txt`. Result path: `<worktree_path>/.orchestrator/plan_review.json`. Missing/malformed result → log warning and proceed (Plan Reviewer is advisory; absence is NOT a halt).

   **Parse the result:**

   - `status: "PASS"` → record `<active>.plan_review = {status: "PASS", warnings: []}` at Step 7. Proceed.
   - `status: "ISSUES_FOUND"` →
     - Partition issues by severity: `BLOCKER` vs `WARN`.
     - All `WARN` only: record `<active>.plan_review = {status: "WARN", warnings: [...]}`. Log to user as a one-line summary. Proceed.
     - Any `BLOCKER`: ask the user ONE batched question with all blocker issues listed:
       ```
       Plan Reviewer found <N> BLOCKER issue(s) that will likely cause SPEC_BLOCKER escalations during Phase 1:
         1. [task_<id> / <category>] <description>
            evidence: <file:line>
            suggested fix: <one-sentence fix>
         ...
       Proceed anyway, halt for manual fix, or auto-apply each `suggested_fix` (max 2 retry cycles)?
       ```
       Halt until answered. If user picks auto-apply: edit plan/spec per each `suggested_fix`, re-read both documents, re-dispatch Plan Reviewer (max 2 cycles). If still ISSUES_FOUND after 2 cycles: halt with manual-fix message.

   **Why this gate exists:** every BLOCKER caught here costs ~30s + 5k tokens; each one missed costs one Implementer dispatch + SPEC_BLOCKER escalation + git reset (~2–3 min + tokens).

7. **Initialize state file:**
   ```bash
   mkdir -p <worktree_path>/.orchestrator
   ```

   **Branch on plan count (v2.13):**

   *Single-plan run* (`state.plan_chain` was NOT written by Phase -1 step b, OR this is a fresh interactive run with one plan): write state.json in v2.12 shape. The fields below populate top-level — `tasks`, `risk_levels`, `compaction_points`, etc. all live at the root of state.json. `active_plan = "plan1"` (string, v2.12 form).

   *Multi-plan run* (`state.plan_chain` IS present from Phase -1 step b, OR this is a fresh interactive run with `plan2=` or beyond): write state.json with `plan_chain[]` as the source of truth. Populate the CURRENT plan's entry (`plan_chain[state.active_plan]`) with the same fields v2.12 wrote at the top level — `tasks`, `task_summaries`, `risk_levels`, `task_complexity`, `compaction_points`, `execution_plan`, `global_constraints`, `quality_trend`, `low_tasks_pending_verification`, `last_compaction_after_task`, `plan_review`. Top-level `tasks` etc. are NOT written for multi-plan runs — code reads through `state.plan_chain[state.active_plan]`. `active_plan` is an integer index (0, 1, 2, ...).

   Write `<worktree_path>/.orchestrator/state.json` using the Write tool. Schema below shows the SINGLE-PLAN shape; multi-plan moves the per-plan fields into `plan_chain[active].*`:

   ```json
   {
     "schema_version": "2",
     "mode": "<interactive_session | headless_running>",
     "active_plan": "plan1",
     "plan": "<plan path>",
     "spec": "<spec path>",
     "branch": "<branch name>",
     "worktree": "<worktree path>",
     "test_command": "<derived in Phase 0 baseline step>",
     "baseline": {"passing": 0, "failing": 0},
     "risk_levels": {},
     "compaction_points": [],
     "execution_plan": [],
     "task_header_prefix": "### ",
     "global_constraints": {
       "shared_files": {}
     },
     "plan_review": {"status": "SKIPPED", "warnings": []},
     "implementer_model": {"used": "<sonnet | opus>", "default": "sonnet"},
     "task_complexity": {},
     "quality_trend": [],
     "tasks": {},
     "task_summaries": {},
     "spec_edits": [],
     "low_tasks_pending_verification": [],
     "last_compaction_after_task": -1,
     "last_completed_task": null,
     "last_completed_at": null,
     "current_task": 0,
     "current_step_within_task": 1,
     "current_pre_task_sha": null,
     "current_review_retries": 0,
     "current_verifier_retries": 0,
     "current_escalation_count": 0,
     "current_previous_issues": [],
     "phase_summaries": [],
     "phase_doc_commits": [],
     "chain_resume": null,
     "plan2_state": null,
     "budget_cap_usd": null,
     "budget_action": "warn",
     "cost_ledger": {
       "by_task": {},
       "by_role": {},
       "by_model": {},
       "totals": {
         "input_tokens": 0,
         "output_tokens": 0,
         "cached_read_tokens": 0,
         "cached_write_tokens": 0,
         "cost_usd": 0.0,
         "dispatches": 0
       }
     },
     "archive": null,
     "context_budget": {
       "effective_input_budget": 170000,
       "threshold_ratio": 0.60,
       "threshold_tokens": 102000,
       "last_evaluation_at": null,
       "last_evaluation_tokens": 0
     },
     "timestamps": {
       "started_at": null,
       "completed_at": null
     }
   }
   ```

   **Run-level `context_budget` (v2.15 — C3):** lives at the TOP of state.json (NOT inside any `plan_chain[i]`), like `cost_ledger`. Defaults: `effective_input_budget=170000`, `threshold_ratio=0.60`, `threshold_tokens=102000`. If the user passed `context_budget=<int>`: overwrite `effective_input_budget`. If `context_threshold=<float>`: overwrite `threshold_ratio`. After either override, recompute `threshold_tokens = round(effective_input_budget * threshold_ratio)`. The chained orchestrator preserves this block on resume.

   Fill in the actual values from steps 4–6.

   **Run-level cost/budget/archive fields (v2.14):** the four fields `cost_ledger`, `budget_cap_usd`, `budget_action`, and `archive` are **RUN-LEVEL** — they live at the top of `state.json` and span the entire orchestrator invocation, including every plan in a multi-plan chain. They are NOT per-plan and MUST NOT be duplicated inside `plan_chain[i]`. `cost_ledger.by_task` is keyed `"<plan_index_or_'top'>::<task_id>"` so a single ledger covers the chain. `budget_cap_usd` is a number (USD) or `null` (no cap). `budget_action ∈ {"pause", "warn", "off"}` controls behavior when the cap is crossed. `archive` defaults to `null` and is populated by the post-run forensics archive step (v2.14).

   **Multi-plan shape (v2.13):** when `plan_chain` exists, the equivalent state.json is:

   ```json
   {
     "schema_version": "2",
     "mode": "<...>",
     "active_plan": 0,
     "plan": "<plan_path_0 — mirrors plan_chain[0] for legacy readers>",
     "spec": "<spec_path_0 — mirror>",
     "branch": "...",
     "worktree": "...",
     "test_command": "<shared across all plans — derived once>",
     "implementer_model": {"used": "...", "default": "sonnet"},
     "plan_chain": [
       {
         "index": 0, "plan_path": "...", "spec_path": "...",
         "status": "running", "blocked_until": null,
         "baseline": {"passing": N, "failing": M},
         "tasks": {"task_0": {...}, ...},
         "task_summaries": {...},
         "risk_levels": {...},
         "task_complexity": {...},
         "compaction_points": [...],
         "execution_plan": [...],
         "global_constraints": {"shared_files": {...}},
         "quality_trend": [...],
         "low_tasks_pending_verification": [...],
         "last_compaction_after_task": -1,
         "last_completed_task": null,
         "last_completed_at": null,
         "plan_review": {"status": "PASS", "warnings": []}
       },
       {
         "index": 1, "plan_path": "...", "spec_path": "...",
         "status": "queued", "blocked_until": "plan_chain[0].all_tasks_complete_or_skipped",
         "baseline": null, "tasks": {}, "task_summaries": {}, "...": "..."
       }
     ],
     "spec_edits": [...],
     "current_task": 0,
     "current_step_within_task": 1,
     "current_pre_task_sha": null,
     "current_review_retries": 0,
     "current_verifier_retries": 0,
     "current_escalation_count": 0,
     "current_previous_issues": [],
     "phase_summaries": [],
     "phase_doc_commits": [],
     "chain_resume": null,
     "plan2_state": null,
     "budget_cap_usd": null,
     "budget_action": "warn",
     "cost_ledger": {
       "by_task": {},
       "by_role": {},
       "by_model": {},
       "totals": {
         "input_tokens": 0,
         "output_tokens": 0,
         "cached_read_tokens": 0,
         "cached_write_tokens": 0,
         "cost_usd": 0.0,
         "dispatches": 0
       }
     },
     "archive": null,
     "timestamps": {"started_at": "...", "completed_at": null}
   }
   ```

   Note: in the multi-plan shape, `budget_cap_usd`, `budget_action`, `cost_ledger`, and `archive` appear at the TOP level (siblings of `plan_chain`, NOT inside any `plan_chain[i]` entry). See the "Run-level cost/budget/archive fields (v2.14)" paragraph above — these four fields are shared across all plans in the chain and accumulate end-to-end.

   For multi-plan runs at the START of Phase 0 (active_plan == 0): populate `plan_chain[0]` with all the data Steps 3–6 produced for plan 0. Other plan_chain entries (i ≥ 1) keep their `status: "queued"` placeholders and only become populated when their swap fires at Phase 2 Step -1.

   **Mode field rule (P13a):** `mode` MUST always be a string — never `null`. Set to `"interactive_session"` when not under Phase -1 self-spawn, `"headless_running"` immediately after Phase 0 completes under `headless_pending` resume.

   **Active task tree resolution rule (v2.13):** every subsequent step in Phase 1 / Phase Transition / Phase 2 that reads or writes "the current plan's tasks/summaries/quality_trend/etc." MUST do so through this resolution:

   - `state.plan_chain` exists → active tree is `state.plan_chain[state.active_plan]`. Read `state.plan_chain[state.active_plan].tasks` (not top-level `state.tasks`). Same for task_summaries, quality_trend, risk_levels, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review.
   - `state.plan_chain` absent + `state.plan2_state` present → legacy v2.12 two-plan. Read top-level for plan 1 (`active_plan == "plan1"`), `state.plan2_state.*` for plan 2 (`active_plan == "plan2"`).
   - Neither → single-plan. Read top-level fields.

   All earlier prose in this SKILL.md that says "read `state.tasks`" or "write to top-level `quality_trend`" should be interpreted with this resolution rule applied. Where v2.12 said `active_plan == "plan2"`, multi-plan code reads "active_plan is an integer index ≥ 1" via plan_chain.

   **`implementer_model` field rule (v2.12):**

   Two cases by entry path:

   - **You are the headless child (resume from `mode=headless_pending`)**: `state.implementer_model` was already written by the interactive parent at Phase -1 step b. **Read it from state.json. Do NOT re-parse skill args** — the original args are not available to you, only the headless prompt text. Preserve the field as-is.
   - **You are an interactive run (no headless self-spawn — `mode=interactive` was passed, OR you are the parent during Phase -1 itself)**: parse the optional `implementer_model=<opus|sonnet>` skill argument. Case-insensitive. Unknown values → halt with: "Unknown implementer_model=<value>. Allowed: opus, sonnet." Set `state.implementer_model.used = <parsed value, or "sonnet" if not provided>`. Set `state.implementer_model.default = "sonnet"` literally — this records what the skill would have dispatched in the absence of an override at the time of this run. Do NOT compute `default` from the args.

   On Phase 2 Step -1 plan2 swap: do NOT reset this field. Plan 2 inherits the same Implementer model selection as Plan 1 within one orchestrator invocation.

7.5. **Learning log init-run (v2.8 — MANDATORY, v2.8.1 enforced):**

   **DO NOT SKIP THIS STEP.** This is a required Phase 0 checkpoint, equivalent in priority to git worktree creation and state.json initialization. Even on simple single-task plans, even when the plan looks trivial, even under headless `claude -p`, you MUST execute this block in the orchestrator session before any Phase 1 work begins. Skipping it disables institutional-memory observability for the entire run (no meta.json, no events.jsonl) and is the most reproducible adherence regression observed in v2.8 F001 Smoke B.

   After state.json is written, initialize the user-local learning log:

   ```bash
   # Skill dir is the directory containing this SKILL.md.
   RUN_ID="$(python3 <skill_dir>/scripts/append_learning_event.py init-run \
     --repo-root "$WORKTREE_ABS" \
     --repo-name "$(basename $(git -C "$WORKTREE_ABS" rev-parse --show-toplevel))" \
     --branch "$(git -C "$WORKTREE_ABS" branch --show-current)" \
     --plan-path "$PLAN_PATH" \
     --spec-path "$SPEC_PATH" \
     --session-id "${CLAUDE_SESSION_ID:-}" || echo "")"
   if [ -n "$RUN_ID" ]; then
     export MAE_LEARNING_RUN_ID="$RUN_ID"
     echo "LEARNING_LOG_INIT: RUN_ID=$RUN_ID"
   else
     echo "LEARNING_LOG_INIT: SKIPPED (helper missing or write failure — observability degraded for this run)"
   fi
   ```

   Note v2.8.1 changes vs v2.8.0:
   - `2>/dev/null` removed — helper script stderr now surfaces in run.jsonl. If init-run breaks, you see why.
   - Explicit `echo` on both success and failure paths — this line appears in `run.jsonl` and lets eval/audit verify adherence (the absence of either `LEARNING_LOG_INIT:` line proves the step was skipped entirely, not just that the helper failed).
   - Heading text strengthens MANDATORY framing. Under headless multi-task plans (F001 Smoke B baseline) the previous "must NOT block" language was being read as "may skip".

   `MAE_LEARNING_RUN_ID` is captured in shell env and used for the lifetime of the run. If helper init fails (script missing, write failure), `RUN_ID` is empty and no `MAE_LEARNING_RUN_ID` is exported — subsequent emit attempts (Phase 1/Transition/2) check the env var and skip silently. The plan execution proceeds normally. **Failure of init-run must NEVER block plan execution; failure to even attempt init-run IS the regression we are guarding against.**

   Sub-agents do NOT call the helper. They write event candidate JSON files to `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`. The orchestrator scans this directory after each cycle step and invokes `append` itself. See `references/learning-log.md` for the schema and 10 event types.

   **active_plan pointer (P13b + v2.13):** Single-plan or v2.12 legacy two-plan run: `"plan1"` then `"plan2"` (string). v2.13 multi-plan run: integer index `0, 1, 2, ...` into `state.plan_chain[]`. All Phase 1 / Phase Transition / Phase 2 / Monitor code MUST resolve through `<active>` per the placeholder rule. Phase 2 Step -1 swaps this pointer at every cross-plan boundary.

   **plan2_state initialization (Previous #5):** If invocation includes `plan2=<path>`, populate at Phase 0 Step 7:
   ```json
   "plan2_state": {
     "status": "queued",
     "plan_path": "<plan2 path>",
     "spec_path": "<spec2 path or same as plan2>",
     "blocked_until": "task_<final-task-id-of-plan1>=COMPLETE",
     "tasks": {},
     "task_summaries": {}
   }
   ```
   If no `plan2=`, leave as `null`.

   Each task entry written into `<active>.tasks` (resolving to top-level `tasks`, `plan2_state.tasks`, or `plan_chain[N].tasks` per the resolution table) later uses this format:
   ```json
   "task_N": {
     "status": "COMPLETE | SKIPPED | IN_PROGRESS",
     "risk": "<level>",
     "complexity": "SMALL | MEDIUM | LARGE",
     "files": [],
     "files_test": [],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "spec_clarifications": 0,
     "spec_score": null,
     "quality_score": null,
     "review_tier": null,
     "timing": {
       "started": null,
       "implementer_done": null,
       "reviewer_done": null,
       "verifier_done": null,
       "completed": null
     }
   }
   ```

   `files_test` (Previous #3): list of test-file paths the Implementer touched, separated from `files` (the broader change set). Populated from Implementer's `FILES_TEST_CHANGED:` output. Phase Transition T1 pre-filter uses this — if empty AND `files` are all `.md`, the task is treated as docs-only.

   `spec_clarifications` (P15): per-task counter for the spec-edit branch in Step 2, kept distinct from `review_retries` so spec issues don't burn the implementer-retry budget.

---

## Phase 1: Per-Task Cycle

Iterate `<active>.execution_plan` (waves outer, parallel groups inner). Within each parallel group:
- **Singleton group** (one task): run the standard sequential per-task flow described below (Steps 1–4).
- **Multi-task group** (size ≥ 2): run the **Parallel Sub-Flow** (described after the standard flow). Combined Reviewer and Verifier still run sequentially after the parallel Implementer merge.

Within a wave, parallel groups run sequentially (not in parallel with each other) — the second parallel group of the same wave starts after the first group's Reviewer + Verifier have completed. This keeps the post-merge state deterministic.

Advance only when the current task (or parallel group) reaches Agent Cleanup successfully.

**Before Step 1 of each task:**
- Run `git -C <worktree_path> rev-parse HEAD` and **record the literal SHA** (e.g., `Task 3: pre_sha=abc1234`). Use this literal string in all subsequent revert and diff commands — do not use shell variables, which do not persist between Bash calls.
- Update `current_task` in the state file.
- **Record `timing.started` (v2.16):** initialize the task's entry under `<active>.tasks.task_<N>` if not yet present (use the per-task schema from Phase 0 Step 7), and set `<active>.tasks.task_<N>.timing.started = <iso8601 now>` via atomic R-M-W of state.json. Failure to write timing.started is a non-fatal warning — log and continue; do NOT halt. Without this field the Final Summary Report's duration column cannot be computed (observed regression: jq strptime errors in all v2.11–v2.15 runs because timing.started stayed null).

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

**Result: DONE** → proceed to Step 2.  
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

Update the rolling quality-trend buffer (active-tree-aware):
- Append `quality_score` to `<active>.quality_trend` (max 10, drop oldest). This resolves to `state.plan_chain[state.active_plan].quality_trend` for v2.13 multi-plan, `state.plan2_state.quality_trend` for v2.12 legacy plan2, top-level `state.quality_trend` otherwise.
- After append, if length ≥ 5 AND mean of last 5 < mean of first 5 by > 0.10: surface at the NEXT compaction point (T3 message) — `"Quality trending down: last 5 tasks averaged X.XX vs first 5 at Y.YY. Consider manual review of recent tasks."`. Do NOT halt automatically.

Then branch on tier:

**Tier: PASS** → proceed to Step 3.

**Tier: WARN** → proceed to Step 3, but ALSO:
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
3. Orchestrator re-reads the affected spec section, makes the smallest possible edit, then re-reads the full spec.
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
  - Set `previous_issues = current_issues`.
  - Re-dispatch Implementer with `## Fix Required\n{issues with RECURRING labels}`. Return to Step 1.
- If `review_retries` > 3: halt. Report to user: "Task N exceeded review retry limit (3). Manual intervention required."

### Step 3: Verifier (MID/HIGH tasks only)

**If task risk is LOW:** skip this step. Add the task to `low_tasks_pending_verification` in the state file. Proceed to Step 4.

**If task risk is MID or HIGH:** build the Verifier prompt from the **Verifier Prompt Template** below. Fill in:
- `{MID | HIGH}` — the risk level
- `{files changed}` — from implementer output
- `{baseline}` — passing/failing counts from Phase 0
- `{test_command}` — from state.json `test_command`
- `{acceptance_criteria}` — the `## Acceptance Criteria` shell block from the task, or "none provided"
- `{result_json_path}` — `<worktree_path>/.orchestrator/verifier_results/task_<N>.json`

**Dispatch as a headless `claude -p` subprocess (not Agent tool):**
1. Write the prompt to `<worktree_path>/.orchestrator/verifier_prompts/task_<N>.txt` using the Write tool.
2. Create the results directory:
   ```bash
   mkdir -p <worktree_path>/.orchestrator/verifier_results
   ```
3. Run the Verifier:
   ```bash
   claude -p --dangerously-skip-permissions "$(cat <worktree_path>/.orchestrator/verifier_prompts/task_<N>.txt)" \
     > <worktree_path>/.orchestrator/verifier_results/task_<N>.stdout 2>&1
   ```
4. Read the result file: `<worktree_path>/.orchestrator/verifier_results/task_<N>.json`
   - If the file exists and is valid JSON: parse `status` field for PASS/FAIL/ESCALATE.
   - If the file is missing or malformed: treat as ESCALATE with `type: ENV_BLOCKER, blocker: "Verifier subprocess produced no result file — check task_<N>.stdout for diagnostics"`.

**Result: PASS** → proceed to Step 4.  
**Result: FAIL** →
- Increment `verifier_retries`.
- If `verifier_retries` ≤ 3:
  - Reset to pre-task state: `git -C <worktree_path> reset --hard <pre_task_sha>`
  - Re-dispatch Implementer with verifier's `issues` from the JSON under `## Fix Required`. Include `receiving-code-review` (per Phase 1 Step 1 re-dispatch rules) — verifier feedback can be wrong (baseline drift, flaky tests), so the skill's "verify before patching" discipline applies. Return to Step 1.
- If `verifier_retries` > 3: halt. Report to user: "Task N exceeded verifier retry limit (3). Manual intervention required."

**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 3.5: Learning-log candidate scan (v2.8)

Once per task cycle, after Step 3 completes (or after Step 2 for LOW tasks
that skip Verifier), check the candidate directory for any event files
written by Implementer / Reviewer / Verifier during this cycle and forward
them in a single batch:

```bash
CANDIDATE_DIR="<worktree_path>/.orchestrator/learning_events"
if [ -n "${MAE_LEARNING_RUN_ID:-}" ] && [ -d "$CANDIDATE_DIR" ]; then
  for cand in "$CANDIDATE_DIR"/task_<N>-*.json; do
    [ -f "$cand" ] || continue
    python3 <skill_dir>/scripts/append_learning_event.py append \
      --run-id "$MAE_LEARNING_RUN_ID" \
      --event-json "$cand" \
      --repo-root "$WORKTREE_ABS" >/dev/null 2>&1 || true
    mv "$cand" "$cand.appended"  # mark consumed; avoid double-emit
  done
fi
```

Append failures are silent (`|| true`) — observability must not block execution. Candidate files are renamed `.appended` after consumption to prevent duplicate emission on the next cycle step. Sub-agents writing fresh candidates always overwrite (per-task-per-role one file at a time).

### Step 4: Agent Cleanup

You (Orchestrator) perform these checks directly — no sub-agent needed:

1. **Debug artifact scan — REMOVED in v2.5.0.** This check is now runtime-enforced by the `PostToolUse(Edit|Write)` hook at `<worktree>/.orchestrator/hooks/scan-debug-artifacts.sh` (materialized at Phase 0 Step 2.5). If an Implementer attempted to write `console.log|debugger|TODO|FIXME` outside of allow-listed contexts, the hook already exit-2'd and the Implementer auto-retried before reaching this step. No orchestrator-side grep needed.

   If you suspect the hook was misfired or disabled (e.g., user manually edited settings.json mid-run): re-enable and continue. Do not re-introduce the manual grep — it duplicates the hook and was the silent-bypass risk that motivated P1.

1.5. **Accumulate cost (F2 — v2.16 helper-script enforced):**

   **MANDATORY for every sub-agent dispatch.** Pre-v2.16 runs left `cost_ledger.totals.dispatches=0` across every observed run because this step was prose-only and got silently skipped. Always call `scripts/accumulate_cost.py` — it does the price lookup, R-M-W of state.json under flock, and aggregation for you. The orchestrator's job is reduced to (a) extracting `usage` from the just-completed dispatch, (b) calling the helper.

   **Extract `usage`:**

   - *Agent tool dispatch* (Implementer / Combined Reviewer): the Agent tool result returned to this turn includes a `usage` object with `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`. Normalize to the helper's field names: `cached_read_tokens` ← `cache_read_input_tokens`, `cached_write_tokens` ← `cache_creation_input_tokens`. If the Agent result has no `usage` block (transport error, schema drift): use `{"input_tokens": 0, "output_tokens": 0}` and pass `--model unknown` so cost is recorded as 0 without misattributing tokens. Do NOT skip the helper call — the dispatch count is itself signal.
   - *Headless `claude -p --output-format stream-json` subprocess* (Verifier / Plan Reviewer / Docs Updater): tail the result file `<worktree>/.orchestrator/{verifier,docs,plan_review}_results/...` OR the matching `.stdout`. The final line of stream-json is `{"type":"result","usage":{...},...}`. Extract `usage`, normalize the same way.

   **Invoke the helper:**

   ```bash
   python3 <skill_dir>/scripts/accumulate_cost.py \
     --state "<worktree_path>/.orchestrator/state.json" \
     --task-id "task_<N>" \
     --role "implementer|reviewer|verifier|plan_reviewer|docs_updater" \
     --model "<state.implementer_model.used for implementer; 'sonnet' for reviewer/verifier/docs/plan_reviewer; 'unknown' if missing>" \
     --usage-json '<JSON string of normalized usage>' \
     >/dev/null 2>&1 || echo "COST_ACCUMULATE: failed (non-fatal; ledger may under-count this dispatch)"
   ```

   The helper's exit code is intentionally NOT enforced (`|| echo`) — accumulation failure is observability degradation, not a correctness issue. The next compaction-point budget check (Phase Transition T3 step 4) reads whatever is in the ledger.

   **by_task key shape:** `<active_plan>::<task_id>::<role>` so implementer + reviewer + verifier each persist under the same task without overwriting each other. Same-role retries overwrite (latest dispatch wins); by_role / by_model / totals always increment so cumulative spend stays correct across retries.

   **Failure modes:**
   - Missing `usage` block → call helper with `{"input_tokens":0,"output_tokens":0}` and `--model unknown`. Cost recorded as 0, dispatch count still increments.
   - `state.json` write failure inside helper → helper exits 1; orchestrator logs and continues (no halt — this is the F2 budget guardrail's downside vs. the state-file write guardrail; budget tracking is best-effort by design).
   - `price_table` import failure → helper exits 1 at startup; same handling.

   **Budget evaluation** (Phase Transition T3 step 4 and Phase 2 Step 0) is unchanged — it reads `state.cost_ledger.totals.cost_usd` and compares to `state.budget_cap_usd`. The fix here only ensures the ledger is actually populated so the comparison is meaningful.

2. **Update state file** — write this task's result into the active task tree.

   **Active tree selection (v2.13):** write under **`<active>.tasks.task_N`** (resolves per the table at the top of the document: `state.plan_chain[state.active_plan].tasks.task_N` for multi-plan, `state.plan2_state.tasks.task_N` for v2.12 legacy plan2, `state.tasks.task_N` otherwise). Same rule for `task_summaries`. Note `state.active_plan` is an **integer** (0, 1, 2, ...) when `plan_chain` is in use — do NOT string-compare `== "plan2"` for multi-plan runs.

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

   `files_test` comes from the Implementer's `FILES_TEST_CHANGED:` output (empty list if none). `complexity` comes from `<active>.task_complexity.task_N` (set in Phase 0 Step 6 per P5). `spec_score` / `quality_score` / `review_tier` come from Phase 1 Step 2 score parsing — PASS or WARN reached this point; FAIL would have looped back to Step 1.

   **Also update top-level latest pointers (P14)** — required for Monitor and any consumer that needs "most recent task":
   ```json
   "last_completed_task": "task_N",
   "last_completed_at":   "<iso8601>"
   ```
   Do NOT rely on JSON insertion order — this skill re-writes state.json many times and key order is unreliable (observed bug: a later spec-edit re-touch of an earlier task moved it to the end of insertion order, breaking `to_entries | last`).

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

2.5. **Commit orchestrator state separately:**
   ```bash
   git -C <worktree_path> add .orchestrator/
   git -C <worktree_path> diff --cached --quiet || \
     git -C <worktree_path> commit -m "chore(<plan-slug>): task <N> orchestrator state"
   ```
   This keeps implementation commits (`feat:`) separate from orchestrator state commits (`chore:`). Reviewers can filter `git log --grep '^feat'` to see only code changes.

3. **Check for compaction point:** if this task is a compaction point, go to **Phase Transition** before advancing. Otherwise, advance to the next task.

### Parallel Sub-Flow (P2 — multi-task parallel group)

Triggered when the current parallel group from `<active>.execution_plan` has size ≥ 2.

**Pre-flight invariant:** all tasks in the group have disjoint `Files:` sets (Phase 0 Step 6 partition guarantees this). If you observe the group has size ≥ 2 but the tasks share any file: halt — `execution_plan` is corrupt; do not proceed.

**Step P.0: Record pre-group SHA**

```bash
git -C <worktree_path> rev-parse HEAD
```
Record as `current_pre_group_sha` in state.json. Every task in the group will branch off this SHA.

**Step P.1: Create sub-worktrees + replicate safety hooks**

For each task `task_<N>` in the group:
```bash
mkdir -p <worktree_path>/.parallel
git -C <worktree_path> worktree add \
  <worktree_path>/.parallel/task_<N> \
  HEAD
# Replicate safety + gate hooks into the sub-worktree
mkdir -p <worktree_path>/.parallel/task_<N>/.claude
mkdir -p <worktree_path>/.parallel/task_<N>/.orchestrator/hooks
cp <worktree_path>/.claude/settings.json \
   <worktree_path>/.parallel/task_<N>/.claude/settings.json
cp <worktree_path>/.orchestrator/hooks/*.sh \
   <worktree_path>/.parallel/task_<N>/.orchestrator/hooks/
```
Rewrite the absolute `<worktree_path>` in the copied `settings.json` to point at the sub-worktree path (sed/Edit). Otherwise hooks reference the parent and silently no-op.

**Step P.2: Dispatch all Implementers in one Orchestrator message**

In a single assistant message, emit N `Agent` tool calls — one per task in the group. Each Agent dispatch:
- Uses the same Implementer Prompt Template, with `{implementer_model}` filled from `state.implementer_model.used` (same value for all parallel siblings — the field is run-level, not task-level).
- **Sets the Agent tool `model` parameter to `state.implementer_model.used`** under the same rule as the sequential Step 1 dispatch — `sonnet` may omit the parameter, `opus` MUST set it explicitly. Forgetting this here silently downgrades every parallel-dispatched task to Sonnet regardless of the run's selection (v2.12 regression risk).
- Has `{worktree_path}` set to the **sub-worktree** path (`<worktree_path>/.parallel/task_<N>`), NOT the parent worktree
- Has `{deps_for_this_task}` set to the dependency list (which by definition only includes earlier-WAVE tasks, all already merged into the parent before P.0)

Collect all N tool results.

**Step P.3: Aggregate results**

For each sub-worktree task:
- `STATUS: DONE` → record the sub-worktree commit SHA from the `COMMIT:` line; record `FILES_CHANGED:` for merge verification.
- `STATUS: ESCALATE` → defer the escalation; continue collecting other results. The escalations are handled sequentially in P.5.

If at least one ESCALATE: do NOT merge any sub-worktree until all escalations are resolved (P.5). Keep all sub-worktrees intact.

**Step P.4: Out-of-scope file check (guardrail)**

For each DONE sub-worktree:
- Read its `FILES_CHANGED:`. Confirm every file is within the task's declared `Files:` block.
- Confirm that across ALL DONE sub-worktrees in this group, the union of `FILES_CHANGED` has no duplicates.

If any out-of-scope edit OR duplicate file: halt the entire group. Remove all sub-worktrees with `git worktree remove --force`. Re-dispatch the offending task sequentially in the main worktree under standard flow with `## Fix Required\n<out-of-scope file list>`.

**Step P.5: Resolve ESCALATEs serially**

For each ESCALATE from P.3: handle via the standard Escalation Protocol. The escalation may resolve via spec edit (continue to P.6), AMBIGUITY edit, or hit the escalation cap (skip that task; remove its sub-worktree).

**Step P.6: Cherry-pick onto parent worktree**

In task-ID order (numeric ascending), for each successful sub-worktree:
```bash
git -C <worktree_path> cherry-pick <sub_worktree_commit_sha>
```

If a cherry-pick fails (should be impossible given the disjoint-files guarantee, but defensively):
- `git -C <worktree_path> cherry-pick --abort`
- Halt the group. Report the conflict path to the user; do NOT proceed to Reviewer/Verifier.

After all cherry-picks succeed:
```bash
git -C <worktree_path> worktree remove --force <worktree_path>/.parallel/task_<N>  # for each N
rm -rf <worktree_path>/.parallel
```

**Step P.7: Per-task Reviewer + Verifier (serial)**

For each task in the group, in task-ID order, run Steps 2 (Combined Reviewer) and 3 (Verifier) from the standard flow. The diff is computed from `current_pre_group_sha` to the post-cherry-pick HEAD scoped to this task's `FILES_CHANGED`.

If a Reviewer FAIL or Verifier FAIL occurs for any task: reset the offending task ONLY by reverting its specific cherry-picked commit (`git revert <commit_sha>` — single-commit revert) and re-dispatch sequentially in the main worktree under the standard flow. Other tasks' commits stay in place.

**Step P.8: Agent Cleanup per task**

Run Step 4 (Agent Cleanup) for each task in the group, writing per-task state entries normally. The first task in the group writes the compaction-point check; subsequent tasks bypass it (the boundary is the LAST task of the group).

**Failure isolation guarantee (P2):** if any single sub-worktree dies (Implementer ESCALATE or out-of-scope edit), only that task is rolled back. The other parallel commits stay. This is the core wall-time win — independent failures don't restart the whole wave.

---

## Phase Transition

Execute at each compaction point, after Agent Cleanup of the boundary task and before starting the next task.

### Step T1: Batch Verifier for LOW Tasks

If `low_tasks_pending_verification` is non-empty: build the Verifier prompt from the **Verifier Prompt Template** with:
- Risk level: `LOW (BATCH)`
- Files changed: all files from all accumulated LOW tasks since the last compaction point
- Baseline: from Phase 0
- `{test_command}`: from state.json
- `{acceptance_criteria}`: "run all test files for changed files combined"
- `{result_json_path}`: `<worktree_path>/.orchestrator/verifier_results/batch_<compaction_index>.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/verifier_prompts/batch_<compaction_index>.txt` and result path `<worktree_path>/.orchestrator/verifier_results/batch_<compaction_index>.json`. Missing/malformed result → ENV_BLOCKER ESCALATE.

**Result: PASS** → clear `low_tasks_pending_verification` in the state file.  
**Result: FAIL** → apply this recovery algorithm:
0. **Pre-filter** (docs-only exclusion): For each task in `<active>.low_tasks_pending_verification`, read its entry under `<active>.tasks.task_N`. The task is docs-only if **either**:
   - `files_test` is present and equals `[]`, **or**
   - `files_test` is missing/null AND every entry in `files` ends with `.md` (heuristic fallback for legacy state.json).

   Docs-only tasks: exclude from batch test mapping. Run `markdownlint` (if available) on the changed `.md` files; if markdownlint is unavailable, run a syntax sanity check via `git diff --check` on the same files. Failures here count toward the task's `verifier_retries`.

   Tasks with test files proceed to the standard test-mapping algorithm below.
1. From the batch FAIL output, identify which test files failed.
2. Map each failing test file to the LOW task that last modified it (use `git log --oneline <worktree>` and task commit messages which include `Files:` lines).
3. If two LOW tasks both modified the same file and that file's tests fail: treat the LATER task as the likely cause — reset only that task to its `pre_task_sha`, re-implement it, then re-run the full batch.
4. If a single task is clearly responsible: reset that task's `pre_task_sha`, re-implement, re-run batch.
5. If responsibility is ambiguous after mapping: reset ALL tasks in this batch to the first batch task's `pre_task_sha`, then re-run them sequentially with per-task Verifier (treat as MID for this retry).
6. Apply `verifier_retries` counter per affected task. If any task hits limit: halt.

### Step T2: Phase Docs Updater

Build the Phase Docs Updater prompt from the **Phase Docs Updater Prompt Template** with:
- Files changed in this phase: all files from state file tasks since `last_compaction_after_task`
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: `<worktree_path>/.orchestrator/docs_results/phase_<compaction_index>.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/docs_prompts/phase_<compaction_index>.txt` and result path `<worktree_path>/.orchestrator/docs_results/phase_<compaction_index>.json`. Missing/malformed result → treat as ESCALATE; record `phase_docs_skipped` in state.json. The Final Docs Updater in Phase 2 will recover.

### Step T3: State Anchor + Context Drop

1. Flush all pending state to the state file:
   - Set `last_compaction_after_task = current_task`
   - Update `low_tasks_pending_verification = []`
   - Write the file and verify it is readable.

1.5. **Project decisions to DECISIONS.md (C2):** render `<worktree>/.orchestrator/DECISIONS.md` from `<active>.decisions_register`. Format: a markdown table with columns `[Task, Decision, Files, Made at, Supersedes]`. Sort by `made_at` ascending. Group superseded entries (`supersedes != null`) at the bottom in a separate subsection. Use an atomic write: write to `DECISIONS.md.tmp`, then `mv` over `DECISIONS.md`. The file is included in the archive tarball (F1). Empty register → write a stub file with header `# Decisions register (empty)`. Failure → log warning, continue (best-effort like the register itself).

2. **Actively drop prior task context:** from this point forward, do not reference individual task details from before this compaction point. Work only from your structured task summary (what you have in internal notes from Agent Cleanup steps). If you need details from an earlier task, re-read the state file — do not hold raw sub-agent output in active context.

3. **Emit `context_health` passive snapshot (v2.10):** if `MAE_LEARNING_RUN_ID` is set, write a candidate JSON to `<worktree>/.orchestrator/learning_events/transition_<compaction_index>-orchestrator.json` and `append` it. The event is informational — never alters control flow. Fields per `references/learning-log.md` "`context_health` (v2.10) — passive observation contract". Minimum body:
   ```json
   {
     "schema_version": "1",
     "phase": "phase_transition",
     "risk_tier": null,
     "event_type": "context_health",
     "severity": "low",
     "execution": {"task_id": "transition_<compaction_index>", "issue_key": "context_health_snapshot"},
     "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
     "summary": "Phase Transition T3 passive context-health snapshot.",
     "context": {
       "user_intent": "Observe context-management state across compactions.",
       "agent_expectation": "Counters captured at compaction boundary.",
       "actual_outcome": "Snapshot recorded.",
       "root_cause": "Routine emit point — not a failure.",
       "evidence": [{"kind": "issue_key", "value": "context_health_snapshot"}],
       "compaction_index": <index>,
       "completed_tasks_count": <count>,
       "resume_chain_handoffs": <handoffs>
     },
     "improvement": {
       "target": "references/learning-log.md",
       "proposal": "Aggregate context_health events to derive empirical thresholds.",
       "experiment_link": null
     },
     "privacy": {"redacted": true, "notes": "Counters only — no path/content."}
   }
   ```
   Append failure is silent (`|| true`) per the learning-log failure policy. **Do not use these counters to alter orchestrator behavior** — Goodhart's-law guard. Behavior changes require a follow-on experiment.

3.5. **Emit `chain_trigger_eval` (C3 — v2.15):** compute the trigger result via the should_chain logic (Resume Chain "Trigger (v2.15 — token-aware)" section). Update `state.context_budget.last_evaluation_tokens = session_input_tokens` and `state.context_budget.last_evaluation_at = <iso8601 now>`. Then write a candidate event to `<worktree>/.orchestrator/learning_events/trigger_<compaction_index>-orchestrator.json`:

   ```json
   {
     "schema_version": "1",
     "phase": "phase_transition",
     "event_type": "context_health",
     "severity": "low",
     "execution": {"task_id": "transition_<compaction_index>", "issue_key": "chain_trigger_eval"},
     "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
     "summary": "Chain trigger eval: <chained|not_chained> | tokens=<N>/<threshold> | compactions=<N>/2 | completed=<N>/8",
     "context": {
       "trigger_decision": "chained" | "not_chained",
       "trigger_reason": "token_threshold" | "legacy_floor" | "none",
       "session_input_tokens": <int>,
       "threshold_tokens": <int>,
       "compactions_reached": <int>,
       "completed_count": <int>
     },
     "privacy": {"redacted": true, "notes": "Counters only — no path/content."}
   }
   ```

   Append silently (`|| true`). One event PER Phase Transition T3 regardless of decision — enables post-hoc A/B analysis of token-vs-legacy trigger lift. If `trigger_decision == "chained"`: proceed with the existing Resume Chain procedure (Phase 0 Step 0 Resume Chain section). If `not_chained`: continue execution.

4. **Evaluate budget (F2):** governed by spec §F2.4. Placement is **after** the state-anchor write (step 1) **and after** the `context_health` snapshot (step 3) — the spec timing supersedes the plan's "step 2.5" label.

   ```
   If state.budget_action == "off" OR state.budget_cap_usd is None: skip.
   Else if state.cost_ledger.totals.cost_usd >= state.budget_cap_usd:
     If state.budget_action == "warn":
       Emit a context_health learning event with severity=high, issue_key=budget_warning,
       summary="Budget warning: ${totals} of ${cap} cap consumed."
       Continue execution.
     If state.budget_action == "pause":
       Call close-run --outcome=blocked.
       Write HEADLESS_HALTED.txt with first line "reason: budget_exceeded".
       Exit orchestrator (headless child) or halt (interactive).
   ```

   The `warn` event is written as a candidate JSON under `<worktree>/.orchestrator/learning_events/transition_<compaction_index>-budget.json` and appended via `scripts/append_learning_event.py append` — same pattern as the `context_health` snapshot in step 3, but with `severity: "high"` and `execution.issue_key: "budget_warning"`. Append failure is silent.

   The `pause` branch invokes the same close-run helper used by the exhausted-escalation halt:
   ```bash
   if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
     python3 <skill_dir>/scripts/append_learning_event.py close-run \
       --run-id "$MAE_LEARNING_RUN_ID" --outcome blocked >/dev/null 2>&1 || true
   fi
   # Archive run (F1): best-effort archive before HEADLESS_HALTED marker.
   if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
     <skill_dir>/scripts/archive_run.sh \
       --worktree <worktree_path> \
       --run-id "$MAE_LEARNING_RUN_ID" \
       --outcome blocked 2>&1 || echo "ARCHIVE: failed (see archive output above) — worktree retained"
   fi
   printf 'reason: budget_exceeded\n' > <worktree_path>/.orchestrator/HEADLESS_HALTED.txt
   ```
   Then exit (headless child) or halt (interactive). The Monitor watcher will surface the HALTED line on its next loop.

**Phase Transition failure handling:**
- If T1 batch Verifier FAIL exceeds retries for any task: halt that task, record SKIPPED in state.json, continue Phase Transition.
- If T2 Phase Docs Updater sends ESCALATE: skip docs for this phase. Record `phase_docs_skipped: [<phase_id>]` in state.json. The Final Docs Updater in Phase 2 will recover.
- If T3 state file write fails (Write tool error or Read-back fails): close the learning log with `outcome=blocked` (best-effort, silent on failure) and then **hard halt immediately** — 'State file write failed at <path>. Risk of state corruption. Manual inspection required.' Do not proceed.
  ```bash
  if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
    python3 <skill_dir>/scripts/append_learning_event.py close-run \
      --run-id "$MAE_LEARNING_RUN_ID" --outcome blocked >/dev/null 2>&1 || true
  fi
  ```

---

## Escalation Protocol

### When a sub-agent sends ESCALATE

```
ESCALATE
type: SPEC_BLOCKER | ENV_BLOCKER | AMBIGUITY
task: <task id>
blocker: <one-sentence description>
attempted: <what was tried>
cause: <suspected root cause>
options:
  A: <option>
  B: <option>
  C: <option>
```

### Your response

1. Increment the current task's `escalation_count`. If that task's `escalation_count` > 3: halt **that task only** (not the entire run):
   ```
   HALTED: Task <N> exceeded maximum escalations (3).
   Last escalation: <blocker text>
   Branch: <branch name>
   State file: <worktree_path>/.orchestrator/state.json
   Manual intervention required for Task <N>.
   ```
   Record the task as SKIPPED in state.json with the escalation reason. The orchestrator continues with subsequent tasks (subject to SKIPPED propagation rules from Phase 0 Step 6).

   **Learning-log (v2.8):** if this exhausted-escalation halt aborts the entire run (whole-orchestrator halt, not just task skip), call `close-run --outcome=aborted` before exiting:
   ```bash
   if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
     python3 <skill_dir>/scripts/append_learning_event.py close-run \
       --run-id "$MAE_LEARNING_RUN_ID" --outcome aborted >/dev/null 2>&1 || true
   fi
   ```

   **Archive run (F1):** after close-run, call archive_run.sh with `--outcome aborted`. Best-effort — failure is silent (the run has already been closed):
   ```bash
   if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
     <skill_dir>/scripts/archive_run.sh \
       --worktree <worktree_path> \
       --run-id "$MAE_LEARNING_RUN_ID" \
       --outcome aborted 2>&1 || echo "ARCHIVE: failed (see archive output above) — worktree retained"
   fi
   ```
   For the more common case (task-only halt that lets the orchestrator continue), do NOT close-run — the run is still alive. Phase 2 Step 2 closes it with `outcome=success` if subsequent tasks finish, or the final hard-halt block does so with `outcome=blocked` if the orchestrator gives up entirely.

2. Reset to pre-task state using the literal SHA from your notes:
   ```bash
   git -C <worktree_path> reset --hard <pre_task_sha>
   ```

3. Act based on type:

| Type | Your action |
|------|-------------|
| `SPEC_BLOCKER` | Make the smallest possible edit to the spec that resolves the contradiction. Re-read the spec. Re-dispatch Implementer from clean state. |
| `ENV_BLOCKER` | Run the **ENV_BLOCKER Triage Playbook** below before escalating to the user. |
| `AMBIGUITY` | Edit the plan with an explicit decision that resolves the ambiguity. Re-read the plan. Re-dispatch Implementer from clean state. |

4. After resolving: return to Step 1 and re-run all steps in sequence. Do NOT skip Combined Review or Verification.

### ENV_BLOCKER Triage Playbook

See `references/escalation-playbook.md` (the ENV_BLOCKER Triage section). Read it at the moment an `ENV_BLOCKER` arrives. The same file also contains the canonical orchestrator response procedure and the document-update rules referenced above.

**Rule (kept here for prominence):** You (Orchestrator) update all documents yourself. Never delegate spec or plan updates to a sub-agent. After updating any document, re-read it fully before building the next sub-agent prompt.

---

## Phase 2: Final Phase

After all tasks are processed (COMPLETE or SKIPPED):

### Step -1: Cross-Plan Trigger (multi-plan only)

Two code paths share this section by schema detection:

- **v2.13 multi-plan** (`state.plan_chain` exists, length ≥ 2): generalize swap to "advance `active_plan` from index i to i+1". See "v2.13 path" below.
- **v2.12 two-plan legacy** (`state.plan_chain` absent + `state.plan2_state` non-null): use the original plan2-only swap. See "v2.12 legacy path" below.

If neither precondition is met: this step is a no-op — proceed to Step 0.

#### v2.13 path — generalized chain advance

If `state.plan_chain` exists and there is some i where `state.active_plan == i` and `state.plan_chain[i+1]` exists with `status: "queued"`:

1. **Verify LOW batch sweep for current plan PASSED.** Read the active tree (`state.plan_chain[i]`). Check `low_tasks_pending_verification == []` AND that any `<worktree>/.orchestrator/verifier_results/batch_final_p<i>.json` (per-plan suffix; see below) has no `status: FAIL`.

2. **Verify all tasks in `plan_chain[i]` are COMPLETE or SKIPPED.** The `blocked_until` for index i+1 is `"plan_chain[<i>].all_tasks_complete_or_skipped"` — resolve by scanning `plan_chain[i].tasks` for any task whose `status` is neither COMPLETE nor SKIPPED. If any remain: skip Step -1, proceed to Step 1 (Final Docs Updater handles whatever did finish).

3. **Swap pointer:** `state.active_plan = i + 1`. Update `state.plan = plan_chain[i+1].plan_path`, `state.spec = plan_chain[i+1].spec_path`. Update `state.mode = "plan_chain_running"`.

4. **Reset transient counters:** `current_task = 0`, `current_step_within_task = 1`, `current_pre_task_sha = null`, `current_review_retries = 0`, `current_verifier_retries = 0`, `current_escalation_count = 0`, `current_previous_issues = []`. These are run-level, not plan-level — same fields v2.12 used.

5. **Re-run Phase 0 Steps 3, 3.5, 4, 6 against Plan i+1.** Write the results (Plan i+1's `risk_levels`, `task_complexity`, `compaction_points`, `execution_plan`, `global_constraints.shared_files`) INTO `plan_chain[i+1]` — NOT top-level. The plan_chain entry for index i+1 keeps `plan_chain[i]`'s contents intact for archival.

6. **Re-take baseline.** Plan i's changes are now in HEAD. Run Phase 0 Step 5 fresh — `test_command` unchanged but counts re-measured. Write to `plan_chain[i+1].baseline`.

7. Set `plan_chain[i+1].status = "running"`. (Keep `plan_chain[i].status = "complete"` after step 2 succeeds; mark `"failed"` if step 1 found unresolved batch failures and recovery doesn't apply.)

8. Begin Phase 1 Task 0 of plan i+1.

After Plan N-1 (final plan in chain) completes Step 0 (LOW batch sweep), this Cross-Plan Trigger is skipped (no `plan_chain[N]` exists) and execution falls through to Step 1 (Final Docs Updater for the whole chain).

**Per-plan result file paths (v2.13):** Verifier and Docs Updater output files under `<worktree>/.orchestrator/` need a per-plan suffix to avoid collision when one chain has multiple plans. Use `_p<index>` suffix:
- Phase Transition T1 batch: `verifier_results/batch_p<i>_<compaction_index>.json`
- Phase 2 Step 0 final LOW sweep: `verifier_results/batch_final_p<i>.json`
- Phase Transition T2 phase docs: `docs_results/phase_p<i>_<compaction_index>.json`
- Phase 2 Step 1 final docs: `docs_results/final_p<i>.json` PER PLAN, OR `docs_results/final_chain.json` for the cross-plan summary
- For v2.12 single-plan and legacy two-plan runs: keep existing un-suffixed paths.

#### v2.12 legacy path — plan2_state two-plan

(Retained verbatim from v2.12 for legacy state.json compatibility.)

Precondition: `state.plan2_state` is a non-null object initialized at Phase 0 Step 7 with `status: "queued"`. If `plan2_state` is null AND `plan_chain` is absent, this whole step is skipped — proceed to Step 0.

If `plan2_state.status == "queued"`:

1. Verify Plan 1 Phase 2 Step 0 (LOW batch sweep) PASSED — check `state.low_tasks_pending_verification == []` AND no batch verifier result file in `<worktree>/.orchestrator/verifier_results/batch_final.json` has `status: FAIL`.
2. Verify `plan2_state.blocked_until` condition is satisfied. The condition string takes the form `task_<id>=COMPLETE`; resolve by looking up `state.tasks[<id>].status`. If not COMPLETE: skip Step -1, proceed to Step 1 (Plan 1 Final Docs Updater only).
3. If both pass, initialize Plan 2 orchestration:
   - Swap the active-plan pointer: set `state.active_plan = "plan2"`. All Phase 1 / Phase Transition / Phase 2 logic from this point reads/writes through `state.plan2_state.tasks` and `state.plan2_state.task_summaries` — NOT top-level `state.tasks`. Plan 1 results remain intact under `state.tasks` (no archival move; the pointer is authoritative).
   - Update `state.mode = "plan2_running"`. Update `state.plan = plan2_state.plan_path`, `state.spec = plan2_state.spec_path` for documentation; Phase 1 reads these.
   - Reset transient counters: `current_task = 0` (matches Phase 0 indexing), `current_step_within_task = 1`, `current_pre_task_sha = null`, `current_review_retries = 0`, `current_verifier_retries = 0`, `current_escalation_count = 0`, `current_previous_issues = []`, `low_tasks_pending_verification = []`, `last_compaction_after_task = -1`, `last_completed_task = null`, `last_completed_at = null`.
   - Re-run Phase 0 Steps 3, 3.5, 4, 6 against Plan 2 (read Plan 2 docs, ambiguity gate, risk assignment, dependency graph + `shared_files` for Plan 2). Write Plan 2's `risk_levels`, `compaction_points`, `global_constraints.shared_files` into `state.plan2_state` (NOT top-level — those belong to Plan 1).
   - **Re-take baseline (P13b correction):** do NOT reuse Plan 1's baseline. Plan 1's changes are now in HEAD; that's Plan 2's starting state. Run Phase 0 Step 5 fresh — the `test_command` is unchanged but the passing/failing counts MUST be re-measured. Write to `state.plan2_state.baseline`.
   - Set `state.plan2_state.status = "running"`.
   - Begin Phase 1 Task 0 of Plan 2 (under the active-plan pointer).

### Step 0: LOW Batch Verifier Sweep

**Phase 2 Step 0 — Budget evaluation (F2):** before dispatching the LOW batch verifier, run the same evaluation as Phase Transition T3 step 4 — this is the last chance to halt before incurring more cost. If `budget_action=pause` AND `state.cost_ledger.totals.cost_usd >= state.budget_cap_usd`: call `close-run --outcome=blocked`, write `<worktree_path>/.orchestrator/HEADLESS_HALTED.txt` with first line `reason: budget_exceeded`, and exit. If `budget_action=warn` AND the same threshold is crossed: emit ONE `context_health` learning event (severity=high, issue_key=budget_warning, summary referencing totals/cap) under `<worktree>/.orchestrator/learning_events/phase2_step0-budget.json` and continue. If `budget_action=off` OR `budget_cap_usd is None`: skip the check. The cap is compared against the run-level totals, so chained plans share one budget.

Read the active tree's `low_tasks_pending_verification` (resolution rule from Phase 0 Step 7: `state.plan_chain[state.active_plan].low_tasks_pending_verification` for v2.13 multi-plan; `state.plan2_state.low_tasks_pending_verification` for v2.12 legacy plan2; top-level for single-plan). If non-empty: dispatch headless batch Verifier (same pattern as Phase Transition T1).

**Result path:** when `state.plan_chain` is in use, use `batch_final_p<active>.json` (consistent with Phase 2 Step -1 check). For single-plan or v2.12 legacy two-plan: `batch_final.json` un-suffixed.

On PASS: clear the active tree's list. On FAIL: apply standard `verifier_retries` per affected task. Only after PASS proceed to Step -1 (Cross-Plan Trigger checks whether to advance to the next plan) or to Step 1 (Final Docs Updater) if no next plan.

This guarantees LOW task verification even when `compaction_points=[]` (short plans with no compaction points).

### Step 1: Final Docs Updater

**Scope rule (v2.13):**

- *Single-plan run* (no `plan_chain`): unchanged from v2.12 — one Final Docs Updater dispatch covering all tasks. Result path: `docs_results/final.json`.
- *Multi-plan run* (`plan_chain` present): TWO-tier behavior. Per-plan Phase Docs Updater already ran at each plan's compaction points (Phase Transition T2 with `_p<i>` suffix). Step 1 here dispatches ONE chain-level Final Docs Updater that summarizes the ENTIRE chain — input is the consolidated `task_summaries` from every `plan_chain[*].task_summaries`. Result path: `docs_results/final_chain.json`. Per-plan docs commits stay intact; the chain-level commit adds a top-level summary to `README.md` / `CHANGELOG.md` only.

If a Phase Docs Updater was NOT dispatched for the last phase of the active plan (no compaction point after the last task): dispatch one now for that plan first (per-plan, with `_p<active>` suffix in multi-plan mode), then proceed to the chain-level summary if multi-plan.

If per-plan updaters already covered all phases: dispatch only the top-level chain summary (multi-plan) or the un-suffixed single-plan final (single-plan).

**Final DECISIONS.md projection (C2):** re-render `<worktree>/.orchestrator/DECISIONS.md` from the full union of `<active>.decisions_register` across every plan (iterate `state.plan_chain[*]` for multi-plan; top-level + `plan2_state` for legacy). Same format and atomic-write contract as Phase Transition T3 step 1.5. This is the canonical, end-of-run snapshot — the per-T3 projections are intermediate.

Build from the **Final Docs Updater Prompt Template** with:
- All files changed: consolidated from state file across all tasks (all plans for chain runs)
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: per scope rule above

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/docs_prompts/final{_chain | }.txt` and result path matching `{result_json_path}`. Missing/malformed result → ENV_BLOCKER ESCALATE.

### Step 1.5: Method Audit Validation (v2.11)

After the Final Docs Updater commit and before generating the Final Summary Report:

```bash
python3 <skill_dir>/scripts/validate_method_audit.py \
  --state <worktree>/.orchestrator/state.json
```

Parse the JSON output:

- `"passed": true` → proceed to Step 2.
- `"passed": false` → for each entry in `failures`, write a learning-log candidate event:

  ```json
  {
    "schema_version": "1",
    "phase": "phase_2",
    "risk_tier": "high",
    "event_type": "method_audit_violation",
    "severity": "high",
    "execution": {"task_id": "<id>", "issue_key": "method_audit_missing"},
    "subagent": {"role": "orchestrator", "model": "opus", "dispatch": "orchestrator"},
    "summary": "Task <id> missing required methods: <missing list>",
    "context": {
      "user_intent": "Validate that required disciplines were applied.",
      "agent_expectation": "All COMPLETE tasks emit method_audit evidence.",
      "actual_outcome": "Missing methods: <list>",
      "root_cause": "Sub-agent did not emit METHOD_AUDIT lines or evidence was incomplete.",
      "evidence": [{"kind": "missing_methods", "value": "<list>"}]
    },
    "improvement": {"target": "references/implementer-prompt.md",
                    "proposal": "Strengthen METHOD_AUDIT requirement or hook check.",
                    "experiment_link": null},
    "privacy": {"redacted": true, "notes": "Skill names only."}
  }
  ```
  Then halt:

  Substitute `<task_path_prefix>` in the message below per the active-tree resolution:
  - v2.13 multi-plan (`state.plan_chain` present): use `state.plan_chain[<N>].tasks` where `<N>` is the index that owns the failing task. If failures span multiple plans, list each prefix on its own line.
  - v2.12 legacy two-plan: `state.tasks` for `active_plan == "plan1"`, `state.plan2_state.tasks` for `active_plan == "plan2"`.
  - Single-plan: `state.tasks`.
  
  The validator script itself iterates all plans via `--active-plan auto`, but this user-facing diagnostic must point at the correct path so the operator edits the right node.

  ```
  Method audit FAILED for tasks: <comma-separated list>.

  To resolve, either:
    - Re-dispatch the failing task(s) with explicit instructions to emit
      METHOD_AUDIT: lines (see references/implementer-prompt.md).
    - If a method is genuinely not applicable, edit
      <task_path_prefix>.<id>.method_audit.waived in state.json with a reason,
      then re-run Phase 2.

  Validator output:
  <pretty-printed validator JSON>
  ```

  Do NOT call `close-run` — the run remains alive for the user's resolution. Standard hard-halt block applies.

### Step 2: Generate Final Summary Report

Before generating the report, invoke `Skill("superpowers:finishing-a-development-branch")` and include its recommendation in Cleanup Status.

**Stamp `state.timestamps.completed_at` (v2.16):** before close-run, set `state.timestamps.completed_at = <iso8601 now>` via atomic R-M-W of state.json. This is the canonical wall-clock end-marker that the Final Summary Report's "Total wall time" row depends on. If state.json write fails: the standard state-file write guardrail applies (hard halt). Observed regression: pre-v2.16 runs left `completed_at: null` even when `meta.json.outcome=success`, because nothing in the Phase 2 prose explicitly wrote it.

**Learning-log close-run (v2.8, v2.16 idempotent):** before printing the summary, close the
run record. Use `--outcome=success` when Phase 2 completes normally. The `--if-open` flag (v2.16) makes close-run a no-op when the run is already closed — important for chained meta-runs where the final child re-enters Phase 2 Step 2 after a chain handoff and would otherwise overwrite an earlier outcome:

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  python3 <skill_dir>/scripts/append_learning_event.py close-run \
    --run-id "$MAE_LEARNING_RUN_ID" \
    --outcome success --if-open >/dev/null 2>&1 || true
fi
```

Close-run failure is silent. The summary report below still prints unchanged.

**Archive run (F1):** call scripts/archive_run.sh with the worktree path, run ID (from MAE_LEARNING_RUN_ID), and outcome. Failure is silent — log to user but do NOT halt; close-run already succeeded.

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  <skill_dir>/scripts/archive_run.sh \
    --worktree "$WORKTREE_ABS" \
    --run-id "$MAE_LEARNING_RUN_ID" \
    --outcome success 2>&1 || echo "ARCHIVE: failed (see archive output above) — worktree retained"
fi
```

After archive completes, populate the "Archive" section of the Final Summary Report below using fields from `<worktree>/.orchestrator/state.json` `archive` object (written by archive_run.sh): `archive.tar_path`, `archive.size_bytes`, `archive.redacted`. If the archive call failed, write `FAILED` for archive_path and omit size/redacted. The worktree is always retained — record its absolute path.

Output:

```markdown
## Execution Summary

**Plan:** <path>
**Spec:** <path>
**Branch:** <branch name>
**Worktree:** <worktree path>
**State file:** <worktree_path>/.orchestrator/state.json
**Models:** Orchestrator=Opus, Sub-agents=Sonnet
**Date:** <YYYY-MM-DD>

### Tasks
| Task | Status | Risk | Size | Spec | Quality | Tier | Escalations | Review Retries | Verifier Retries | Duration |
|------|--------|------|------|------|---------|------|-------------|----------------|------------------|----------|
| Task 0 | COMPLETE | low | SMALL | 0.95 | 0.90 | PASS | 0 | 0 | — (batch) | <M> min |

### WARN-tier tasks (P4)

For each task across every plan's task tree (`<active>.tasks` for each value of `state.active_plan` — iterate over `state.plan_chain[*].tasks` for v2.13 multi-plan; top-level `state.tasks` + `state.plan2_state.tasks` for v2.12 legacy) where `review_tier == "WARN"`, list one row:
- `task_<id>` — spec=<score>, quality=<score> — warnings: <one-line summary from task_summaries.task_N.warnings>

If none: "WARN-tier tasks: 0".

### Quality trend (P4)

- First 5 task quality_score mean: <X.XX>
- Last 5 task quality_score mean: <Y.YY>
- Delta: <signed>
- Note: <"stable" | "declining — review recent tasks" | "improving">

(Pull from each plan's quality_trend — iterate `state.plan_chain[*].quality_trend` for v2.13 multi-plan, top-level + `state.plan2_state.quality_trend` for v2.12 legacy.)

### Performance
- Total wall time: <HH:MM from timestamps.started_at to completed_at>
- Longest task: Task N (<M> min)
- Total retries: <review_retries sum> review, <verifier_retries sum> verifier

### Changes Made
- `<file path>`: <one-line description>

### Verification Results
| Scope | Risk Level | Tests Run | Result |
|-------|------------|-----------|--------|

### Docs Updated
- `<file>`: <what was updated>

### Cleanup Status
- Worktree: **active** — branch `<name>` at `<path>`. Merge or delete when ready.
- Debug artifacts: none found
- Temp files: none found

### Archive (F1)

| Item | Value |
|------|-------|
| Archive path | `<archive_meta.tar_path or "FAILED">` |
| Size | `<bytes formatted>` |
| Redacted | `<yes/no>` |
| Worktree | `<still present at> <path>` |
| HTML report | `<file://path/to/REPORT.html or "FAILED (see render.log)">` |

### Remaining Risks
- <risk description>: <mitigation taken or "accepted">
```

### Step 3: Render HTML run report (F3)

After Step 2's archive completes (regardless of archive success/failure), invoke the HTML renderer:

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  ARCHIVE_DIR="$HOME/.claude/learning/kws-claude-multi-agent-executor/runs/$(date +%Y-%m-%d)/${MAE_LEARNING_RUN_ID}"
  if [ -d "$ARCHIVE_DIR/artifacts" ]; then
    python3 <skill_dir>/scripts/render_html_report.py \
      --archive-dir "$ARCHIVE_DIR" \
      --output "$ARCHIVE_DIR/artifacts/REPORT.html" \
      2>"$ARCHIVE_DIR/artifacts/render.log" || \
      echo "REPORT_RENDER: failed (see $ARCHIVE_DIR/artifacts/render.log)"
  fi
fi
```

Update state.json's `archive.report_html_path` if rendering succeeds (atomic R-M-W).

---

## Guardrails

These rules are absolute. No exceptions.

| Rule | Detail |
|------|--------|
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
| **Headless subprocess dispatch** | Verifier and Docs Updaters run via `claude -p --dangerously-skip-permissions` (never Agent tool). Results in `.orchestrator/{verifier,docs}_results/`. Missing result JSON → ENV_BLOCKER ESCALATE; check `.stdout` for diagnostics. |
| **Two-phase commits** | See Phase 1 Step 2.5. `chore:` orchestrator state and `feat:` code are always separate commits. |
| **PreToolUse hooks in worktree** | Phase 0 Step 2.5 writes `.claude/settings.json` blocking `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA`. |
| **PostToolUse hook is the only debug-artifact gate** | `<worktree>/.orchestrator/hooks/scan-debug-artifacts.sh` (materialized at Phase 0 Step 2.5) is runtime-enforced. The orchestrator does NOT run a parallel manual grep — that duplication was removed in v2.5.0 because prose discipline silently bypassed. If the hook is disabled or missing, fix it; do not re-introduce the manual scan. |
| **SubagentStop hook validates Implementer output structure** | `<worktree>/.orchestrator/hooks/check-implementer-output.sh` exits 2 if STATUS / SUMMARY / FILES_CHANGED / FILES_TEST_CHANGED (or COMMIT on DONE, ESCALATE fields on ESCALATE) are missing. Sub-agent auto-retries; no orchestrator action needed. |
| **Plan Reviewer is mechanical, not subjective** | Phase 0 Step 6.5 audits the plan/spec against a fixed rubric (missing Files, missing AC on MID/HIGH, contract mismatch, dep cycles, out-of-repo paths). Style/architecture suggestions are out of scope and MUST be ignored if the sub-agent returns them. BLOCKER issues halt with a batched user question; WARN issues are recorded and bypass. Skip the entire step via `preflight=off`. |
| **Effort scaling is heuristic and biased upward** | Phase 0 Step 6 assigns SMALL/MEDIUM/LARGE per task for tool budget and review/verification routing only. Task size is not a TDD skip condition: any Implementer task that writes or modifies executable code or behavior must use `superpowers:test-driven-development` and report RED evidence before implementation, whether SMALL, MEDIUM, or LARGE. Docs-only, config-only, or generated-only tasks may report TDD as not applicable. Mis-estimation is acceptable as mild over-engineering; never silently under-instruct a HIGH-risk task (risk_mult forces LARGE). |
| **Quality scoring thresholds are not user-configurable** | SPEC threshold 0.85, QUALITY threshold 0.75, WARN floors 0.70/0.60 (P4). Calibrated against the P6 eval suite. Re-tune only when re-calibrating against a new Claude version, not per-run. |
| **WARN tier does not retry** | A WARN-tier review proceeds to Verifier with warnings recorded in `task_summaries.task_N.warnings`. WARN exists to prevent burning the 3-retry budget on borderline work. Three consecutive WARN tasks → surface at next compaction (signal, not halt). |
| **`quality_trend` is rolling, max 10** | Phase 1 Step 2 appends `quality_score` to `<active>.quality_trend` (drop oldest at length 10). Each plan in a v2.13 chain has its own buffer at `state.plan_chain[N].quality_trend`. Mean-of-last-5 < mean-of-first-5 by > 0.10 → surface at next compaction. |
| **Parallel Implementer outputs must respect declared Files: blocks** | Step P.4 verifies each sub-worktree's `FILES_CHANGED` is a subset of its task's declared `Files:` block AND that no two sub-worktrees in the same group touched the same file. Violation halts the group, removes sub-worktrees, and re-dispatches the offender sequentially. Never silently merge an out-of-scope parallel edit. |
| **Sub-worktrees inherit safety + gate hooks** | Step P.1 copies `.claude/settings.json` and `.orchestrator/hooks/*.sh` into every sub-worktree. The settings.json absolute path MUST be rewritten to point at the sub-worktree, not the parent — otherwise hooks reference a different worktree's helper scripts and silently no-op. |
| **External-resource contention in parallel waves is the user's responsibility** | If two parallel tasks contend for the same DB port, file lock, or external service, mark one of them `serial: true` in the plan. The Phase 0 Step 6 partition respects `serial` and keeps such tasks in singleton groups. The skill cannot detect arbitrary external contention. |
| **Disable parallel dispatch via `parallel=off`** | Writes a degenerate `execution_plan` where every parallel group is singleton. Use when sub-worktree creation is constrained (shallow clones, low disk, fsmonitor races). |
| **Acceptance Criteria shell is primary PASS condition** | If a task has an `## Acceptance Criteria` block with executable shell, the Verifier runs those commands first. All must exit 0. Risk-tiered test instructions are the fallback when no AC block is present. |
| **Plan structural validation is mandatory** | Step 0.5 runs before worktree creation. A plan must have either `### Task N:` (H3, canonical) OR `## Task N:` (H2) task headers — neither present halts immediately. Detected level is persisted as `<active>.task_header_prefix` and used consistently in all downstream parsing, Plan Reviewer prompts, and sub-agent task excerpts. A plan with missing Files blocks halts with a user question. Never skip this gate. |
| **Ambiguity gate clears before risk assignment** | Step 3.5 must complete with zero unresolved ambiguities before Step 4 begins. Unclear task descriptions answered downstream cost one full sub-agent dispatch + reset cycle. |
| **Out-of-repo paths halt execution** | Files blocks referencing paths outside repo root halt at Phase 0 Step 3.5. Never infer a correction — always ask the user. |
| **Phase -1 self-spawn is the default** | Interactive invocations auto-detach unless `mode=interactive` is explicitly passed. The headless sentinel `<<HEADLESS_KWS_ORCHESTRATOR>>` distinguishes spawned instances. Self-spawn is gated by Phase 0 Steps 1, 2, 2.5 completing successfully — failures abort the spawn and surface to the user. |
| **`mode` field is always a string** | `state.mode ∈ {interactive_session, headless_pending, headless_running, headless_chained, plan2_running}`. Never null. Resume protocol (Phase 0 Step 0) dispatches on this value — null breaks the headless_pending branch. |
| **`active_plan` pointer is authoritative for plan selection** | All Phase 1 / Phase Transition / Phase 2 / Monitor code dereferences `<active>` per the resolution table near the top of this document. v2.13 multi-plan: integer index into `state.plan_chain[]`. v2.12 legacy: string `"plan1"` / `"plan2"`. Never assume top-level `state.tasks` is the active tree without checking — hard-coding it for a multi-plan run silently corrupts the chain. |
| **`last_completed_task` is the only authoritative "most recent" field** | Phase 1 Step 4 Agent Cleanup writes it. Monitor and any post-hoc query MUST use it — never `to_entries \| last` over `tasks` (key insertion order is mutated by re-writes; this caused a real observed bug). |
| **Spec-edit branch uses `spec_clarifications`, not `review_retries`** | When `SPEC_FAULT ∈ {spec_contradicts, unclear}`, increment `spec_clarifications` (max 3 per task). Implementer retry budget stays intact for actual implementer mistakes. |
| **Resume Chain trigger is deterministic** (v2.15) | Chain when EITHER token threshold OR legacy floor fires (additive). Token threshold: `session_input_tokens (= cost_ledger.totals.input_tokens − cached_read_tokens) ≥ state.context_budget.threshold_tokens`. Legacy floor: `compaction_points reached ≥ 2` AND `completed tasks ≥ 8` (always evaluated). `budget_action == "off"` disables the token trigger, leaving the legacy floor as the sole criterion. Chain procedure MUST update `headless.pid` atomically so Monitor sees `CHAIN_HANDOFF`, not `PROCESS_DIED`. |
| **`files_test` discrimination for batch verifier** | Implementer outputs `FILES_TEST_CHANGED` separately from `FILES_CHANGED`. T1 batch pre-filter uses it (or `.md`-only heuristic for legacy state) to route docs-only tasks to lint instead of test runs. |
| **Plan 2 re-takes baseline** | When Phase 2 Step -1 swaps `active_plan` to `"plan2"`, run Phase 0 Step 5 fresh against current HEAD (Plan 1's changes are now Plan 2's starting point). Never reuse Plan 1's baseline as Plan 2's regression reference. |
| **Learning log lifecycle (v2.8, v2.16 idempotent success)** | Phase 0 Step 7.5 calls `init-run` and exports `MAE_LEARNING_RUN_ID`. Phase 1 Step 3.5 scans `<worktree>/.orchestrator/learning_events/` for sub-agent candidate JSON and calls `append`. Phase 2 Step 2 closes with `outcome=success` AND `--if-open` (v2.16) — the flag makes success-close a no-op when the run is already terminal (e.g., a prior child in a chained meta-run already wrote `aborted` or `blocked`). Orchestrator-level abort closes with `outcome=aborted`; whole-orchestrator hard-halt (state-write fail, exhausted escalations halting the run) closes with `outcome=blocked`. **Halt-paths intentionally omit `--if-open`** so an outer halt overwrites an inner success when the run truly failed. Resume Chain preserves `MAE_LEARNING_RUN_ID` via env propagation and calls `append-session-id`, never `init-run`. **Learning-log failure must never block plan execution** — every helper invocation is wrapped with `\|\| true`. See `references/learning-log.md`. |
| **`state.timestamps.completed_at` is stamped at Phase 2 Step 2** (v2.16) | The first action of Step 2 is an atomic R-M-W of state.json setting `timestamps.completed_at = <iso8601 now>`. This is the canonical wall-clock end-marker; the Final Summary Report's "Total wall time" row depends on it. Pre-v2.16 runs left this field null even on `outcome=success` because nothing in the prose explicitly wrote it. State-file write failure here is a hard halt (existing guardrail). |
| **`timing.started` is stamped before Step 1 dispatch** (v2.16) | The "Before Step 1 of each task" block writes `<active>.tasks.task_<N>.timing.started = <iso8601 now>` via atomic R-M-W. Without this field the per-task duration column cannot be computed (observed: `jq strptime` errors across all v2.11–v2.15 runs because the field stayed null). Failure to write is a non-fatal warning, not a halt. |
| **Single-writer for learning events** | Only the orchestrator invokes the helper. Sub-agents write event candidates as JSON files under `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`; the orchestrator reads and forwards them. Never let a sub-agent prompt instruct direct helper invocation. |
| **`context_health` is observation-only (v2.10)** | Emitted at Phase Transition T3 and Resume Chain chained-orchestrator startup. Counts compaction index, completed tasks, chain handoffs. **MUST NOT alter orchestrator control flow** — Goodhart's-law guard. Behavior changes require a follow-on experiment under `docs/experiments/v2.10-context-health/` after ≥ 2 weeks of real-run data. See `references/learning-log.md`. |
| **Polite-stop anti-pattern is forbidden (v2.10.1)** | A sub-agent returning PASS / APPROVED is a checkpoint inside the autonomous loop, never a reporting moment. The orchestrator MUST proceed immediately to the next phase step in the same turn. The only legitimate reporting moments are: Phase 2 success completion, ESCALATE that exceeds `escalation_count > 3`, headless `HEADLESS_HALTED.txt`, or hook denial. Any prompt edit that introduces "summarize and wait for user acknowledgment" between PASS and the next step IS the regression this invariant exists to prevent. |
| **Cross-run isolation is enforced (v2.10.1)** | Phase 0 Step 1.5 refuses to start when another worktree of this skill has a live headless PID. Mode exclusivity is concurrent-safe by halt, not by lock — the user is responsible for choosing which run continues. Orphan worktrees with no state.json + >7d mtime are reported but never auto-deleted (may hold uncommitted manual debugging). |
| **Method audit fields are populated at Agent Cleanup (v2.11)** | Method audit fields are populated at Phase 1 Step 4 from structured sub-agent output. |
| **Method audit must pass before Phase 2 close-run** | Phase 2 Step 1.5 runs `scripts/validate_method_audit.py`. A task is `applied` only when it has evidence references (RED command, GREEN command, commands_run, findings_count). FAIL halts before close-run; user re-dispatches or edits `<active>.tasks.<id>.method_audit.waived` with a reason. v2.13: the validator must iterate every `state.plan_chain[N].tasks` for chain runs, not just top-level. |
| **Method audit fields populated at Phase 1 Step 4** | Orchestrator parses `METHOD_AUDIT:` from Implementer, `REVIEW_FINDINGS:` from Combined Reviewer, `commands_run` from Verifier result JSON. Written under `<active>.tasks` per the resolution table. |
| **TDD waive reasons are restricted** | `METHOD_AUDIT: tdd waived` accepts only `reason=docs-only-task`, `config-only-task`, or `generated-only-task`. Other reasons fail validation. |
| **Resource-key collisions force serialization in same wave** | Phase 0 Step 6 resource_key partition rule: tasks in the same wave that share a `**Resource Key:** <slug>` annotation are placed in singleton groups (never merged). The `serialization_reason: "resource_key=<key>"` field is written to each affected `<active>.execution_plan` group. WARN is emitted by the Plan Reviewer; correctness is automatic. |
| **`implementer_model` records both used and default** (v2.12) | Arg is parsed in the **interactive parent** (Phase -1 step b OR Phase 0 Step 7 when mode=interactive) and written into state.json. The headless child reads it FROM state.json — it cannot re-parse skill args since `claude -p` only sees the headless prompt text. Phase 0 Step 7 in the child preserves the field as-is. `state.implementer_model = {"used": <effective>, "default": "sonnet"}`. `default` is the contemporaneous skill default, NOT the parsed arg. Phase 1 Step 1 reads `used` and passes it as the Agent tool `model` parameter — `sonnet` may omit the parameter, `opus` MUST set it explicitly (omitting silently falls back to the agent default and invalidates A/B comparisons). **Parallel Sub-Flow Step P.2 dispatches MUST also pass `model`** under the same rule — forgetting it there silently downgrades parallel-merged tasks to Sonnet regardless of the run's selection. Reviewer and Verifier are unaffected — they always run on Sonnet for judge consistency. Plan 2 inherits Plan 1's selection. |
| **Multi-plan auto-chain detection** (v2.13) | Phase -1.0 Pass 2 scans `plan\d*=` keys. `plan=` is index 0, `plan2=` is index 1, etc. Gaps halt. Missing `specN=` for present `planN=` halts. Length 1 → v2.12 single-plan schema. Length ≥ 2 → `plan_chain[]` schema with `active_plan` as integer index. `manifest=` is mutually exclusive (reserved; halt if combined). |
| **NL keyword lexicon is fixed and conservative** (v2.13) | Phase -1.0 Pass 3 scans free-text tokens (excluding tokens with `/`, `.`, `=`, backticks) for the closed lexicon: opus/오푸스, sonnet/소넷, 순차/sequential/직렬/시리얼, 대화형/interactive. Explicit `key=value` always wins; NL fills unset keys only. Conflicts halt with batched question — never silently disambiguate. Lexicon additions require an ADR (see `docs/experiments/v2.13-natural-multi-plan/decisions/D001`). |
| **Phase -1 echo line is mandatory** (v2.13) | Before any other work, Phase -1.0 prints ONE line summarizing parsed args (plan count, implementer_model, parallel, mode, risk) with the source of each value (explicit / NL / default). This is the user's one chance to spot mis-interpretation before the headless subprocess detaches. The line goes to stdout of the interactive parent — visible even before the spawn. Never skip. |
| **`plan_chain[]` is authoritative when present** (v2.13) | When `state.plan_chain` exists in state.json, code MUST dereference `state.plan_chain[state.active_plan].*` for tasks, task_summaries, quality_trend, risk_levels, task_complexity, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review. Top-level `state.tasks` etc. are NOT written for multi-plan runs. `state.plan` and `state.spec` mirror `plan_chain[active].plan_path / .spec_path` for legacy reader convenience but are NOT the source of truth. `state.active_plan` is an integer (not a string) when chain is in use. |
| **Per-plan result file suffix** (v2.13) | Verifier/Docs Updater output JSON files under `.orchestrator/{verifier,docs}_results/` get a `_p<index>` suffix in multi-plan runs to avoid collision across plans (`batch_p0_2.json`, `phase_p1_4.json`, `final_p2.json`). Single-plan and legacy v2.12 two-plan runs keep their un-suffixed paths for compatibility. Aggregators that scan these directories must accept both shapes. |
| **Run-level args propagate across all chain plans** (v2.13) | `implementer_model`, `parallel`, `risk`, `docs_scope` are written to state.json top-level (NOT into each plan_chain entry). The Cross-Plan Trigger does NOT reset them at swap. Every plan in the chain inherits the same model selection, parallel toggle, etc. Plan-specific overrides are deliberately NOT supported — if a user wants different models for different plans, they invoke the skill once per plan, not as a chain. |
| **Cost ledger frozen pricing** | `scripts/price_table.py` hardcodes rates at commit time. Historical runs reflect contemporaneous rates — re-running with a later price_table does NOT retroactively recompute past runs. Update price_table when Anthropic adjusts rates; do NOT auto-fetch. |
| **Cost-accumulate helper is mandatory per dispatch** (v2.16) | Every sub-agent dispatch (Implementer / Reviewer / Verifier / Plan Reviewer / Docs Updater) ends with a `scripts/accumulate_cost.py` invocation in Phase 1 Step 4 substep 1.5. Pre-v2.16 prose ("extract usage from Agent result, update by_task atomically") was silently skipped in every observed run — `cost_ledger.totals.dispatches=0` across runs 1/2/3 confirmed the regression. The helper is single-call, flock-protected, and handles unknown-model and missing-usage gracefully. Skipping the helper call means budget cap (`budget_cap_usd`) and `chain_trigger_eval` token threshold cannot fire correctly. by_task key is `<plan>::<task>::<role>` so same-task multi-role dispatches don't overwrite. |
| **`budget_action=pause` halts at compaction boundaries only** | Budget is evaluated at Phase Transition T3 and Phase 2 Step 0 — never mid-task. Cost overruns within a single task complete the task, then the next compaction triggers halt. This is intentional: aborting mid-task wastes the in-flight dispatch. |
| **Cost ledger is run-level** | `cost_ledger`, `budget_cap_usd`, `budget_action` live at top-level state.json (never inside `plan_chain[N]`). Cross-plan chains accumulate one unified ledger. Per-plan totals derivable via `by_task` key prefix `<plan_index>::`. |
| **Archive on close-run is best-effort** | `scripts/archive_run.sh` is invoked AFTER `close-run` succeeds. Archive failure is logged but does NOT halt the orchestrator (the primary run already completed). The worktree is never auto-deleted by archive — user retains it for manual recovery if archive fails. |
| **Redaction is mandatory** | `redact_archive.py` MUST run before the tar moves to its final path. Redaction failure → tar discarded, `archive_meta.json` written with `redaction_applied: false, error: ...`, user-visible warning. Never write a non-redacted tar to `~/.claude/learning/`. |
| **Spec manifest is per-plan** (v2.15 C1) | `spec_manifest` lives under `<active>` per the v2.13 resolution rule. Each plan in a chain has its own manifest (sections + task_to_sections + fallback_policy). `task_to_sections` references are validated by the Plan Reviewer at Phase 0 Step 6.5 — unknown section IDs are BLOCKER. Manifest is rebuilt at the spec-edit branch (Phase 1 Step 2 sub-step 6.5). |
| **Decisions register is per-plan, append-only** (v2.15 C2) | `decisions_register` lives under `<active>`. Entries are never deleted — supersession is recorded via the `supersedes` field (still rendered, with strikethrough prefix). Empty `key_decision` from `task_summaries` is ignored (not appended). Append failure logs a warning and continues (best-effort). |
| **decision_conflict is a QUALITY issue, not SPEC** (v2.15 C2) | Combined Reviewer flags `decision_conflict` under `QUALITY_ISSUES`. Does NOT downgrade `SPEC_SCORE`. Standard `review_retries` budget applies — no spec-edit branch. Use it to nudge sub-agents toward consistency, not to halt. Intentional supersession (diff includes `supersedes <task_id>` comment) emits an ADVISORY note instead of an ISSUE. |
| **Token-based chain trigger is additive** (v2.15 C3) | C3's `session_input_tokens >= threshold_tokens` trigger fires *in addition to* the legacy `compactions ≥ 2 AND completed ≥ 8` floor. Never replaces. `budget_action=off` disables the token trigger (legacy is then the sole criterion). `session_input_tokens = cost_ledger.totals.input_tokens − cached_read_tokens`. One `chain_trigger_eval` event per Phase Transition T3 regardless of decision (telemetry for trigger lift). |

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
