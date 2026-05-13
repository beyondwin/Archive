---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation. NOTE — single-session execution is preferable for ≤5-task plans or plans with deep cross-task coupling (multi-agent overhead exceeds the parallelism win).
metadata:
  version: "2.8.0"
  updated_at: "2026-05-13"
---

# KWS Claude Multi-Agent Executor

## Overview

You are the **Orchestrator** running on Opus. Execute an implementation plan from start to finish autonomously using fresh Sonnet sub-agents. Do not ask the user for approval between tasks.

**At invocation, the user provides:**
- **Plan path** — path to the implementation plan document
- **Spec path** — path to the design spec document
- Optionally: `risk=<low|mid|high>` to override risk level for all tasks
- Optionally: `docs_scope=<file1,file2>` to override which docs are updated

---

## Phase -1: Mode Selection (Autonomy Gate)

At invocation, before any other work:

Detection (in order):
1. Parse skill arguments. Args are space-separated `key=value` pairs (e.g., `plan=/path/to/plan.md spec=/path/to/spec.md mode=interactive`).
2. If parsed args contain `mode=interactive` (case-insensitive): legacy single-session mode — skip Phase -1, proceed to Phase 0.
3. If invocation prompt contains literal `<<HEADLESS_KWS_ORCHESTRATOR>>` anywhere: this is the headless instance — skip Phase -1, proceed to Phase 0.
4. Otherwise: execute Self-Spawn Procedure below, then exit.

### Self-Spawn Procedure

**a. Run Phase 0 Steps 1, 2, 2.5 in interactive context.**

Execute Phase 0 Step 1 (working tree clean check), Step 2 (worktree creation), and Step 2.5 (safety hooks) now, in the interactive session. These steps are quick (~2 min) and must complete before the subprocess starts — the subprocess requires an existing worktree to operate in. If any of these steps fail, abort the spawn and surface the failure to the user. Do NOT proceed to step b.

**b. Initialize a minimal `.orchestrator/state.json` in the worktree.**

Write `<worktree_path>/.orchestrator/state.json` using the Write tool:
```json
{
  "schema_version": "2",
  "mode": "headless_pending",
  "interactive_setup_complete": true,
  "plan": "<plan path>",
  "spec": "<spec path>",
  "branch": "<branch name>",
  "worktree": "<worktree path>",
  "timestamps": {
    "interactive_setup_at": "<iso8601 now>",
    "headless_started_at": null,
    "completed_at": null
  }
}
```
Fill in actual values from Phase 0 Steps 1–2.5. The full state.json fields (analysis, risk_levels, baseline, etc.) will be populated by the headless instance in its Phase 0 run.

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
  jq '{current_task, mode, completed: (.tasks | to_entries | map(select(.value.status=="COMPLETE")) | length)}' <worktree>/.orchestrator/state.json

