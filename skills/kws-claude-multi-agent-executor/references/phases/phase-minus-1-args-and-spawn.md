# Phase -1: Mode Selection, Argument Parser, Self-Spawn, Resume Chain

> **Loaded by**: `SKILL.md` Phase entry stub — orchestrator MUST `Read` this
> file at the start of any invocation before any other work.
>
> **Scope**: argument parsing (key=value + NL keyword passes), mode detection
> (interactive vs headless self-spawn), the self-spawn procedure (worktree +
> hooks + minimal state.json + headless subprocess), and the Resume Chain
> fallback that lets a long-running plan exceed a single subprocess context.
>
> **Why extracted**: this content is read once per invocation (at startup) and
> never again during the run. Keeping it in SKILL.md forced ~10k tokens to sit
> in the orchestrator prefix for the entire session. Extraction is v2.19 T1.1
> PoC — see `docs/experiments/v2.19-token-cost-optimization/` for rationale.

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

**b. Initialize a minimal `state.json` in `<orch_dir>`.**

All arg-derived values come from Phase -1.0's three-pass parser (`implementer_model`, plan/spec pairs, `parallel`, `mode`, etc.). The headless subprocess will NOT re-parse args — only the headless prompt text reaches it, NOT the original args. The interactive parent persists everything needed into state.json here.

Validate `implementer_model` value: must be `opus` or `sonnet` (case-insensitive). Unknown value → halt: `"Unknown implementer_model=<value>. Allowed: opus, sonnet."` Unset → use `"sonnet"`.

**AgentLens orchestration run-open (v2.17 — RUN-LEVEL, NULL-safe):**

Immediately before writing state.json, attempt to open an AgentLens orchestration run. The returned ID (or empty string if AgentLens is absent / errors out) is the value substituted into the `agentlens_orchestration_run` field of the JSON written below. This field is **run-level** (top-level of state.json, parallel to `cost_ledger`/`test_command`/`budget_cap_usd`) — one orchestrator invocation owns at most one AgentLens run regardless of plan_chain length.

```bash
ORCH_RUN_ID=$(agentlens run-open \
  --agent kws-cme-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta plan="$PLAN_PATH" \
  --meta spec="$SPEC_PATH" \
  2>/dev/null || echo "")
if [ -z "$ORCH_RUN_ID" ]; then
  echo "WARN: AgentLens unavailable (CLI missing or registry write failed); event observability disabled for this run. To enable, install agentlens CLI and rerun." >&2
fi
```

If `ORCH_RUN_ID` is empty (AgentLens CLI missing, registry write failure, etc.), substitute `null` into the JSON (not the empty string) so the field type is `string|null`. This is **never** a blocking failure — the orchestrator proceeds regardless. The single stderr WARN above is the one-shot user notification so AgentLens absence is not a silent degradation; downstream emits remain `2>/dev/null || true` no-ops. The value persists for the lifetime of the run and is read by Phase 0 / Phase 1 / Phase Transition / Phase 2 emit sites that publish events into AgentLens. (v2.17 cutover, Task 11: the legacy learning-log helper `append_learning_event.py` has been removed — AgentLens is now the sole event sink. See `scripts/compare_agentlens_events.py` for parity verification on historical runs.)

**Multi-plan vs single-plan write rules (v2.13):**

If the parsed plan list has length 1: write the minimal state.json in v2.12 shape (no `plan_chain` field). Substitute `$ORCH_RUN_ID` (or `null`) for the `agentlens_orchestration_run` field — the Write tool cannot capture shell variables, so template it in before calling Write:

```json
{
  "schema_version": "2",
  "mode": "headless_pending",
  "interactive_setup_complete": true,
  "plan": "<plan_path_0>",
  "spec": "<spec_path_0>",
  "branch": "<branch name>",
  "worktree": "<$HOME/.claude/worktrees/<RUN_ID>>",
  "orchestrator_dir": "<$HOME/.claude/orchestrator/<RUN_ID>>",
  "implementer_model": {"used": "<parsed value or sonnet>", "default": "sonnet"},
  "agentlens_orchestration_run": "<$ORCH_RUN_ID or null>",
  "timestamps": {
    "interactive_setup_at": "<iso8601 now>",
    "headless_started_at": null,
    "completed_at": null
  }
}
```

If the parsed plan list has length ≥ 2: write the v2.13 multi-plan minimal state.json. `state.plan` / `state.spec` mirror index 0 for legacy reader compatibility; the authoritative source is `plan_chain[]`. Same `agentlens_orchestration_run` substitution rule as the single-plan shape — `$ORCH_RUN_ID` (or `null`) is templated in at write time:

```json
{
  "schema_version": "2",
  "mode": "headless_pending",
  "interactive_setup_complete": true,
  "plan": "<plan_path_0>",
  "spec": "<spec_path_0>",
  "branch": "<branch name>",
  "worktree": "<$HOME/.claude/worktrees/<RUN_ID>>",
  "orchestrator_dir": "<$HOME/.claude/orchestrator/<RUN_ID>>",
  "implementer_model": {"used": "<parsed value or sonnet>", "default": "sonnet"},
  "agentlens_orchestration_run": "<$ORCH_RUN_ID or null>",
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

**c. Write the headless prompt at `<orch_dir>/headless_prompt.txt`:**

```
<<HEADLESS_KWS_ORCHESTRATOR>>
You are the kws-claude-multi-agent-executor running HEADLESSLY. No user available.
Working directory: <abs worktree path>
Orchestrator state dir: <abs orch_dir path>
Plan: <plan path>
Spec: <spec path>

Resume protocol applies — read <abs orch_dir path>/state.json. If state shows mode=headless_pending, proceed with full Phase 0 (analysis, baseline, dependency graph, state population). Otherwise resume from current_task.

Run Phase 0 → Phase 1 → Phase 2 to completion. NEVER ask for user input.
Halt only on: per-task escalation_count > 3 (record SKIPPED, continue) OR all tasks COMPLETE/SKIPPED.
On completion, write <abs orch_dir path>/HEADLESS_DONE.txt with summary.
On critical failure, write <abs orch_dir path>/HEADLESS_HALTED.txt with diagnostics.

Begin.
```

Fill in `<abs worktree path>`, `<abs orch_dir path>`, `<plan path>`, `<spec path>` with the actual resolved paths before writing. The headless child cwd's into `<abs worktree path>` for `git` operations but reads/writes state via the absolute `<abs orch_dir path>` because the two are no longer nested (v2.18).

**d. Spawn detached background process:**

`AGENTLENS_PARENT_RUN_ID` propagates the run ID captured in step b into the headless child's environment. The child reads it back as `ORCH_RUN_ID` (see Phase 0 Step 0 Resume Protocol; canonical name is `ORCH_RUN_ID` for all emit-site code) and guards every `agentlens event append` with `[ -n "${ORCH_RUN_ID:-}" ]`. If AgentLens was absent (step b set `$ORCH_RUN_ID=""`), the env var is empty and every emit becomes a silent no-op:

```bash
WORKTREE_ABS="$(cd <worktree> && pwd -P)"
ORCH_DIR="$HOME/.claude/orchestrator/<RUN_ID>"
mkdir -p "$ORCH_DIR"
(
  cd "$WORKTREE_ABS" || { echo "FATAL: cannot cd to $WORKTREE_ABS" >&2; exit 1; }
  AGENTLENS_PARENT_RUN_ID="${ORCH_RUN_ID:-}" \
  nohup claude -p --dangerously-skip-permissions \
    --output-format stream-json --verbose \
    "$(cat "$ORCH_DIR/headless_prompt.txt")" \
    > "$ORCH_DIR/headless.jsonl" 2>&1 &
  echo $! > "$ORCH_DIR/headless.pid"
  disown
)
```

The subshell `cd "$WORKTREE_ABS"` **enforces** the headless child's working directory at the OS level — the child inherits cwd from the spawning subshell, not from the parent's cwd. Pre-v2.18 prose relied on the child to `cd` itself via prompt instructions; that was fragile (any prompt drift caused `git` calls to run in the wrong tree). The subshell guarantees that even if the prompt instruction is misread, the cwd is correct. Both `WORKTREE_ABS` and `ORCH_DIR` must still be exported / inlined into the spawn because the child does not inherit shell variables.

**d.5. Verify spawn lived past startup**:
   ```bash
   sleep 3
   if ! kill -0 $(cat "$ORCH_DIR/headless.pid") 2>/dev/null; then
     echo "FATAL: headless subprocess died within 3 seconds. Check $ORCH_DIR/headless.jsonl for diagnostic." >&2
     # Read first 50 lines of headless.jsonl and surface to user; do NOT proceed to step e (no Monitor)
     exit 1
   fi
   ```
   If spawn died: report failure to user with diagnostic; do NOT continue.

**e. Report to user (final message before exit):**

```
Orchestrator running headless.
Worktree:   <abs worktree path>      (~/.claude/worktrees/<RUN_ID>/)
State dir:  <abs orch_dir path>      (~/.claude/orchestrator/<RUN_ID>/)
PID: $(cat <abs orch_dir path>/headless.pid)