Completion check:
  test -f <worktree>/.orchestrator/HEADLESS_DONE.txt && cat <worktree>/.orchestrator/HEADLESS_DONE.txt
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
    # Use active_plan pointer to select the right task tree (Plan 1 vs Plan 2 nested).
    AP=$(jq -r '.active_plan // "plan1"' $WT/.orchestrator/state.json 2>/dev/null)
    if [ "$AP" = "plan2" ]; then TASKS_FILTER='.plan2_state.tasks'; else TASKS_FILTER='.tasks'; fi
    cur_c=$(jq -r "[$TASKS_FILTER[]|select(.status==\"COMPLETE\")]|length" $WT/.orchestrator/state.json 2>/dev/null || echo 0)
    cur_s=$(jq -r "[$TASKS_FILTER[]|select(.status==\"SKIPPED\")]|length" $WT/.orchestrator/state.json 2>/dev/null || echo 0)
    if [ "$cur_c" != "$prev_c" ] || [ "$cur_s" != "$prev_s" ]; then
      # P14: read explicit last_completed_task field (NOT JSON insertion order).
      latest=$(jq -r '.last_completed_task as $t | if $t then
                       (if .active_plan == "plan2" then .plan2_state.tasks[$t] else .tasks[$t] end)
                       | "\($t) \(.status) risk=\(.risk) review_retries=\(.review_retries // 0)"
                       else "(no task recorded yet)" end' \
                $WT/.orchestrator/state.json 2>/dev/null)
      echo "[$(date +%H:%M:%S)] [$AP] $latest | totals: ${cur_c}C ${cur_s}S"
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

**Trigger (deterministic, introspectable from state.json):**
Chain ONLY when **both** are observed by the headless instance just after Phase Transition T3:
- `state.compaction_points` reached **≥ 2** AND
- count of tasks with `status == "COMPLETE"` is **≥ 8**

Do NOT chain on token-count heuristics (not introspectable) or after every compaction point. If neither threshold is met, continue in the same subprocess.

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

This is a fallback — the primary expectation is that one headless subprocess completes a typical 10-25 task plan within its own context budget.

---

## Phase 0: Setup

0. **Check for existing state file (Resume Protocol):**
   Check if `<worktree_path>/.orchestrator/state.json` exists by attempting to read it.
   - If it does NOT exist: proceed normally to Step 1.
   - If it EXISTS and is valid JSON with `schema_version: "2"`:
     - If `"mode": "headless_pending"`: freshly-spawned headless instance — Phase -1 already ran Steps 1, 2, 2.5 in interactive context and wrote minimal state. **MUST skip Phase 0 Steps 1, 2, 2.5** (clean check, worktree creation, safety hooks — re-running breaks: `git status` flags pre-written `.orchestrator/` and `.claude/settings.json` as dirty; `git worktree add` errors on the existing branch). PROCEED with Phase 0 Step 0.5 onward (`0.5 → 3 → 3.5 → 4 → 5 → 6 → 7`) to populate baseline, risk_levels, compaction_points, full task data. After Step 7, update `state.json.mode` from `"headless_pending"` to `"headless_running"` and write.
     - If `"mode": "headless_running"`, `"headless_chained"`, `"plan2_running"`, `"interactive_session"`, or no mode field: Standard resume path — load all fields. Do NOT overwrite. Verify git branch and worktree match `state.branch` / `state.worktree`. Set internal tracking from state.json: `current_task`, `current_step_within_task`, `current_pre_task_sha`, per-task counters. Output: "Resuming from state file: Task <N>, Step <M> (mode=<value or null>)." Skip Phase 0 Steps 1–7 (setup already done). Go directly to Phase 1 at the recorded task/step.
   - If it EXISTS but is invalid (empty, malformed JSON):
     - Warn user: "State file exists but is corrupted at <path>. Recommend manual inspection before proceeding."
     - Do NOT overwrite. Halt.

0.5. **Validate plan file (pre-flight):**
   Read the plan file. Before proceeding:
   - If the file is unreadable or missing: halt. "Plan file not found or unreadable at <path>."
   - If no `### Task N:` sections are found: halt. "Plan has no `### Task N:` sections. Cannot execute."
   
   This gate runs before worktree creation — structural failures cost zero infrastructure.

1. **Check working tree is clean:**
   ```bash
   git status
   ```
   If there are uncommitted changes, stop immediately. Tell the user: "Working tree is dirty. Please commit or stash changes before running multi-agent-executor." Do not proceed.

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
   - Read the plan document. Extract the ordered task list: every `### Task N:` section with full text. Note any explicit phase groupings (e.g., `## Phase 1`, `## Phase 2`) — these define phase boundaries.
   - Read the spec document. Keep relevant sections in context for prompt construction.

3.5. **Validate document content (Ambiguity Gate):**
   After reading both documents, before assigning risk levels:

   1. **Missing Files blocks:** List every `### Task N:` section that has no `**Files:**` block. If any found: ask the user one short question — "Tasks N, M have no Files block. Should I infer from task descriptions, or halt for you to add them?" Halt until answered.

   2. **Ambiguity scan:** Check each task description for:
      - Verbs without referents: "fix the bug", "optimize the query", "update the config" — which one?
      - Missing acceptance thresholds: "improve performance" with no metric, "reduce errors" with no target
      - Named contracts (function/type/API names) in the task that contradict the spec — same entity, different name or signature
      
      For each ambiguity found: ask one targeted question. Halt until all are resolved. Do not proceed to risk assignment until all ambiguities are cleared.

   3. **Out-of-repo paths:** Verify all paths in `**Files:**` blocks resolve within the repo root. Any path that escapes (e.g., `../../other-repo/file.py`): halt. "Task N references path outside repo root: <path>. Resolve before proceeding."

   **Why this gate exists:** Every ambiguity caught here saves one Implementer dispatch + SPEC_BLOCKER escalation + git reset cycle downstream.

4. **Assign risk levels** to each task:
   - `low` — isolated change, single file or module, no shared state, no API surface change
   - `mid` — touches 2+ modules, shared state, moderate coupling, or config changes
   - `high` — cross-cutting change, database/schema/API surface, or explicitly marked high-risk in plan

   Record: `Task 0: low | Task 1: mid | ...` in your internal notes.

   After initial assignment: if a LOW task touches any file already touched by an earlier LOW task in the same plan, upgrade the LATER task to MID. Record the upgrade reason. This prevents batch Verifier from accumulating file-level conflicts.

   If the user provided `risk=<level>` override: apply it to all tasks. However, if any task's description in the plan contains the words 'high-risk', 'schema migration', 'database', 'API surface', or 'breaking change', log a warning: 'risk override applied but task N description suggests HIGH risk — proceeding with override as instructed.' Do not silently downgrade dangerous tasks.

5. **Take baseline test snapshot:**
   Before running: derive the test command from `Makefile`, `package.json`, `pyproject.toml`, or `Cargo.toml`. Record this exact command in state.json `test_command` field. Use this same command everywhere in the skill (Verifier prompts, Phase Transition batch Verifier). Verifiers do NOT need to re-derive the test command.

   Run the full test suite in the worktree before any changes:
   ```bash
   cd <worktree_path> && <test_command>
   ```
   Record: `baseline: <N> passing, <M> failing`. This is your regression reference — Verifiers must not introduce new failures beyond baseline.

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
   - **Compute `global_constraints.shared_files`:** Build a map of file → list of task IDs that touch it (from each task's `**Files:**` block). Keep only files referenced by ≥ 2 tasks. Write this to `state.global_constraints.shared_files` in Step 7. The Implementer template's *Shared files alert* reads from here — not from any external `analysis.json` (no such file exists in this skill).

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

     Heuristic biases upward — under-instructing is worse than mild over-engineering. Record per-task: `state.task_complexity.task_N = "SMALL" | "MEDIUM" | "LARGE"`.

     Effort-guidance strings (the Implementer prompt at Phase 1 Step 1 injects one of these into `{effort_guidance}`):
     - SMALL: `aim for ≤8 tool calls; skip TDD for trivial renames/aliases unless task explicitly says test required; do not add abstractions, helpers, or refactors`
     - MEDIUM: `aim for 10–25 tool calls; TDD recommended for new behavior; refactor only what the task touches`
     - LARGE: `aim for 25–60 tool calls; TDD required for any new logic; if you exceed 60 tool calls without DONE, ESCALATE with AMBIGUITY rather than continue`

   - **Compute `execution_plan` — waves + parallel groups (P2 — parallel dispatch):**

     After the dependency graph is built, compute waves greedily:
     - Wave 0 = all tasks with `deps == []`
     - Wave N = all tasks whose deps are all in waves 0..N-1
     - Tasks within a wave have no inter-dependency by construction.

     Within each wave, partition tasks into **parallel groups** by file-disjointness:
     1. Start with each task as its own singleton group.
     2. Greedily merge two groups iff the UNION of their declared `Files:` sets has no overlap AND no task in either group has a `serial: true` annotation in the plan.
     3. Tasks whose Files: blocks overlap any other in the same wave MUST stay in their own singleton group (run sequentially within the wave).

     Write to `state.execution_plan`:
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
   - `{spec_path}`, `{spec_full_text}` — the spec document
   - `{risk_levels_yaml}` — from Step 4 (YAML-formatted `task_N: <risk>`)
   - `{result_json_path}` — `<worktree_path>/.orchestrator/plan_review.json`

   **Dispatch headless** via `claude -p --dangerously-skip-permissions` (same pattern as Verifier — Phase 1 Step 3). Prompt path: `<worktree_path>/.orchestrator/plan_review_prompt.txt`. Result path: `<worktree_path>/.orchestrator/plan_review.json`. Missing/malformed result → log warning and proceed (Plan Reviewer is advisory; absence is NOT a halt).

   **Parse the result:**

   - `status: "PASS"` → record `state.plan_review = {status: "PASS", warnings: []}` at Step 7. Proceed.
   - `status: "ISSUES_FOUND"` →
     - Partition issues by severity: `BLOCKER` vs `WARN`.
     - All `WARN` only: record `state.plan_review = {status: "WARN", warnings: [...]}`. Log to user as a one-line summary. Proceed.
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
   Write `<worktree_path>/.orchestrator/state.json` using the Write tool:
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
     "global_constraints": {
       "shared_files": {}
     },
     "plan_review": {"status": "SKIPPED", "warnings": []},
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
     "timestamps": {
       "started_at": null,
       "completed_at": null
     }
   }
   ```
   Fill in the actual values from steps 4–6.

   **Mode field rule (P13a):** `mode` MUST always be a string — never `null`. Set to `"interactive_session"` when not under Phase -1 self-spawn, `"headless_running"` immediately after Phase 0 completes under `headless_pending` resume.

7.5. **Learning log init-run (v2.8):**

   After state.json is written, initialize the user-local learning log. This is observability — failure to init must NOT block plan execution.

   ```bash
   # Skill dir is the directory containing this SKILL.md.
   RUN_ID="$(python3 <skill_dir>/scripts/append_learning_event.py init-run \
     --repo-root "$WORKTREE_ABS" \
     --repo-name "$(basename $(git -C "$WORKTREE_ABS" rev-parse --show-toplevel))" \
     --branch "$(git -C "$WORKTREE_ABS" branch --show-current)" \
     --plan-path "$PLAN_PATH" \
     --spec-path "$SPEC_PATH" \
     --session-id "${CLAUDE_SESSION_ID:-}" 2>/dev/null || echo "")"
   if [ -n "$RUN_ID" ]; then
     export MAE_LEARNING_RUN_ID="$RUN_ID"
   fi
   ```

   `MAE_LEARNING_RUN_ID` is captured in shell env and used for the lifetime of the run. If helper init fails (script missing, write failure), `RUN_ID` is empty and no `MAE_LEARNING_RUN_ID` is exported — subsequent emit attempts (Phase 1/Transition/2) check the env var and skip silently. The plan execution proceeds normally.

   Sub-agents do NOT call the helper. They write event candidate JSON files to `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`. The orchestrator scans this directory after each cycle step and invokes `append` itself. See `references/learning-log.md` for the schema and 10 event types.

   **active_plan pointer (P13b):** `"plan1"` while executing the primary plan, `"plan2"` after Phase 2 Step -1 swap. Phase Transition / Phase 2 / Monitor scripts MUST use this pointer to select between `state.tasks` and `state.plan2_state.tasks` — see Phase 2 Step -1.

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

   Each task entry written into `tasks` (or `plan2_state.tasks`) later uses this format:
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

Iterate `state.execution_plan` (waves outer, parallel groups inner). Within each parallel group:
- **Singleton group** (one task): run the standard sequential per-task flow described below (Steps 1–4).
- **Multi-task group** (size ≥ 2): run the **Parallel Sub-Flow** (described after the standard flow). Combined Reviewer and Verifier still run sequentially after the parallel Implementer merge.

Within a wave, parallel groups run sequentially (not in parallel with each other) — the second parallel group of the same wave starts after the first group's Reviewer + Verifier have completed. This keeps the post-merge state deterministic.

Advance only when the current task (or parallel group) reaches Agent Cleanup successfully.

**Before Step 1 of each task:**
- Run `git -C <worktree_path> rev-parse HEAD` and **record the literal SHA** (e.g., `Task 3: pre_sha=abc1234`). Use this literal string in all subsequent revert and diff commands — do not use shell variables, which do not persist between Bash calls.
- Update `current_task` in the state file.

**Per-task counters (reset for each task — all are task-level):**
- `review_retries` — re-dispatches of Implementer due to Combined Reviewer FAIL (max 3)
- `verifier_retries` — re-dispatches due to Verifier FAIL (max 3)
- `escalation_count` — **task-level** counter of ESCALATE signals across all sub-agents this task (max 3 per task)
- `previous_issues` — Combined Reviewer ISSUES from the last retry (starts empty; used for retry-learning)

### Step 1: Dispatch Implementer

Build the implementer prompt from the **Implementer Prompt Template** below. Fill in:
- `{full text of the task}` — copy the entire `### Task N:` section verbatim
- `{relevant spec excerpt}` — spec section(s) that govern this task
- `{files to touch}` — from the task's **Files:** block
- `{risk level}` — from your Phase 0 assignment
- `{worktree_path}` — the worktree path
- `{deps_for_this_task}` — list of task IDs that this task depends on (from Phase 0 Step 6 dependency graph)
- `{task_size}` — SMALL / MEDIUM / LARGE from `state.task_complexity.task_N` (P5)
- `{effort_guidance}` — the matching guidance string from Phase 0 Step 6 (P5)

Re-dispatch rules (always append `## Fix Required\n{issues}`):
- After **Combined Reviewer FAIL**: include Required Skills bullet 4 (`receiving-code-review`).
- After **Verifier FAIL** or cleanup grep: do NOT include bullet 4.

Dispatch as a **fresh Sonnet sub-agent**.

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

Dispatch as a **fresh Sonnet sub-agent**.

**Parse scores first (P4):** the Reviewer emits `SPEC_SCORE` and `QUALITY_SCORE` (0.0–1.0, 1-decimal). Compute the **tier** by combining both axes:

| Tier | Condition |
|------|-----------|
| **PASS** | `SPEC_SCORE >= 0.85` AND `QUALITY_SCORE >= 0.75` |
| **WARN** | (PASS not met) AND `SPEC_SCORE >= 0.70` AND `QUALITY_SCORE >= 0.60` |
| **FAIL** | otherwise (either score below the WARN floor) |

Record per-task into the active task tree (`state.tasks.task_N` or `state.plan2_state.tasks.task_N`):
```json
"spec_score": <float>,
"quality_score": <float>,
"review_tier": "PASS | WARN | FAIL"
```

Update the rolling quality-trend buffer at top level (active-plan-aware):
- For `active_plan == "plan1"`: append `quality_score` to `state.quality_trend` (max 10, drop oldest).
- For `active_plan == "plan2"`: append to `state.plan2_state.quality_trend` (same rule).
- After append, if length ≥ 5 AND mean of last 5 < mean of first 5 by > 0.10: surface at the NEXT compaction point (T3 message) — `"Quality trending down: last 5 tasks averaged X.XX vs first 5 at Y.YY. Consider manual review of recent tasks."`. Do NOT halt automatically.

Then branch on tier:

**Tier: PASS** → proceed to Step 3.

**Tier: WARN** → proceed to Step 3, but ALSO:
1. Record the QUALITY_ISSUES (and any non-blocking SPEC_ISSUES) under `state.task_summaries.task_N.warnings = [...]` (active-tree-aware).
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
  - Re-dispatch Implementer with verifier's `issues` from the JSON under `## Fix Required`. Do NOT include `receiving-code-review`. Return to Step 1.
- If `verifier_retries` > 3: halt. Report to user: "Task N exceeded verifier retry limit (3). Manual intervention required."

**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 3.5: Learning-log candidate scan (v2.8)

After each Phase 1 cycle step (Step 1 Implementer, Step 2 Reviewer, Step 3 Verifier), check if a learning-event candidate file was written:

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

2. **Update state file** — write this task's result into the active task tree.

   **Active tree selection (P13b):** if `state.active_plan == "plan2"`, write under `state.plan2_state.tasks.task_N`; otherwise under `state.tasks.task_N`. Same rule for `task_summaries`.

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
     "timing": {
       "started": "<iso8601>",
       "implementer_done": "<iso8601>",
       "reviewer_done": "<iso8601>",
       "verifier_done": "<iso8601>",
       "completed": "<iso8601>"
     }
   }
   ```

   `files_test` comes from the Implementer's `FILES_TEST_CHANGED:` output (empty list if none). `complexity` comes from `state.task_complexity.task_N` (set in Phase 0 Step 6 per P5). `spec_score` / `quality_score` / `review_tier` come from Phase 1 Step 2 score parsing — PASS or WARN reached this point; FAIL would have looped back to Step 1.

   **Also update top-level latest pointers (P14)** — required for Monitor and any consumer that needs "most recent task":
   ```json
   "last_completed_task": "task_N",
   "last_completed_at":   "<iso8601>"
   ```
   Do NOT rely on JSON insertion order — this skill re-writes state.json many times and key order is unreliable (observed bug: a later spec-edit re-touch of an earlier task moved it to the end of insertion order, breaking `to_entries | last`).

   Also write to `task_summaries.task_N` (same active-tree rule):
   ```json
   {
     "files": ["<file1>", "..."],
     "exposed_apis": ["<new function/class/constant names added>"],
     "key_decision": "<≤15 words: the most important choice made>",
     "for_next_tasks": "<≤30 words: what downstream tasks must know — contracts, types, naming>"
   }
   ```

2.5. **Commit orchestrator state separately:**
   ```bash
   git -C <worktree_path> add .orchestrator/
   git -C <worktree_path> diff --cached --quiet || \
     git -C <worktree_path> commit -m "chore(<plan-slug>): task <N> orchestrator state"
   ```
   This keeps implementation commits (`feat:`) separate from orchestrator state commits (`chore:`). Reviewers can filter `git log --grep '^feat'` to see only code changes.

3. **Check for compaction point:** if this task is a compaction point, go to **Phase Transition** before advancing. Otherwise, advance to the next task.

### Parallel Sub-Flow (P2 — multi-task parallel group)

Triggered when the current parallel group from `state.execution_plan` has size ≥ 2.

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

In a single assistant message, emit N `Agent` tool calls — one per task in the group. Each prompt:
- Uses the same Implementer Prompt Template
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
0. **Pre-filter** (docs-only exclusion): For each task in `low_tasks_pending_verification`, read its entry under the active task tree (`state.tasks` or `state.plan2_state.tasks`). The task is docs-only if **either**:
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

2. **Actively drop prior task context:** from this point forward, do not reference individual task details from before this compaction point. Work only from your structured task summary (what you have in internal notes from Agent Cleanup steps). If you need details from an earlier task, re-read the state file — do not hold raw sub-agent output in active context.

**Phase Transition failure handling:**
- If T1 batch Verifier FAIL exceeds retries for any task: halt that task, record SKIPPED in state.json, continue Phase Transition.
- If T2 Phase Docs Updater sends ESCALATE: skip docs for this phase. Record `phase_docs_skipped: [<phase_id>]` in state.json. The Final Docs Updater in Phase 2 will recover.
- If T3 state file write fails (Write tool error or Read-back fails): **hard halt immediately** — 'State file write failed at <path>. Risk of state corruption. Manual inspection required.' Do not proceed.

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

### Step -1: Cross-Plan Trigger (only if multi-plan invocation)

Precondition: `state.plan2_state` is a non-null object initialized at Phase 0 Step 7 with `status: "queued"` (see Phase 0 Step 7). If `plan2_state` is null, this whole step is skipped — proceed to Step 0.

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

If `low_tasks_pending_verification` is non-empty: dispatch headless batch Verifier (same headless pattern as Phase Transition T1, using `batch_final.json` as result path). On PASS: clear the list. On FAIL: apply standard `verifier_retries` per affected task. Only after PASS proceed to Step 1.

This guarantees LOW task verification even when `compaction_points=[]` (short plans with no compaction points).

### Step 1: Final Docs Updater

If a Phase Docs Updater was NOT dispatched for the last phase (no compaction point after the last task): dispatch one now covering all remaining changes.

If phase updaters already covered all phases: dispatch the Final Docs Updater only for top-level summary docs (`CHANGELOG.md` and top-level README) to ensure the complete run is captured as a unit.

Build from the **Final Docs Updater Prompt Template** with:
- All files changed: consolidated from state file across all tasks
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: `<worktree_path>/.orchestrator/docs_results/final.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/docs_prompts/final.txt` and result path `<worktree_path>/.orchestrator/docs_results/final.json`. Missing/malformed result → ENV_BLOCKER ESCALATE.

### Step 2: Generate Final Summary Report

Before generating the report, invoke `Skill("superpowers:finishing-a-development-branch")` and include its recommendation in Cleanup Status.

**Learning-log close-run (v2.8):** before printing the summary, close the
run record. Use `--outcome=success` when Phase 2 completes normally:

```bash
if [ -n "${MAE_LEARNING_RUN_ID:-}" ]; then
  python3 <skill_dir>/scripts/append_learning_event.py close-run \
    --run-id "$MAE_LEARNING_RUN_ID" \
    --outcome success >/dev/null 2>&1 || true