Monitor live (stream-json events):
  tail -f <orch_dir>/headless.jsonl | jq -c 'select(.type=="text" or .type=="tool_use")'

Status snapshot:
  jq 'def active: if .plan_chain then .plan_chain[.active_plan] elif .active_plan=="plan2" then .plan2_state else . end; {current_task, mode, completed: (active.tasks | to_entries | map(select(.value.status=="COMPLETE")) | length)}' <orch_dir>/state.json

Completion check:
  test -f <orch_dir>/HEADLESS_DONE.txt && cat <orch_dir>/HEADLESS_DONE.txt

Quick queries (no LLM, ~10ms each):
  <skill_dir>/scripts/query_state.sh --orch-dir <abs_orch_dir> progress
  <skill_dir>/scripts/query_state.sh --orch-dir <abs_orch_dir> cost
  <skill_dir>/scripts/query_state.sh --orch-dir <abs_orch_dir> warn

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
OD="$ORCH_DIR"   # absolute path to ~/.claude/orchestrator/<RUN_ID>/
prev_c=0; prev_s=0

while true; do
  # Re-read PID each loop — Resume Chain (see below) may have replaced it.
  HEADLESS_PID=$(cat $OD/headless.pid 2>/dev/null || echo "")
  if [ -f $OD/state.json ]; then
    # Resolve active task tree (v2.13 plan_chain[N] > v2.12 plan2_state > top-level).
    HAS_CHAIN=$(jq -r '.plan_chain != null' $OD/state.json 2>/dev/null)
    AP=$(jq -r '.active_plan // "plan1"' $OD/state.json 2>/dev/null)
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
    cur_c=$(jq -r "[$TASKS_FILTER[]|select(.status==\"COMPLETE\")]|length" $OD/state.json 2>/dev/null || echo 0)
    cur_s=$(jq -r "[$TASKS_FILTER[]|select(.status==\"SKIPPED\")]|length" $OD/state.json 2>/dev/null || echo 0)
    if [ "$cur_c" != "$prev_c" ] || [ "$cur_s" != "$prev_s" ]; then
      # P14: read explicit last_completed_task field (NOT JSON insertion order).
      # last_completed_task lives under <active> for multi-plan; resolve same way.
      LCT_PATH=$(jq -r "if .plan_chain then .plan_chain[.active_plan].last_completed_task elif .active_plan==\"plan2\" then .plan2_state.last_completed_task else .last_completed_task end" $OD/state.json 2>/dev/null)
      if [ "$LCT_PATH" != "null" ] && [ -n "$LCT_PATH" ]; then
        latest=$(jq -r "$LATEST_FILTER[\"$LCT_PATH\"] | \"$LCT_PATH \\(.status) risk=\\(.risk) review_retries=\\(.review_retries // 0)\"" $OD/state.json 2>/dev/null)
      else
        latest="(no task recorded yet)"
      fi
      echo "[$(date +%H:%M:%S)] [$LABEL] $latest | totals: ${cur_c}C ${cur_s}S"
      prev_c=$cur_c; prev_s=$cur_s
    fi
  fi
  test -f $OD/HEADLESS_DONE.txt && echo "[$(date +%H:%M:%S)] DONE: $(head -1 $OD/HEADLESS_DONE.txt)" && exit 0
  test -f $OD/HEADLESS_HALTED.txt && echo "[$(date +%H:%M:%S)] HALTED: $(head -1 $OD/HEADLESS_HALTED.txt)" && exit 1
  if [ -n "$HEADLESS_PID" ] && ! kill -0 $HEADLESS_PID 2>/dev/null; then
    # Grace period for Resume Chain handoff — .pid is rewritten by the child.
    sleep 2
    NEW_PID=$(cat $OD/headless.pid 2>/dev/null || echo "")
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
   cat > "$ORCH_DIR/headless_chain_<N>_prompt.txt" <<EOF
   <<HEADLESS_KWS_ORCHESTRATOR>>
   Continue from state.json.
   Worktree: $WORKTREE_ABS
   Orchestrator state dir: $ORCH_DIR
   EOF
   ```
   (Note: use unquoted heredoc so `$WORKTREE_ABS` and `$ORCH_DIR` interpolate.)
4. Spawn child AND atomically swap the PID file so the Monitor watcher (step e′) picks up the new process. **Pass `AGENTLENS_PARENT_RUN_ID` explicitly** so the chained orchestrator publishes to the same AgentLens run as its parent (v2.17 — replaces the legacy `MAE_LEARNING_RUN_ID` propagation; see Task 11 cutover):
   ```bash
   (
     cd "$WORKTREE_ABS" || { echo "FATAL: cannot cd to $WORKTREE_ABS" >&2; exit 1; }
     env AGENTLENS_PARENT_RUN_ID="${ORCH_RUN_ID:-${AGENTLENS_PARENT_RUN_ID:-}}" \
       nohup claude -p --session-id "$RESUME_UUID" --dangerously-skip-permissions \
       --output-format stream-json --verbose \
       "$(cat "$ORCH_DIR/headless_chain_<N>_prompt.txt")" \
       > "$ORCH_DIR/headless_chain_<N>.jsonl" 2>&1 &
     CHILD_PID=$!
     disown
     # Atomic-ish swap: write-then-rename
     echo $CHILD_PID > "$ORCH_DIR/headless.pid.new"
     mv "$ORCH_DIR/headless.pid.new" "$ORCH_DIR/headless.pid"
   )
   sleep 3
   kill -0 $(cat "$ORCH_DIR/headless.pid") 2>/dev/null || { echo "FATAL: chain child died within 3s" >&2; exit 1; }
   ```
   Same subshell-cd enforcement as the initial spawn (Phase -1 step d) — the chain child inherits cwd from its spawning subshell, not from the parent orchestrator's working dir.
5. Parent exits **without calling `close-run`** — the run is still alive in the child. Child takes over. The Monitor watcher re-reads `headless.pid` each loop (see step e′) so the handoff is observed as `CHAIN_HANDOFF`, not `PROCESS_DIED`.

6. **Chained child startup (v2.17 — AgentLens session join):** at Phase 0 Step 0 (Resume Protocol), after detecting `state.mode == "headless_chained"`, the chained orchestrator does NOT open a new AgentLens run — `ORCH_RUN_ID` (propagated via `AGENTLENS_PARENT_RUN_ID` → re-exported on resume) refers to the original orchestrator run and remains in use across the handoff. The legacy `append-session-id` step is removed in v2.17 (see Task 11 cutover); AgentLens does not need a session-id append because it tracks events by run, not by session.

   **Emit a `kws-cme.context_health` snapshot (v2.17):** the chained orchestrator writes a candidate JSON to `<orch_dir>/learning_events/chain_handoff-orchestrator.json` and the candidate-drain loop (Phase 1 Step 3.5) publishes it to AgentLens as `kws-cme.context_health`. Use `phase: "phase_0"`, `execution.task_id: "chain_handoff"`, `execution.issue_key: "context_health_snapshot"`, `context.compaction_index: -1`, `context.completed_tasks_count: <count of COMPLETE tasks from state>`, `context.resume_chain_handoffs: <new chain depth>`. This marks the boundary in the event stream so downstream analysis can attribute pre/post-handoff metrics. Emit failure is silent.

This is a fallback — the primary expectation is that one headless subprocess completes a typical 10-25 task plan within its own context budget.