fi
```

Close-run failure is silent. The summary report below still prints unchanged.

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

For each task in `state.tasks` (and `state.plan2_state.tasks`) where `review_tier == "WARN"`, list one row:
- `task_<id>` — spec=<score>, quality=<score> — warnings: <one-line summary from task_summaries.task_N.warnings>

If none: "WARN-tier tasks: 0".

### Quality trend (P4)

- First 5 task quality_score mean: <X.XX>
- Last 5 task quality_score mean: <Y.YY>
- Delta: <signed>
- Note: <"stable" | "declining — review recent tasks" | "improving">

(Pull from `state.quality_trend` and `state.plan2_state.quality_trend` when relevant.)

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

### Remaining Risks
- <risk description>: <mitigation taken or "accepted">
```

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
| **Effort scaling is heuristic and biased upward** | Phase 0 Step 6 assigns SMALL/MEDIUM/LARGE per task. SMALL skips TDD only for trivial renames; MEDIUM/LARGE require TDD. Mis-estimation is acceptable as mild over-engineering; never silently under-instruct a HIGH-risk task (risk_mult forces LARGE). |
| **Quality scoring thresholds are not user-configurable** | SPEC threshold 0.85, QUALITY threshold 0.75, WARN floors 0.70/0.60 (P4). Calibrated against the P6 eval suite. Re-tune only when re-calibrating against a new Claude version, not per-run. |
| **WARN tier does not retry** | A WARN-tier review proceeds to Verifier with warnings recorded in `task_summaries.task_N.warnings`. WARN exists to prevent burning the 3-retry budget on borderline work. Three consecutive WARN tasks → surface at next compaction (signal, not halt). |
| **`quality_trend` is rolling, max 10** | Phase 1 Step 2 appends `quality_score` to `state.quality_trend` (drop oldest at length 10). Mean-of-last-5 < mean-of-first-5 by > 0.10 → surface at next compaction. Plan 2 has its own buffer at `state.plan2_state.quality_trend`. |
| **Parallel Implementer outputs must respect declared Files: blocks** | Step P.4 verifies each sub-worktree's `FILES_CHANGED` is a subset of its task's declared `Files:` block AND that no two sub-worktrees in the same group touched the same file. Violation halts the group, removes sub-worktrees, and re-dispatches the offender sequentially. Never silently merge an out-of-scope parallel edit. |
| **Sub-worktrees inherit safety + gate hooks** | Step P.1 copies `.claude/settings.json` and `.orchestrator/hooks/*.sh` into every sub-worktree. The settings.json absolute path MUST be rewritten to point at the sub-worktree, not the parent — otherwise hooks reference a different worktree's helper scripts and silently no-op. |
| **External-resource contention in parallel waves is the user's responsibility** | If two parallel tasks contend for the same DB port, file lock, or external service, mark one of them `serial: true` in the plan. The Phase 0 Step 6 partition respects `serial` and keeps such tasks in singleton groups. The skill cannot detect arbitrary external contention. |
| **Disable parallel dispatch via `parallel=off`** | Writes a degenerate `execution_plan` where every parallel group is singleton. Use when sub-worktree creation is constrained (shallow clones, low disk, fsmonitor races). |
| **Acceptance Criteria shell is primary PASS condition** | If a task has an `## Acceptance Criteria` block with executable shell, the Verifier runs those commands first. All must exit 0. Risk-tiered test instructions are the fallback when no AC block is present. |
| **Plan structural validation is mandatory** | Step 0.5 runs before worktree creation. A plan without `### Task N:` headers halts immediately. A plan with missing Files blocks halts with a user question. Never skip this gate. |
| **Ambiguity gate clears before risk assignment** | Step 3.5 must complete with zero unresolved ambiguities before Step 4 begins. Unclear task descriptions answered downstream cost one full sub-agent dispatch + reset cycle. |
| **Out-of-repo paths halt execution** | Files blocks referencing paths outside repo root halt at Phase 0 Step 3.5. Never infer a correction — always ask the user. |
| **Phase -1 self-spawn is the default** | Interactive invocations auto-detach unless `mode=interactive` is explicitly passed. The headless sentinel `<<HEADLESS_KWS_ORCHESTRATOR>>` distinguishes spawned instances. Self-spawn is gated by Phase 0 Steps 1, 2, 2.5 completing successfully — failures abort the spawn and surface to the user. |
| **`mode` field is always a string** | `state.mode ∈ {interactive_session, headless_pending, headless_running, headless_chained, plan2_running}`. Never null. Resume protocol (Phase 0 Step 0) dispatches on this value — null breaks the headless_pending branch. |
| **`active_plan` pointer is authoritative for plan selection** | Phase 1 / Phase Transition / Phase 2 / Monitor scripts ALWAYS dereference `state.active_plan` (`"plan1"` → `state.tasks`, `"plan2"` → `state.plan2_state.tasks`). Never assume top-level `state.tasks` is the active tree. |
| **`last_completed_task` is the only authoritative "most recent" field** | Phase 1 Step 4 Agent Cleanup writes it. Monitor and any post-hoc query MUST use it — never `to_entries \| last` over `tasks` (key insertion order is mutated by re-writes; this caused a real observed bug). |
| **Spec-edit branch uses `spec_clarifications`, not `review_retries`** | When `SPEC_FAULT ∈ {spec_contradicts, unclear}`, increment `spec_clarifications` (max 3 per task). Implementer retry budget stays intact for actual implementer mistakes. |
| **Resume Chain trigger is deterministic** | Chain only when `compaction_points reached ≥ 2` AND `completed tasks ≥ 8`. No token-count heuristics — not introspectable. Chain procedure MUST update `headless.pid` atomically so Monitor sees `CHAIN_HANDOFF`, not `PROCESS_DIED`. |
| **`files_test` discrimination for batch verifier** | Implementer outputs `FILES_TEST_CHANGED` separately from `FILES_CHANGED`. T1 batch pre-filter uses it (or `.md`-only heuristic for legacy state) to route docs-only tasks to lint instead of test runs. |
| **Plan 2 re-takes baseline** | When Phase 2 Step -1 swaps `active_plan` to `"plan2"`, run Phase 0 Step 5 fresh against current HEAD (Plan 1's changes are now Plan 2's starting point). Never reuse Plan 1's baseline as Plan 2's regression reference. |
| **Learning log lifecycle (v2.8)** | Phase 0 Step 7.5 calls `init-run` and exports `MAE_LEARNING_RUN_ID`. Phase 1 Step 3.5 scans `<worktree>/.orchestrator/learning_events/` for sub-agent candidate JSON and calls `append`. Phase 2 Step 2 closes with `outcome=success`; orchestrator-level abort closes with `outcome=aborted`; whole-orchestrator hard-halt (state-write fail, exhausted escalations halting the run) closes with `outcome=blocked`. Resume Chain preserves `MAE_LEARNING_RUN_ID` via env propagation and calls `append-session-id`, never `init-run`. **Learning-log failure must never block plan execution** — every helper invocation is wrapped with `\|\| true`. See `references/learning-log.md`. |
| **Single-writer for learning events** | Only the orchestrator invokes the helper. Sub-agents write event candidates as JSON files under `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`; the orchestrator reads and forwards them. Never let a sub-agent prompt instruct direct helper invocation. |

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
